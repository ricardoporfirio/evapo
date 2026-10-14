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
    calcular_emissividade, calcular_emissividades_sebal, calcular_proporcao_vegetacao,
    calcular_termicos, calcular_radiacoes, validar_temperatura_ar,
)
from evapo.mapa.leitura import ler_janela, consultar_pixel, localizar_extremo
from evapo.analises.processamento import calcular_produtos_roi
from evapo.calculos.produtos import PRODUTOS
from evapo.analises.timelapse import preparar_frames, montar_timelapse
from evapo.analises.pastagens import processar_pastagens


class EnergiaTest(unittest.TestCase):
    def test_pv_descritivo_nao_determina_emissividade(self):
        ndvi = np.array([-0.2, 0.1, 0.2, 0.35, 0.5, 0.8, np.nan, 2])
        pv = calcular_proporcao_vegetacao(ndvi)
        np.testing.assert_allclose(pv[:6], [0, 0, 0, 0.25, 1, 1], atol=1e-6)
        self.assertTrue(np.isnan(pv[6:]).all())
        _, larga = calcular_emissividade(ndvi, np.ones(8))
        np.testing.assert_allclose(larga[1:6], 0.96, atol=1e-6)
        self.assertTrue(np.isnan(larga[[0, 6, 7]]).all())
        with self.assertRaisesRegex(ValueError, "IAF"):
            calcular_emissividade(ndvi)

    def test_emissividades_sebal_iaf_agua_neve_e_qa(self):
        ndvi = np.array([0.1, 0.2, 0.35, 0.5, 0.8, -0.2, 0.3, 0.3, 0.3, 0.3, -0.1, 0.3])
        iaf = np.array([0, 1, 2, 3, 6, np.nan, np.nan, 2, 2, 2, 0, -1])
        qa = np.array([0, 0, 0, 0, 0, 128, 128, 32, 128 | 32, 128 | 8, 0, 0], dtype="uint16")
        estreita, larga = calcular_emissividades_sebal(ndvi, iaf, qa)
        np.testing.assert_allclose(estreita[:7], [0.97, 0.9733, 0.9766, 0.98, 0.98, 0.99, 0.99], atol=1e-6)
        np.testing.assert_allclose(larga[:7], [0.95, 0.96, 0.97, 0.98, 0.98, 0.985, 0.985], atol=1e-6)
        self.assertTrue(np.isnan(estreita[7:]).all())
        self.assertTrue(np.isnan(larga[7:]).all())

    def test_termicos_kelvin_emissividade_e_nodata(self):
        mtl = {
            "LEVEL1_RADIOMETRIC_RESCALING": {"RADIANCE_MULT_BAND_10": 0.0003342, "RADIANCE_ADD_BAND_10": 0.1},
            "LEVEL1_THERMAL_CONSTANTS": {"K1_CONSTANT_BAND_10": 774.8853, "K2_CONSTANT_BAND_10": 1321.0789},
        }
        radiancia_300k = 774.8853 / np.expm1(1321.0789 / 300)
        dn = (radiancia_300k - 0.1) / 0.0003342
        resultado = calcular_termicos(
            np.array([dn, dn, 0, np.nan]), mtl,
            np.array([1, 0.97, 1, 1]), np.array([1, 0.95, 1, 1]),
        )
        np.testing.assert_allclose(resultado["temperatura_brilho"][:2], [300, 300], atol=1e-4)
        self.assertAlmostEqual(float(resultado["temperatura_superficie"][0]), 26.85, places=4)
        self.assertGreater(resultado["temperatura_superficie"][1], 26.85)
        self.assertAlmostEqual(float(resultado["radiacao_longa_emitida"][0]), 5.67e-8 * 300**4, places=3)
        ts_kelvin = 300 / (1 + (10.895e-6 * 300 / 1.438e-2) * np.log(0.97))
        self.assertAlmostEqual(float(resultado["temperatura_superficie"][1]), ts_kelvin - 273.15, places=4)
        self.assertAlmostEqual(float(resultado["radiacao_longa_emitida"][1]), 0.95 * 5.67e-8 * ts_kelvin**4, places=3)
        self.assertTrue(np.isnan(resultado["radiancia_b10"][2:]).all())

    def test_saldo_sinal_distancia_e_temperatura_ar(self):
        mtl = {"IMAGE_ATTRIBUTES": {"SUN_ELEVATION": 30, "EARTH_SUN_DISTANCE": 1.02}}
        tau = np.array([0.75, np.nan, 0, 1.1])
        resultado = calcular_radiacoes(tau, mtl, 25, np.full(4, 0.95), np.full(4, 30), np.full(4, 0.2))
        curta = 1367 * 0.5 / 1.02**2 * 0.75
        longa = 0.85 * (-np.log(0.75))**0.09 * 5.67e-8 * 298.15**4
        emitida = 0.95 * 5.67e-8 * 303.15**4
        self.assertAlmostEqual(float(resultado["radiacao_curta_incidente"][0]), curta, places=3)
        self.assertAlmostEqual(float(resultado["saldo_radiacao"][0]), 0.8 * curta + 0.95 * longa - emitida, places=3)
        self.assertTrue(np.isnan(resultado["saldo_radiacao"][1:]).all())
        self.assertNotIn("radiacao_longa_incidente", calcular_radiacoes(tau, mtl))
        self.assertEqual(validar_temperatura_ar("25,5"), 25.5)
        self.assertIsNone(validar_temperatura_ar(""))
        for valor in ("abc", "nan", "inf", -273.15):
            with self.assertRaises(ValueError):
                validar_temperatura_ar(valor)

    def test_radiacoes_invalidam_parametros_fora_do_dominio_fisico(self):
        mtl = {"IMAGE_ATTRIBUTES": {"SUN_ELEVATION": 30, "EARTH_SUN_DISTANCE": 1}}
        resultado = calcular_radiacoes(
            np.array([0.75, 0.75, 0.75, 0.75, 1, 1e-6]), mtl, 25,
            np.array([0.95, 1.01, 0.95, 0.95, 0.95, 0.95]),
            np.array([30, 30, -273.15, 30, 30, 30]),
            np.array([0.2, 0.2, 0.2, 1.01, 0.2, 0.2]),
        )
        self.assertTrue(np.isfinite(resultado["saldo_radiacao"][0]))
        self.assertTrue(np.isnan(resultado["saldo_radiacao"][1:]).all())
        self.assertTrue(np.isnan(resultado["emissividade_atmosferica"][4:]).all())


class EnergiaRasterTest(unittest.TestCase):
    def setUp(self):
        base.ImagemInteiraTest.setUp(self)
        self.cena = self.cenas[0]
        # Terreno com NDVI positivo, dentro do domínio da emissividade SEBAL.
        with rasterio.open(self.cena["caminho"], "r+") as imagem:
            nir = imagem.read(5)
            nir[nir > 0] = 12000
            imagem.write(nir, 5)
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

    def test_agua_e_neve_nos_produtos_nativos(self):
        with rasterio.open(self.cena["caminho"].parent / "teste_QA_PIXEL.TIF", "r+") as arquivo:
            qa = arquivo.read(1)
            qa[1, 1] = 1 << 7
            qa[1, 2] = 1 << 5
            arquivo.write(qa, 1)
        produtos, _, _, _ = calcular_produtos_roi(self.cena, None, caminho_mde=self.mde, temperatura_ar=25)
        self.assertAlmostEqual(float(produtos["emissividade_b10"][1, 1]), 0.99, places=6)
        self.assertAlmostEqual(float(produtos["emissividade"][1, 1]), 0.985, places=6)
        self.assertTrue(np.isfinite(produtos["temperatura_superficie"][1, 1]))
        self.assertTrue(np.isfinite(produtos["temperatura_brilho"][1, 2]))
        for nome in ("emissividade_b10", "emissividade", "temperatura_superficie", "radiacao_longa_emitida", "saldo_radiacao"):
            self.assertTrue(np.isnan(produtos[nome][1, 2]), nome)

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

    def test_distancia_ausente_usa_data_em_todos_os_fluxos(self):
        self.cena["mtl"]["IMAGE_ATTRIBUTES"].pop("EARTH_SUN_DISTANCE")
        # A data da cena também atende metadados antigos sem DATE_ACQUIRED.
        self.cena["mtl"]["IMAGE_ATTRIBUTES"].pop("DATE_ACQUIRED", None)
        nativos, _, _, grade = calcular_produtos_roi(
            self.cena, None, caminho_mde=self.mde, temperatura_ar=25,
        )
        vista, _, _, _ = ler_janela(
            self.cena, Window(0, 0, 4, 3), tamanho=None, mde=self.mde, temperatura_ar=25,
        )
        frames, _, _ = preparar_frames(
            [self.cena], None, tamanho=4, caminho_mde=self.mde, temperatura_ar=25,
        )
        self.assertIn("Aproximação", grade["solar"]["fonte"])
        self.assertTrue(np.isfinite(nativos["saldo_radiacao"][1, 1]))
        for nome in ("radiacao_curta_incidente", "saldo_radiacao"):
            np.testing.assert_allclose(vista[PRODUTOS[nome][0]], nativos[nome], equal_nan=True)
            np.testing.assert_allclose(frames[0][nome], nativos[nome], equal_nan=True)

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
