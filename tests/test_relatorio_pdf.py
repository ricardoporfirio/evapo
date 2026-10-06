"""Verifica o documento entregue, suas interpretações e os dados de origem."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from evapo.relatorio_pdf import gerar_pdf_da_pasta


class RelatorioPDFTest(unittest.TestCase):
    def setUp(self):
        self.temporaria = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporaria.cleanup)
        self.pasta = Path(self.temporaria.name) / "roi"
        self.pasta.mkdir()
        self.registros = [
            dict(data="2025-06-16", satelite="LANDSAT_8", produto="ndvi",
                 pixels_totais=100, pixels_validos=80, pixels_ausentes=20,
                 cobertura_percentual=80, media=0.6, mediana=0.61,
                 desvio_padrao=0.1, minimo=-0.2, maximo=0.9,
                 q1=0.5, q3=0.7, p05=0.1, p95=0.8, amplitude=1.1,
                 intervalo_interquartil=0.2, base_area="ROI; centros dos pixels"),
            dict(data="2025-07-18", satelite="LANDSAT_8", produto="ndvi",
                 pixels_totais=100, pixels_validos=0, pixels_ausentes=100,
                 cobertura_percentual=0, media=float("nan"), mediana=float("nan"),
                 desvio_padrao=float("nan"), minimo=float("nan"), maximo=float("nan"),
                 q1=float("nan"), q3=float("nan"), p05=float("nan"), p95=float("nan"),
                 amplitude=float("nan"), intervalo_interquartil=float("nan"),
                 base_area="ROI; centros dos pixels"),
        ]
        self.gravar_csv()
        (self.pasta / "manifesto_roi.json").write_text(
            json.dumps({"L": 0.5, "mde": None, "resolucao": "nativa; ROI", "cenas": []}),
            encoding="utf-8",
        )

    def gravar_csv(self, nome="estatisticas_todas_cenas_roi.csv"):
        with (self.pasta / nome).open("w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=list(self.registros[0]), delimiter=";")
            escritor.writeheader()
            escritor.writerows(self.registros)

    def ler(self, destino):
        leitor = PdfReader(destino)
        return leitor, "\n".join(pagina.extract_text() for pagina in leitor.pages)

    def test_pdf_contem_teoria_interpretacao_e_figuras_sem_ler_rasters(self):
        figuras = self.pasta / "2025-06-16"
        figuras.mkdir()
        for tipo in ("mapa", "histograma"):
            Image.new("RGB", (100, 60), "green").save(figuras / f"ndvi_{tipo}.png")
        destino = self.pasta / "relatorio.pdf"
        with patch("rasterio.open") as raster:
            resultado = gerar_pdf_da_pasta(self.pasta, destino, {
                "nome": "Projeto <teste> & campo", "estado": {"notas": "Observação <campo>"},
            })
            raster.assert_not_called()
        self.assertEqual(resultado, destino)
        self.assertTrue(destino.read_bytes().startswith(b"%PDF-"))
        leitor, texto = self.ler(destino)
        self.assertGreater(len(leitor.pages), 3)
        for trecho in (
            "Síntese interpretativa", "Fundamentação teórica", "NDVI", "0,6000",
            "Sem dados", "Referências", "L = 0,1", "Projeto <teste> & campo",
            "Observação <campo>", "não estabelece", "USGS",
        ):
            self.assertIn(trecho, texto)
        self.assertIn("Relatório interpretativo", leitor.metadata.title)
        self.assertTrue(any(pagina.images for pagina in leitor.pages))

    def test_estatisticas_antigas_sem_manifesto_geram_pdf_sem_presumir_parametros(self):
        (self.pasta / "manifesto_roi.json").unlink()
        destino = self.pasta / "antigo.pdf"
        gerar_pdf_da_pasta(self.pasta, destino)
        _, texto = self.ler(destino)
        self.assertIn("não informado no manifesto", texto)
        self.assertIn("Manifesto da execução não disponível", texto)
        self.assertIn("Figura não disponível", texto)

    def test_pdf_pastagens_distingue_referencia_anual_da_data(self):
        for registro in self.registros:
            registro["vigor"] = "baixo"
        self.gravar_csv("estatisticas_por_vigor.csv")
        (self.pasta / "manifesto.json").write_text(json.dumps({
            "configuracao": {"area_analise": "ROI", "metodo": "classes anuais de vigor",
                             "limites_ndvi": None, "ano_camada": 2024, "L": 0.5},
            "grades": [],
        }), encoding="utf-8")
        destino = self.pasta / "pastagens.pdf"
        gerar_pdf_da_pasta(self.pasta, destino)
        _, texto = self.ler(destino)
        self.assertIn("Pastagens", texto)
        self.assertIn("2024", texto)
        self.assertIn("MapBiomas", texto)
        self.assertIn("vigor baixo", texto)

    def test_falha_preserva_pdf_anterior_e_csv_nao_escapa_da_pasta(self):
        destino = self.pasta / "relatorio.pdf"
        destino.write_bytes(b"documento anterior")
        self.registros[0]["data"] = "../fora"
        self.gravar_csv()
        with self.assertRaisesRegex(ValueError, "inválido"):
            gerar_pdf_da_pasta(self.pasta, destino)
        self.assertEqual(destino.read_bytes(), b"documento anterior")

    def test_estatisticas_ausentes_informam_como_prosseguir(self):
        (self.pasta / "estatisticas_todas_cenas_roi.csv").unlink()
        with self.assertRaisesRegex(ValueError, "estatísticas salvas"):
            gerar_pdf_da_pasta(self.pasta, self.pasta / "relatorio.pdf")
