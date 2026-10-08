"""Confere unidades térmicas, balanço de energia e concordância com pixels nativos."""

import csv
import json
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.windows import Window
import test_imagem_inteira as base

from evapo.cli import main
from evapo.calculos.energia import (
    calcular_emissividade, calcular_termicos, calcular_radiacoes, validar_temperatura_ar,
)
from evapo.mapa.leitura import ler_janela, consultar_pixel, localizar_extremo
from evapo.analises.processamento import calcular_produtos_roi
from evapo.calculos.produtos import PRODUTOS
from evapo.analises.timelapse import preparar_frames, montar_timelapse
from evapo.analises.pastagens import processar_pastagens


class EnergiaTest(unittest.TestCase):
    def test_emissividade_limites_do_modelo_executavel(self):
        pv, emissividade = calcular_emissividade(np.array([-0.2, 0.1, 0.2, 0.35, 0.5, 0.8, np.nan, 2]))
        np.testing.assert_allclose(pv[:6], [0, 0, 0, 0.25, 1, 1], atol=1e-6)
        np.testing.assert_allclose(emissividade[:6], [0.966, 0.966, 0.971, 0.97275, 0.978, 0.978], atol=1e-6)
        self.assertTrue(np.isnan(emissividade[6:]).all())

    def test_termicos_kelvin_emissividade_e_nodata(self):
        mtl = {
            "LEVEL1_RADIOMETRIC_RESCALING": {"RADIANCE_MULT_BAND_10": 0.0003342, "RADIANCE_ADD_BAND_10": 0.1},
            "LEVEL1_THERMAL_CONSTANTS": {"K1_CONSTANT_BAND_10": 774.8853, "K2_CONSTANT_BAND_10": 1321.0789},
        }
        radiancia_300k = 774.8853 / np.expm1(1321.0789 / 300)
        dn = (radiancia_300k - 0.1) / 0.0003342
        resultado = calcular_termicos(np.array([dn, dn, 0, np.nan]), mtl, np.array([1, 0.97, 1, 1]))
        np.testing.assert_allclose(resultado["temperatura_brilho"][:2], [300, 300], atol=1e-4)
        self.assertAlmostEqual(float(resultado["temperatura_superficie"][0]), 26.85, places=4)
        self.assertGreater(resultado["temperatura_superficie"][1], 26.85)
        self.assertAlmostEqual(float(resultado["radiacao_longa_emitida"][0]), 5.67e-8 * 300**4, places=3)
        self.assertTrue(np.isnan(resultado["radiancia_b10"][2:]).all())

    def test_saldo_sinal_distancia_e_temperatura_ar(self):
        mtl = {"IMAGE_ATTRIBUTES": {"SUN_ELEVATION": 30, "EARTH_SUN_DISTANCE": 1.02}}
        tau = np.array([0.75, np.nan, 0, 1.1])
        resultado = calcular_radiacoes(tau, mtl, 25, np.full(4, 0.98), np.full(4, 30), np.full(4, 0.2))
        curta = 1367 * 0.5 / 1.02**2 * 0.75
        longa = 0.85 * (-np.log(0.75))**0.09 * 5.67e-8 * 298.15**4
        emitida = 0.98 * 5.67e-8 * 303.15**4
        self.assertAlmostEqual(float(resultado["radiacao_curta_incidente"][0]), curta, places=3)
        self.assertAlmostEqual(float(resultado["saldo_radiacao"][0]), 0.8 * curta + 0.98 * longa - emitida, places=3)
        self.assertTrue(np.isnan(resultado["saldo_radiacao"][1:]).all())
        self.assertNotIn("radiacao_longa_incidente", calcular_radiacoes(tau, mtl))
        self.assertEqual(validar_temperatura_ar("25,5"), 25.5)
        self.assertIsNone(validar_temperatura_ar(""))
        for valor in ("abc", "nan", "inf", -273.15):
            with self.assertRaises(ValueError):
                validar_temperatura_ar(valor)


class EnergiaRasterTest(unittest.TestCase):
    def setUp(self):
        base.ImagemInteiraTest.setUp(self)
        self.cena = self.cenas[0]
        self.mde = self.pasta / "mde.tif"
        with rasterio.open(self.cena["caminho"]) as imagem:
            perfil = imagem.profile.copy()
        perfil.update(count=1, nodata=0)
        for caminho, valor in ((self.cena["caminho"].parent / "teste_B10.TIF", 30000), (self.mde, 500)):
            with rasterio.open(caminho, "w", **perfil) as arquivo:
                arquivo.write(np.full((1, 3, 4), valor, dtype="uint16"))
        self.cena["mtl"]["IMAGE_ATTRIBUTES"]["EARTH_SUN_DISTANCE"] = 1.01
        self.cena["mtl"]["LEVEL1_RADIOMETRIC_RESCALING"].update(
            RADIANCE_MULT_BAND_10=0.0003342, RADIANCE_ADD_BAND_10=0.1,
        )
        self.cena["mtl"]["LEVEL1_THERMAL_CONSTANTS"] = {
            "K1_CONSTANT_BAND_10": 774.8853, "K2_CONSTANT_BAND_10": 1321.0789,
        }

    def test_grade_nativa_consulta_e_extremo_concordam(self):
        produtos, _, _, grade = calcular_produtos_roi(self.cena, None, caminho_mde=self.mde, temperatura_ar=25)
        self.assertEqual(set(produtos), set(PRODUTOS))
        self.assertEqual(grade["pendencias"], [])
        vista, _, _, _ = ler_janela(self.cena, Window(0, 0, 4, 3), tamanho=None, mde=self.mde, temperatura_ar=25)
        for nome, dados in produtos.items():
            np.testing.assert_allclose(dados, vista[PRODUTOS[nome][0]], rtol=1e-5, equal_nan=True)
            self.assertTrue(np.isnan(dados[0, 0]))  # nuvem
        with rasterio.open(self.cena["caminho"]) as imagem:
            x, y = imagem.xy(1, 1)
        pixel = consultar_pixel(self.cena, x, y, mde=self.mde, temperatura_ar=25)
        self.assertAlmostEqual(pixel["valores"]["Saldo de radiação"], float(produtos["saldo_radiacao"][1, 1]), places=3)
        extremo = localizar_extremo(self.cena, "Temperatura superfície", mde=self.mde)
        self.assertAlmostEqual(extremo[2], float(np.nanmin(produtos["temperatura_superficie"])), places=4)
        parciais, _, _, grade = calcular_produtos_roi(self.cena, None)
        self.assertIn("temperatura_superficie", parciais)
        self.assertNotIn("albedo_superficie", parciais)
        self.assertNotIn("saldo_radiacao", parciais)
        self.assertTrue(grade["pendencias"])

    def test_cli_exporta_novos_produtos_com_unidades_e_metodo(self):
        saida = self.pasta / "energia"
        with patch("evapo.dados.metadados.descobrir_cenas", return_value=[self.cena]):
            codigo = main(["--sem-interface", "--sem-timelapse", "--saida", str(saida),
                           "--mde", str(self.mde), "--temperatura-ar", "25"])
        self.assertEqual(codigo, 0)
        pasta = saida / "imagem_completa"
        with (pasta / "estatisticas_todas_cenas_roi.csv").open(encoding="utf-8-sig") as arquivo:
            registros = list(csv.DictReader(arquivo, delimiter=";"))
        self.assertEqual({r["produto"] for r in registros}, set(PRODUTOS))
        self.assertEqual(next(r["unidade"] for r in registros if r["produto"] == "temperatura_superficie"), "°C")
        self.assertEqual(next(r["unidade"] for r in registros if r["produto"] == "saldo_radiacao"), "W/m²")
        for nome in PRODUTOS:
            self.assertTrue((pasta / self.cena["data"] / f"{nome}_mapa.png").is_file())
        produtos, _, _, _ = calcular_produtos_roi(self.cena, None, caminho_mde=self.mde, temperatura_ar=25)
        for nome, esperado in produtos.items():
            with rasterio.open(pasta / self.cena["data"] / "rasters" / f"{nome}.tif") as raster:
                np.testing.assert_array_equal(raster.read(1), esperado)
            histograma = json.loads((pasta / self.cena["data"] / f"{nome}_histograma.json").read_text())
            self.assertEqual(sum(histograma["frequencias"]), int(np.isfinite(esperado).sum()))
        html = (pasta / self.cena["data"] / "relatorio.html").read_text(encoding="utf-8")
        self.assertIn("°C", html)
        self.assertIn("W/m²", html)
        manifesto = json.loads((pasta / "manifesto_roi.json").read_text(encoding="utf-8"))
        self.assertEqual(manifesto["temperatura_ar_c"], 25)
        self.assertIn("Kelvin", manifesto["modelos_energia"])
        self.assertTrue((pasta / "relatorio.pdf").is_file())

    def test_timelapse_usa_os_mesmos_modelos(self):
        frames, resumo, grade = preparar_frames([self.cena], None, tamanho=4,
                                                caminho_mde=self.mde, temperatura_ar=25)
        nativos, _, _, _ = calcular_produtos_roi(self.cena, None, caminho_mde=self.mde, temperatura_ar=25)
        for nome in PRODUTOS:
            np.testing.assert_allclose(frames[0][nome], nativos[nome], rtol=1e-5, equal_nan=True)
        self.assertEqual(len(resumo), len(PRODUTOS))
        # Somente alguns produtos térmicos e de energia, para
        # conferir a seleção dinâmica no HTML e a exportação dos GIFs.
        selecionados = {k: v for k, v in frames[0].items() if k in {"ndvi", "rgb", "temperatura_superficie", "saldo_radiacao"}}
        arquivo = montar_timelapse([self.cena], [selecionados], self.pasta / "timelapse", grade)
        self.assertTrue((arquivo.parent / "timelapse_temperatura_superficie.gif").exists())
        self.assertTrue((arquivo.parent / "timelapse_saldo_radiacao.gif").exists())
        self.assertIn('value="saldo_radiacao"', arquivo.read_text(encoding="utf-8"))

    def test_pastagens_exporta_energia_por_classe(self):
        camada = self.pasta / "pastagens.tif"
        with rasterio.open(self.mde) as origem:
            perfil = origem.profile
        with rasterio.open(camada, "w", **perfil) as arquivo:
            arquivo.write(np.full((1, 3, 4), 15, dtype="uint16"))
        destino = self.pasta / "pastagens"
        # A exportação real das figuras/PDF é coberta pelo teste geral; aqui
        # verifica-se a máscara de pastagem, as três classes e os CSVs/HTMLs.
        with patch("evapo.analises.pastagens.mostrar_mapa"), patch("evapo.analises.pastagens.mostrar_histograma"), patch("evapo.relatorios.pdf.gerar_pdf_da_pasta"):
            registros = processar_pastagens([self.cena], None, camada, destino=destino,
                                           limites_ndvi=(0.3, 0.6), caminho_mde=self.mde, temperatura_ar=25)
        self.assertEqual(len(registros), 3 * len(PRODUTOS))
        saldo = next(r for r in registros if r["produto"] == "saldo_radiacao" and r["vigor"] == "baixo")
        self.assertEqual(saldo["pixels_validos"], 10)
        html = (destino / self.cena["data"] / "baixo" / "relatorio.html").read_text(encoding="utf-8")
        self.assertIn("W/m²", html)
        self.assertTrue((destino / "estatisticas_por_vigor.csv").exists())
