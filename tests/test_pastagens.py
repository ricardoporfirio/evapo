"""Confere máscaras, NoData, limites de vigor e separação das estatísticas."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib
import numpy as np
import rasterio
from affine import Affine
from PIL import Image

matplotlib.use("Agg")

from evapo.analises.pastagens import processar_pastagens
from evapo.dados.camadas import exportar_poligonos, ler_classes_raster, ler_mascara_pastagem
from evapo.calculos.estatisticas import estatisticas_descritivas
from evapo.calculos.vigor import classificar_vigor
from evapo.relatorios.plots import mostrar_mapa


class PastagensTest(unittest.TestCase):
    def test_mapas_por_produto_preservam_area_e_mascara_e_figura_separada(self):
        ndvi = np.array([[0.1, 0.4, 0.8, np.nan], [0.95, np.nan, 0.2, 0.6]])
        produtos = {"ndvi": ndvi, "savi": ndvi * 0.75}
        roi = np.array([[True, True, True, False], [True, True, True, True]])
        pastagem = np.array([[True, True, True, False], [False, True, False, False]])
        conhecida = np.array([[True, True, True, False], [True, True, False, True]])
        grade = {
            "crs": "EPSG:32723", "transform": [30, 0, 500000, 0, -30, 7600000],
            "pendencias": [],
        }
        cena = {"data": "2025-06-16", "satelite": "LANDSAT_8"}
        with tempfile.TemporaryDirectory() as temporaria:
            destino = Path(temporaria) / "pastagens"
            with (
                patch("evapo.analises.pastagens.calcular_produtos_roi",
                      return_value=(produtos, roi, None, grade)),
                patch("evapo.analises.pastagens.ler_mascara_pastagem",
                      return_value=(pastagem, conhecida)),
                patch("evapo.analises.pastagens.mostrar_mapa", wraps=mostrar_mapa) as mapas,
                patch("evapo.relatorios.pdf.gerar_pdf_da_pasta"),
            ):
                registros = processar_pastagens(
                    [cena], {"geometry": {}}, Path(temporaria) / "pastagens.geojson",
                    destino=destino, limites_ndvi=(0.3, 0.6),
                )
            pasta = destino / cena["data"]
            self.assertEqual(len(registros), 6)
            self.assertEqual(mapas.call_count, 2)
            for chamada, (produto, dados) in zip(mapas.call_args_list, produtos.items()):
                np.testing.assert_array_equal(chamada.args[0], dados)
                self.assertEqual(chamada.args[-1], pasta / f"{produto}_mapa.png")
                # Inclui outros usos e áreas sem cobertura conhecida na camada de pastagem.
                self.assertTrue(np.isfinite(chamada.args[0][1, [0, 2]]).all())
                for sufixo in ("mapa", "histograma"):
                    with Image.open(pasta / f"{produto}_{sufixo}.png") as imagem:
                        imagem.verify()
            for nome in ("pastagem_mascara.png", "vigor_mapa.png"):
                with Image.open(pasta / nome) as imagem:
                    imagem.verify()
            for classe in ("baixo", "moderado", "alto"):
                self.assertEqual(list((pasta / classe).glob("*_mapa.png")), [])
            with (pasta / "estatisticas_produtos.csv").open(encoding="utf-8-sig") as arquivo:
                gerais = list(csv.DictReader(arquivo, delimiter=";"))
            self.assertEqual([int(r["pixels_validos"]) for r in gerais], [6, 6])
            geral = json.loads((pasta / "ndvi_histograma.json").read_text())
            baixo = json.loads((pasta / "baixo" / "ndvi_histograma.json").read_text())
            self.assertEqual(sum(geral["frequencias"]), 6)
            self.assertEqual(sum(baixo["frequencias"]), 1)
            html_data = (pasta / "relatorio.html").read_text(encoding="utf-8")
            self.assertIn('src="ndvi_mapa.png"', html_data)
            self.assertIn('src="pastagem_mascara.png"', html_data)
            html_classe = (pasta / "baixo" / "relatorio.html").read_text(encoding="utf-8")
            self.assertIn('src="../ndvi_mapa.png"', html_classe)

    def test_ndvi_limites_nuvens_e_outros_usos(self):
        ndvi = np.array([[-0.2, 0.3, 0.6, np.nan, 0.8, 1.1]])
        pastagem = np.array([[True, True, True, True, False, True]])
        classes = classificar_vigor(pastagem, ndvi, (0.3, 0.6))
        np.testing.assert_array_equal(classes, [[1, 2, 3, 4, 0, 4]])
        with self.assertRaises(ValueError):
            classificar_vigor(pastagem, ndvi, (0.6, 0.3))

    def test_vigor_anual_conserva_ausencias(self):
        pastagem = np.array([[True, True, True, True, True, False]])
        valores = np.array([[1, 2, 3, 0, np.nan, 3]])
        np.testing.assert_array_equal(
            classificar_vigor(pastagem, valores), [[1, 2, 3, 4, 4, 0]]
        )

    def test_estatisticas_por_classe_excluem_outros_usos(self):
        dados = np.array([[0.1, 0.3, 0.6, 0.9, np.nan]])
        classes = np.array([[1, 1, 2, 0, 1]])
        est = estatisticas_descritivas(dados, (0, 1), mascara_roi=classes == 1)
        self.assertEqual(est["pixels_totais"], 3)
        self.assertEqual(est["pixels_validos"], 2)
        self.assertAlmostEqual(est["media"], 0.2)
        self.assertAlmostEqual(est["cobertura_percentual"], 200 / 3)
        vazia = estatisticas_descritivas(
            dados, (0, 1), mascara_roi=classes == 3, permitir_area_vazia=True
        )
        self.assertEqual(vazia["pixels_totais"], 0)
        self.assertTrue(np.isnan(vazia["media"]))
        self.assertTrue(np.isnan(vazia["cobertura_percentual"]))

    def test_raster_reprojetado_nao_cria_classes_em_nodata(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "uso.tif"
            transformacao = Affine(30, 0, 500000, 0, -30, 7600000)
            with rasterio.open(
                caminho,
                "w",
                driver="GTiff",
                width=2,
                height=2,
                count=1,
                dtype="uint8",
                crs="EPSG:32723",
                transform=transformacao,
                nodata=255,
            ) as ds:
                ds.write(np.array([[15, 3], [255, 15]], dtype="uint8"), 1)
            grade = {"crs": "EPSG:32723", "transform": list(transformacao)[:6]}
            roi = np.array([[True, True], [True, False]])
            mascara, conhecida = ler_mascara_pastagem(caminho, grade, roi)
            np.testing.assert_array_equal(mascara, [[True, False], [False, False]])
            np.testing.assert_array_equal(conhecida, [[True, True], [False, False]])
            grade["transform"] = list(Affine(30, 0, 499970, 0, -30, 7600000))[:6]
            dados = ler_classes_raster(caminho, grade, (2, 3))
            self.assertTrue(np.isnan(dados[:, 0]).all())
            self.assertEqual(dados[0, 1], 15)
            self.assertTrue(np.isnan(dados[1, 1]))

    def test_poligonos_shp_geojson_preservam_buraco_e_roi(self):
        grade = {
            "crs": "EPSG:32723",
            "transform": list(Affine(30, 0, 500000, 0, -30, 7600000))[:6],
        }
        mascara = np.ones((3, 3), dtype=bool)
        mascara[1, 1] = False
        with tempfile.TemporaryDirectory() as pasta:
            for extensao in ("shp", "geojson"):
                caminho = Path(pasta) / f"pastagens.{extensao}"
                exportar_poligonos(mascara, grade, caminho)
                resultado, conhecida = ler_mascara_pastagem(
                    caminho, grade, np.ones_like(mascara)
                )
                np.testing.assert_array_equal(resultado, mascara)
                self.assertTrue(conhecida.all())
