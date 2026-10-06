"""A consulta e os extremos devem usar o mesmo pixel nativo dos cálculos."""

import unittest

import numpy as np
import rasterio
import test_imagem_inteira as base

from evapo.leitura import consultar_pixel, ler_vista, localizar_extremo
from evapo.processamento import calcular_produtos_roi


class LeituraTest(unittest.TestCase):
    setUp = base.ImagemInteiraTest.setUp

    def test_pixel_negativo_e_extremo_correspondem_ao_raster(self):
        cena = self.cenas[0]
        with rasterio.open(cena["caminho"], "r+") as imagem:
            dados = imagem.read()
            dados[3, 1, 1] = 9171
            dados[4, 1, 1] = 5865
            imagem.write(dados)
            x, y = imagem.xy(1, 1)
        valores = consultar_pixel(cena, x, y)
        produtos, _, _, _ = calcular_produtos_roi(cena, None)
        self.assertEqual(valores["linha"], 1)
        self.assertEqual(valores["coluna"], 1)
        self.assertEqual(valores["valores"]["NDVI"], float(produtos["ndvi"][1, 1]))
        self.assertAlmostEqual(valores["valores"]["NDVI"], -0.656473, places=5)
        minimo = localizar_extremo(cena, "NDVI")
        self.assertEqual(minimo[:2], (x, y))
        self.assertEqual(minimo[2], valores["valores"]["NDVI"])

    def test_zoom_menor_que_pixel_conserva_valor_nativo(self):
        cena = self.cenas[0]
        with rasterio.open(cena["caminho"]) as imagem:
            x, y = imagem.xy(1, 1)
        dados, _, _, _ = ler_vista(cena, (x - 0.1, y - 0.1, x + 0.1, y + 0.1))
        self.assertEqual(dados["NDVI"].shape, (1, 1))
        self.assertEqual(
            float(dados["NDVI"][0, 0]), consultar_pixel(cena, x, y)["valores"]["NDVI"]
        )

    def test_qa_e_fora_da_imagem_na_consulta(self):
        cena = self.cenas[0]
        with rasterio.open(cena["caminho"]) as imagem:
            x, y = imagem.xy(0, 0)
        pixel = consultar_pixel(cena, x, y)
        self.assertTrue(np.isnan(pixel["valores"]["NDVI"]))
        self.assertEqual(pixel["qa"], 8)
        self.assertIsNone(consultar_pixel(cena, -1, -1))
