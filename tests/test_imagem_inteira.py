"""Confere análise sem desenho, seleção persistida e extensão total das cenas."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
from affine import Affine

from evapo.cli import main
from evapo.analises.processamento import calcular_produtos_roi
from evapo.mapa.roi import carregar_roi, salvar_imagem_inteira
from evapo.dados.selecao import filtrar_cenas_selecionadas, identificar_cena
from evapo.analises.timelapse import preparar_frames


class ImagemInteiraTest(unittest.TestCase):
    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporario.cleanup)
        self.pasta = Path(self.temporario.name)
        self.cenas = []
        for indice in range(2):
            pasta = self.pasta / f"cena_{indice}"
            pasta.mkdir()
            transformacao = Affine(30, 0, 500000 + indice * 180, 0, -30, 7600000)
            for nome, bandas in (
                ("imagem.tif", 7),
                ("teste_QA_PIXEL.TIF", 1),
                ("teste_QA_RADSAT.TIF", 1),
            ):
                dados = np.full(
                    (bandas, 3, 4), 10000 if bandas == 7 else 0, dtype="uint16"
                )
                if nome == "teste_QA_PIXEL.TIF":
                    dados[0, 0, 0] = 8  # nuvem
                if bandas == 7:
                    dados[:, 2, 3] = 0  # preenchimento
                with rasterio.open(
                    pasta / nome,
                    "w",
                    driver="GTiff",
                    count=bandas,
                    width=4,
                    height=3,
                    dtype="uint16",
                    crs="EPSG:32723",
                    transform=transformacao,
                ) as arquivo:
                    arquivo.write(dados)
            coeficientes = {}
            for banda in range(1, 8):
                coeficientes[f"REFLECTANCE_MULT_BAND_{banda}"] = 0.00002
                coeficientes[f"REFLECTANCE_ADD_BAND_{banda}"] = -0.1
            self.cenas.append(
                {
                    "caminho": pasta / "imagem.tif",
                    "data": f"2025-06-{16 + indice}",
                    "satelite": "LANDSAT_8",
                    "mtl": {
                        "IMAGE_ATTRIBUTES": {"SUN_ELEVATION": 30},
                        "LEVEL1_RADIOMETRIC_RESCALING": coeficientes,
                    },
                }
            )

    def test_grade_completa_com_qa_e_sem_recorte(self):
        produtos, mascara, rgb, grade = calcular_produtos_roi(self.cenas[0], None)
        self.assertEqual(mascara.shape, (3, 4))
        self.assertEqual(rgb.shape, (3, 4, 3))
        self.assertTrue(mascara.all())
        self.assertEqual(grade["janela"]["col_off"], 0)
        self.assertEqual(grade["janela"]["width"], 4)
        self.assertEqual(np.isfinite(produtos["ndvi"]).sum(), 10)

    def test_imagem_inteira_salva_escolha_das_datas(self):
        caminho = self.pasta / "selecao.geojson"
        salvar_imagem_inteira(
            caminho, imagens_selecionadas=[identificar_cena(self.cenas[1])]
        )
        selecao = carregar_roi(caminho)
        self.assertIsNone(selecao["geometry"])
        self.assertEqual(
            filtrar_cenas_selecionadas(self.cenas, selecao), [self.cenas[1]]
        )
        produtos, mascara, rgb, grade = calcular_produtos_roi(self.cenas[1], selecao)
        self.assertEqual(mascara.sum(), 12)
        self.assertEqual(np.isfinite(produtos["ndvi"]).sum(), 10)
        self.assertEqual(rgb.shape, (3, 4, 3))
        self.assertEqual(grade["janela"]["width"], 4)

    def test_timelapse_inclui_cenas_sem_intersecao(self):
        frames, registros, grade = preparar_frames(self.cenas, None, tamanho=10)
        self.assertEqual(grade["bounds"], [500000, 7599910, 500300, 7600000])
        self.assertEqual(grade["width"], 10)
        self.assertEqual(len(registros), 12)
        for frame in frames:
            self.assertEqual(np.isfinite(frame["ndvi"]).sum(), 10)

    def test_cli_sem_roi_gera_resultados_completos(self):
        with patch("evapo.dados.metadados.descobrir_cenas", return_value=self.cenas):
            resultado = main(
                [
                    "--sem-interface",
                    "--saida",
                    str(self.pasta / "saida"),
                    "--tamanho-frame",
                    "10",
                ]
            )
        self.assertEqual(resultado, 0)
        saida = self.pasta / "saida"
        self.assertFalse((saida / "roi").exists())
        self.assertTrue((saida / "imagem_completa" / "relatorio.html").is_file())
        self.assertTrue((saida / "imagem_completa" / "relatorio.pdf").is_file())
        self.assertTrue(
            (saida / "imagem_completa" / "timelapse" / "timelapse_rgb.gif").is_file()
        )
