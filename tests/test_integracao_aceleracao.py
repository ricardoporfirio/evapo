"""Confere configuração automática, diagnóstico e uso do mesmo estágio óptico."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import rasterio
import test_imagem_inteira as base
import test_mapa_desempenho as mapa_base

from evapo.cli import criar_parser, informar_aceleracao_final, main
from evapo.calculos.aceleracao import configurar_aceleracao, informacoes_aceleracao
from evapo.calculos.metodo import parametros_metodo
from evapo.calculos.opticos import calcular_indices_opticos
from evapo.calculos.produtos import PRODUTOS
from evapo.analises.processamento import calcular_produtos_roi
from evapo.analises.timelapse import preparar_frames
from evapo.mapa.leitura import ler_vista
from evapo.mapa.roi import selecionar_roi


class DiagnosticoAceleracaoTest(unittest.TestCase):
    def test_diagnostico_nao_exige_cenas_nem_interface(self):
        informacoes = {
            "backend": "numpy", "dispositivo": "CPU", "fabricante": "",
            "precisao": "float64/float32", "motivo": "CPU solicitada",
            "operacoes_gpu": [],
        }
        saida = io.StringIO()
        with patch("evapo.cli.configurar_aceleracao") as configurar, patch(
            "evapo.cli.informacoes_aceleracao", return_value=informacoes
        ), patch("evapo.dados.metadados.descobrir_cenas") as descobrir, patch(
            "matplotlib.use"
        ) as interface, redirect_stdout(saida):
            codigo = main([
                "--diagnostico-gpu", "--dispositivo", "cpu", "--entrada", "inexistente",
            ])
        self.assertEqual(codigo, 0)
        self.assertEqual(json.loads(saida.getvalue()), informacoes)
        configurar.assert_called_once_with("cpu")
        descobrir.assert_not_called()
        interface.assert_not_called()
        self.assertEqual(criar_parser().parse_args([]).dispositivo, "auto")

    def test_metodologia_guarda_snapshot_sem_inicializar_gpu(self):
        informacoes = {"backend": "numpy", "dispositivo": "CPU", "operacoes_gpu": []}
        with patch("evapo.calculos.metodo.informacoes_aceleracao", return_value=informacoes) as info:
            metodo = parametros_metodo()
        info.assert_called_once_with(inicializar=False)
        self.assertEqual(metodo["aceleracao"], informacoes)
        json.dumps(metodo)

    def test_relato_final_identifica_etapas_realmente_executadas_na_gpu(self):
        saida = io.StringIO()
        with patch("evapo.cli.informacoes_aceleracao", return_value={
            "backend": "opencl", "operacoes_gpu": ["indices_opticos"],
        }) as info, patch("evapo.cli.descricao_aceleracao", return_value="GPU de teste") as descricao:
            with redirect_stdout(saida):
                informar_aceleracao_final()
        info.assert_called_once_with(inicializar=False)
        descricao.assert_called_once_with(inicializar=False)
        self.assertIn("GPU de teste", saida.getvalue())
        self.assertIn("indices_opticos", saida.getvalue())

    def test_mapa_mostra_dispositivo_sem_detectar_na_thread_da_interface(self):
        teste = mapa_base.MapaDesempenhoTest()
        app = teste.criar_app()
        with patch("evapo.interface.sistema.descricao_aceleracao", return_value="GPU de teste") as descricao:
            app.exibir(teste.resultado(), 1)
        descricao.assert_called_once_with(inicializar=False)
        self.assertIn("GPU de teste", app.status.set.call_args.args[0])

    def test_seletor_herda_modo_cpu_sem_mutar_ambiente_global(self):
        with tempfile.TemporaryDirectory() as temporaria, patch.dict(
            os.environ, {"EVAPO_DISPOSITIVO": "auto"}
        ), patch("evapo.mapa.roi.subprocess.run", return_value=SimpleNamespace(returncode=0)) as executar, patch(
            "evapo.mapa.roi.carregar_roi", return_value={"geometry": None}
        ):
            selecionar_roi("imagem.tif", Path(temporaria) / "roi.geojson", dispositivo="cpu")
            self.assertEqual(executar.call_args.kwargs["env"]["EVAPO_DISPOSITIVO"], "cpu")
            self.assertEqual(os.environ["EVAPO_DISPOSITIVO"], "auto")


class FluxosOpticosAceleradosTest(unittest.TestCase):
    def setUp(self):
        base.ImagemInteiraTest.setUp(self)
        configurar_aceleracao("cpu")
        self.addCleanup(configurar_aceleracao, "auto")

    def test_fluxos_compartilham_estagio_e_preservam_l_mascaras_e_rgb(self):
        cena = self.cenas[0]
        with rasterio.open(cena["caminho"], "r+") as imagem:
            dados = imagem.read()
            dados[3, :2] = 7500
            dados[4, :2] = 15000
            imagem.write(dados)
        with rasterio.open(cena["caminho"].parent / "teste_QA_PIXEL.TIF", "r+") as arquivo:
            qa = arquivo.read(1)
            qa[1, 1], qa[1, 2] = 128, 32  # Água e neve.
            arquivo.write(qa, 1)
        with patch("evapo.analises.processamento.calcular_indices_opticos",
                   wraps=calcular_indices_opticos) as calcular:
            produtos, _, rgb, grade = calcular_produtos_roi(cena, None, L=0.2)
        self.assertEqual(calcular.call_args.kwargs["L"], 0.2)
        with patch("evapo.mapa.leitura.calcular_indices_opticos",
                   wraps=calcular_indices_opticos) as calcular:
            vista, _, _, _ = ler_vista(cena, tamanho=None, L=0.2)
        self.assertEqual(calcular.call_args.kwargs["L"], 0.2)
        with patch("evapo.analises.timelapse.calcular_indices_opticos",
                   wraps=calcular_indices_opticos) as calcular:
            frames, _, temporal = preparar_frames([cena], None, tamanho=10, L=0.2)
        self.assertEqual(calcular.call_args.kwargs["L"], 0.2)
        for nome in ("ndvi", "savi", "iaf", "albedo_toa"):
            self.assertIsInstance(produtos[nome], np.ndarray)
            np.testing.assert_allclose(produtos[nome], vista[PRODUTOS[nome][0]], equal_nan=True)
            np.testing.assert_allclose(produtos[nome], frames[0][nome], equal_nan=True)
        self.assertTrue(np.isnan(produtos["iaf"][1, 1:3]).all())
        self.assertTrue(np.isfinite(produtos["iaf"][1, 0]))
        self.assertTrue(np.isnan(produtos["ndvi"][0, 0]))
        np.testing.assert_allclose(rgb, vista["RGB"])
        np.testing.assert_allclose(rgb, frames[0]["rgb"])
        self.assertEqual(grade["aceleracao"]["backend"], "numpy")
        self.assertEqual(temporal["aceleracao"]["backend"], "numpy")

    def test_gpu_real_concorda_com_cpu_e_grade_registra_uso_apos_calculos(self):
        configurar_aceleracao("auto")
        informacoes = informacoes_aceleracao()
        if informacoes["backend"] != "opencl":
            if informacoes.get("gpus_detectadas"):
                self.fail("GPU detectada, mas a qualificação falhou: " + str(informacoes.get("motivo")))
            self.skipTest("Nenhuma GPU OpenCL disponível neste ambiente.")
        cena = self.cenas[0]
        forma = (256, 256)
        with rasterio.open(cena["caminho"]) as origem:
            perfil = origem.profile.copy()
        perfil.update(width=forma[1], height=forma[0])
        dn = np.full((7, *forma), 10000, dtype="uint16")
        dn[3], dn[4] = 7500, 15000
        dn[:, -1, -1] = 0
        for caminho, dados in (
            (cena["caminho"], dn),
            (cena["caminho"].parent / "teste_QA_PIXEL.TIF", np.zeros((1, *forma), dtype="uint16")),
            (cena["caminho"].parent / "teste_QA_RADSAT.TIF", np.zeros((1, *forma), dtype="uint16")),
        ):
            perfil["count"] = dados.shape[0]
            if "QA_PIXEL" in caminho.name:
                dados[0, 0, 0] = 8
                dados[0, 128, 128:130] = [128, 32]
            if "QA_RADSAT" in caminho.name:
                dados[0, 1, 1], dados[0, 1, 2] = 1 << 3, 1
            with rasterio.open(caminho, "w", **perfil) as destino:
                destino.write(dados)
        configurar_aceleracao("cpu")
        cpu, _, rgb_cpu, _ = calcular_produtos_roi(cena, None, L=0.2)
        configurar_aceleracao("auto")
        gpu, _, rgb_gpu, grade = calcular_produtos_roi(cena, None, L=0.2)
        self.assertEqual(grade["aceleracao"]["backend"], "opencl")
        self.assertIn("opticos", grade["aceleracao"]["operacoes_gpu"])
        for nome in cpu:
            np.testing.assert_array_equal(np.isfinite(cpu[nome]), np.isfinite(gpu[nome]))
            np.testing.assert_allclose(cpu[nome], gpu[nome], rtol=1e-5, atol=2e-6, equal_nan=True)
        np.testing.assert_allclose(rgb_cpu, rgb_gpu, rtol=1e-5, atol=2e-6)


if __name__ == "__main__":
    unittest.main()
