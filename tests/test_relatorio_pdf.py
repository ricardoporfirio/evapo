"""Verifica o documento entregue, suas interpretações e os dados de origem."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from evapo.relatorios.pdf import gerar_pdf_da_pasta


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
            json.dumps({"metodologia_versao": 2, "L_iaf": 0.1, "L": 0.5,
                        "mde": None, "resolucao": "nativa; ROI", "cenas": []}),
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

    def preparar_pastagens(self, imagem_inteira=False):
        self.pasta = Path(self.temporaria.name) / (
            "pastagens_imagem_completa" if imagem_inteira else "pastagens"
        )
        self.pasta.mkdir()
        self.registros = [
            {**self.registros[0], "vigor": vigor, "produto": produto}
            for produto in ("ndvi", "savi") for vigor in ("baixo", "moderado", "alto")
        ]
        self.gravar_csv("estatisticas_por_vigor.csv")
        (self.pasta / "manifesto.json").write_text(json.dumps({
            "metodologia_versao": 2,
            "roi": None if imagem_inteira else {
                "type": "Feature", "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [-43.5, -21.8], [-43.4, -21.8], [-43.4, -21.7],
                    [-43.5, -21.7], [-43.5, -21.8],
                ]]},
            },
            "configuracao": {
                "area_analise": "imagem inteira" if imagem_inteira else "ROI",
                "metodo": "NDVI por data", "limites_ndvi": [0.3, 0.6], "L": 0.5,
                "mde": None, "temperatura_ar_c": None,
            }, "grades": [{
                "data": "2025-06-16", "satelite": "LANDSAT_8", "crs": "EPSG:32723",
                "transform": [30, 0, 500000, 0, -30, 7600000], "shape": [10, 10],
                "janela": {"col_off": 0, "row_off": 0, "width": 10, "height": 10},
                "bounds": [500000, 7599700, 500300, 7600000],
            }],
        }), encoding="utf-8")
        figuras = self.pasta / "2025-06-16"
        figuras.mkdir()
        Image.new("RGB", (100, 60), "yellow").save(figuras / "pastagem_mascara.png")
        Image.new("RGB", (100, 60), "purple").save(figuras / "vigor_mapa.png")
        for vigor in ("baixo", "moderado", "alto"):
            pasta_classe = figuras / vigor
            pasta_classe.mkdir()
            for produto in ("ndvi", "savi"):
                Image.new("RGB", (100, 60), "red").save(pasta_classe / f"{produto}_mapa.png")
                Image.new("RGB", (100, 60), "pink").save(pasta_classe / f"{produto}_histograma.png")
        return figuras

    def gravar_manifesto_geral_compativel(self, pasta_geral):
        pastagens = json.loads((self.pasta / "manifesto.json").read_text(encoding="utf-8"))
        manifesto = {
            **pastagens["configuracao"], "roi": pastagens["roi"],
            "metodologia_versao": pastagens["metodologia_versao"],
            "cenas": pastagens["grades"],
        }
        caminho = pasta_geral / "manifesto_roi.json"
        caminho.write_text(json.dumps(manifesto), encoding="utf-8")
        return caminho, manifesto

    def gravar_produtos_completos(self, pasta, nome_csv="estatisticas_produtos.csv"):
        pasta.mkdir(parents=True, exist_ok=True)
        produtos = []
        for produto, cor_mapa, cor_histograma, media in (
            ("ndvi", "blue", "cyan", 0.45), ("savi", "orange", "teal", 0.72),
        ):
            for tipo, cor in (("mapa", cor_mapa), ("histograma", cor_histograma)):
                Image.new("RGB", (100, 60), cor).save(pasta / f"{produto}_{tipo}.png")
            registro = {
                **self.registros[0], "produto": produto, "pixels_validos": 95,
                "pixels_ausentes": 5, "cobertura_percentual": 95,
                "media": media, "mediana": media,
                "base_area": "grade completa" if self.pasta.name.endswith("imagem_completa")
                else "ROI; centros dos pixels",
            }
            registro.pop("vigor", None)
            produtos.append(registro)
        with (pasta / nome_csv).open("w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=list(produtos[0]), delimiter=";")
            escritor.writeheader()
            escritor.writerows(produtos)

    def cores_figuras(self, leitor):
        return [
            figura.image.convert("RGB").getpixel((0, 0))
            for pagina in leitor.pages for figura in pagina.images
        ]

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
        self.assertIn("Reprocesse as cenas", texto)
        self.assertNotIn("Metodologia da execução: versão 2", texto)

    def test_pdf_identifica_formulas_da_versao_e_distancia_solar(self):
        for registro in self.registros:
            registro["produto"] = "albedo_toa"
        self.gravar_csv()
        configuracao = {
            "metodologia_versao": 2, "L": 0.5, "L_iaf": 0.1,
            "cenas": [{"data": "2025-06-16", "solar": {
                "distancia_ua": 1.0, "fator_inverso_quadrado": 1.0,
                "fonte": "MTL EARTH_SUN_DISTANCE",
            }}],
        }
        manifesto = self.pasta / "manifesto_roi.json"
        manifesto.write_text(json.dumps(configuracao), encoding="utf-8")
        destino = self.pasta / "metodologia.pdf"
        gerar_pdf_da_pasta(self.pasta, destino)
        _, texto = self.ler(destino)
        self.assertIn("Metodologia da execução: versão 2", texto)
        self.assertIn("0,300 B2", texto)
        self.assertIn("MTL EARTH_SUN_DISTANCE", texto)
        self.assertIn("1,000000", texto)
        self.assertIn("Não se aplica esse fator novamente", texto)

        configuracao.pop("metodologia_versao")
        manifesto.write_text(json.dumps(configuracao), encoding="utf-8")
        gerar_pdf_da_pasta(self.pasta, destino)
        _, antigo = self.ler(destino)
        self.assertIn("referência histórica", antigo)
        self.assertIn("0,130*rho_B1", antigo)
        self.assertNotIn("0,300 B2", antigo)
        self.assertNotIn("Metodologia da execução: versão 2", antigo)

    def test_pdf_pastagens_distingue_referencia_anual_da_data(self):
        for registro in self.registros:
            registro["vigor"] = "baixo"
        self.gravar_csv("estatisticas_por_vigor.csv")
        (self.pasta / "manifesto.json").write_text(json.dumps({
            "metodologia_versao": 2,
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

    def test_pdf_pastagens_separa_produtos_mascara_e_vigor_sem_repetir_classes(self):
        figuras = self.preparar_pastagens()
        self.gravar_produtos_completos(figuras)
        destino = self.pasta / "pastagens.pdf"
        with patch("rasterio.open") as raster:
            gerar_pdf_da_pasta(self.pasta, destino)
            raster.assert_not_called()
        leitor, texto = self.ler(destino)
        cores = self.cores_figuras(leitor)
        self.assertEqual(len(cores), 6)
        for cor in ((0, 0, 255), (0, 255, 255), (255, 165, 0), (0, 128, 128),
                    (255, 255, 0), (128, 0, 128)):
            self.assertEqual(cores.count(cor), 1)
        self.assertNotIn((255, 0, 0), cores)
        self.assertNotIn((255, 192, 203), cores)
        for trecho in ("Máscara binária de pastagem", "Classes de vigor",
                       "Estatísticas da área completa", "média: 0,4500", "média: 0,7200",
                       "vigor baixo", "vigor moderado", "vigor alto"):
            self.assertIn(trecho, texto)
        self.assertNotIn("média: 0,6000", texto)

    def test_pdf_pastagens_antigas_usa_produtos_completos_da_pasta_irma_sem_raster(self):
        for imagem_inteira in (False, True):
            with self.subTest(imagem_inteira=imagem_inteira):
                self.preparar_pastagens(imagem_inteira)
                pasta_geral = self.pasta.parent / ("imagem_completa" if imagem_inteira else "roi")
                self.gravar_produtos_completos(pasta_geral / "2025-06-16", "estatisticas.csv")
                self.gravar_manifesto_geral_compativel(pasta_geral)
                destino = self.pasta / "antigo.pdf"
                with patch("rasterio.open") as raster:
                    gerar_pdf_da_pasta(self.pasta, destino)
                    raster.assert_not_called()
                leitor, texto = self.ler(destino)
                cores = self.cores_figuras(leitor)
                self.assertEqual(cores.count((0, 0, 255)), 1)
                self.assertEqual(cores.count((255, 165, 0)), 1)
                self.assertNotIn((255, 0, 0), cores)
                self.assertIn("média: 0,4500", texto)
                self.assertIn("média: 0,7200", texto)

    def test_pdf_nao_mistura_figuras_da_irma_com_area_grade_ou_calculo_diferentes(self):
        self.preparar_pastagens()
        pasta_geral = self.pasta.parent / "roi"
        self.gravar_produtos_completos(pasta_geral / "2025-06-16", "estatisticas.csv")
        destino = self.pasta / "incompativel.pdf"
        casos = (
            ("roi", None), ("L", 0.25), ("mde", "outro_mde.tif"),
            ("temperatura_ar_c", 30), ("metodologia_versao", 1),
            ("crs", "EPSG:32623"), ("transform", [30, 0, 500030, 0, -30, 7600000]),
            ("shape", [11, 10]),
            ("janela", {"col_off": 1, "row_off": 0, "width": 10, "height": 10}),
            ("bounds", [500030, 7599700, 500330, 7600000]),
        )
        for campo, valor in casos:
            with self.subTest(campo=campo):
                caminho, manifesto = self.gravar_manifesto_geral_compativel(pasta_geral)
                if campo in ("crs", "transform", "shape", "janela", "bounds"):
                    manifesto["cenas"][0][campo] = valor
                else:
                    manifesto[campo] = valor
                caminho.write_text(json.dumps(manifesto), encoding="utf-8")
                with patch("rasterio.open") as raster:
                    gerar_pdf_da_pasta(self.pasta, destino)
                    raster.assert_not_called()
                leitor, texto = self.ler(destino)
                self.assertEqual(set(self.cores_figuras(leitor)), {(255, 255, 0), (128, 0, 128)})
                self.assertIn("Figura não disponível: Mapa", texto)
                self.assertNotIn("média: 0,4500", texto)

    def test_pdf_nao_usa_figuras_externas_sem_os_dois_manifestos(self):
        self.preparar_pastagens()
        pasta_geral = self.pasta.parent / "roi"
        self.gravar_produtos_completos(pasta_geral / "2025-06-16", "estatisticas.csv")
        manifesto_pastagens = self.pasta / "manifesto.json"
        conteudo = manifesto_pastagens.read_text(encoding="utf-8")
        destino = self.pasta / "sem_manifesto.pdf"
        for ausente in ("geral", "pastagens"):
            with self.subTest(ausente=ausente):
                manifesto_pastagens.write_text(conteudo, encoding="utf-8")
                caminho_geral, _ = self.gravar_manifesto_geral_compativel(pasta_geral)
                (caminho_geral if ausente == "geral" else manifesto_pastagens).unlink()
                with patch("rasterio.open") as raster:
                    gerar_pdf_da_pasta(self.pasta, destino)
                    raster.assert_not_called()
                leitor, texto = self.ler(destino)
                self.assertEqual(set(self.cores_figuras(leitor)), {(255, 255, 0), (128, 0, 128)})
                self.assertIn("Figura não disponível: Mapa", texto)

    def test_pdf_pastagens_sem_produto_completo_informa_ausencia_sem_usar_classes(self):
        self.preparar_pastagens()
        destino = self.pasta / "sem_produtos.pdf"
        with patch("rasterio.open") as raster:
            gerar_pdf_da_pasta(self.pasta, destino)
            raster.assert_not_called()
        leitor, texto = self.ler(destino)
        self.assertEqual(set(self.cores_figuras(leitor)), {(255, 255, 0), (128, 0, 128)})
        self.assertIn("Figura não disponível: Mapa", texto)
        self.assertIn("Figura não disponível: Histograma", texto)
        self.assertIn("Estatísticas da área completa não disponíveis", texto)

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
