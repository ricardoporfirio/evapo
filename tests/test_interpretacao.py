"""Garante interpretações descritivas e preservação de dados ausentes."""

import unittest

from evapo.interpretacao import (
    REFERENCIAS,
    TEORIA_PRODUTOS,
    interpretar_pastagens,
    interpretar_registro,
    interpretar_temporal,
    teorias_produtos,
)


def registro(produto="ndvi", data="2025-06-16", **valores):
    return dict(
        produto=produto,
        data=data,
        pixels_totais=100,
        pixels_validos=80,
        cobertura_percentual=80,
        media=0.4,
        mediana=0.35,
        q1=0.2,
        q3=0.6,
        minimo=0.0,
        maximo=0.9,
    ) | valores


class InterpretacaoTest(unittest.TestCase):
    def test_teoria_identifica_entrada_toa_calibracao_e_bibliografia(self):
        self.assertEqual(set(TEORIA_PRODUTOS), {"ndvi", "savi", "iaf", "albedo_toa", "albedo_superficie"})
        ids = {referencia["id"] for referencia in REFERENCIAS}
        self.assertEqual(len(ids), len(REFERENCIAS))
        for referencia in REFERENCIAS:
            self.assertTrue(referencia["titulo"])
            self.assertTrue(referencia["url"])
        self.assertIn("TOA", TEORIA_PRODUTOS["ndvi"]["limites"])
        self.assertIn("Level-2", TEORIA_PRODUTOS["ndvi"]["limites"])
        self.assertIn("L=0,1", TEORIA_PRODUTOS["iaf"]["interpretacao"])
        self.assertIn("L=0,5", TEORIA_PRODUTOS["iaf"]["limites"])
        copia = teorias_produtos()
        copia["ndvi"]["formula"] = "alterada"
        self.assertNotEqual(copia["ndvi"]["formula"], TEORIA_PRODUTOS["ndvi"]["formula"])

    def test_dados_csv_decimal_nan_e_cobertura_calculada(self):
        dados = registro(media="0,4", mediana="nan", q1=None, q3="", pixels_validos="80", pixels_totais="100", cobertura_percentual="NaN")
        texto = " ".join(interpretar_registro(dados))
        self.assertIn("80,00%", texto)
        self.assertIn("Média de 0,4000", texto)
        self.assertNotIn("A mediana", texto)
        self.assertNotIn("nan", texto.lower())
        self.assertIn("não mede isoladamente a nebulosidade", texto)

    def test_ausencia_nao_vira_zero_nem_baixo_vigor(self):
        for valor in (None, "", "nan", float("nan"), "inf"):
            with self.subTest(valor=valor):
                texto = " ".join(interpretar_registro(registro(media=valor)))
                self.assertIn("Média ausente", texto)
                self.assertNotIn("Média de 0,0000", texto)
        sem_pixels = " ".join(interpretar_registro(registro(pixels_validos="0", media="0.4")))
        self.assertIn("nenhum pixel válido", sem_pixels)
        self.assertNotIn("Média de", sem_pixels)
        classe_vazia = " ".join(interpretar_registro(registro(pixels_totais=0, pixels_validos=0)))
        self.assertIn("classe está vazia", classe_vazia)
        self.assertIn("ausência não corresponde a valor zero", classe_vazia)

    def test_zero_real_indice_nao_significa_ausencia_vegetacao(self):
        texto = " ".join(interpretar_registro(registro(media=0)))
        self.assertIn("Média de 0,0000", texto)
        self.assertIn("não comprova ausência de vegetação", texto)
        negativo = " ".join(interpretar_registro(registro(media=-0.15)))
        self.assertIn("podem contribuir", negativo)
        self.assertIn("não identifica o uso do solo", negativo)

    def test_iaf_explicita_limites_sem_inventar_percentual_saturado(self):
        texto = " ".join(interpretar_registro(registro("iaf", media=2, minimo=0, maximo=6)))
        self.assertIn("teto de 6", texto)
        self.assertIn("piso zero", texto)
        self.assertIn("não informa quantos pixels", texto)
        self.assertIn("não linear", texto)

    def test_albedo_separa_toa_superficie_e_absorcao_condicional(self):
        toa = " ".join(interpretar_registro(registro("albedo_toa")))
        self.assertIn("não permite atribuir", toa)
        superficie = " ".join(interpretar_registro(registro("albedo_superficie", media=0.2, minimo=0.00001, maximo=1)))
        self.assertIn("20,00%", superficie)
        self.assertIn("radiação incidente comparável", superficie)
        self.assertIn("limites numéricos", superficie)

    def test_comparacao_ordena_datas_exclui_ausencias_e_separa_classes(self):
        dados = [
            registro(data="2026-08-30", media="0.6", vigor="baixo"),
            registro(data="2025-07-18", media="nan", pixels_validos="0", vigor="baixo"),
            registro(data="2025-06-16", media="0.3", vigor="baixo"),
            registro(data="2025-06-16", media=0.8, vigor="alto"),
        ]
        texto = " ".join(interpretar_temporal(dados))
        self.assertIn("NDVI — vigor baixo: média 0,3000 em 16/06/2025 e 0,6000 em 30/08/2026", texto)
        self.assertIn("+0,3000", texto)
        self.assertIn("1 registro(s) sem média válida", texto)
        self.assertIn("NDVI — vigor alto: uma única data", texto)
        self.assertIn("não foram substituídos por zero", texto)
        self.assertIn("não fornecem evapotranspiração", texto)

    def test_comparacao_imagem_inteira_nao_pressupoe_mesma_area(self):
        dados = [registro(), registro(data="2026-08-30", media=0.5)]
        texto = " ".join(interpretar_temporal(dados, imagem_inteira=True))
        self.assertIn("não garante a mesma extensão geográfica", texto)
        roi = " ".join(interpretar_temporal(dados))
        self.assertIn("coberturas percentuais iguais", roi)
        self.assertIn("Não estabelecem tendência contínua", roi)

    def test_mediana_e_media_opostas_explicitam_distribuicao(self):
        dados = [registro(media=0.4, mediana=0.5), registro(data="2026-08-30", media=0.5, mediana=0.4)]
        texto = " ".join(interpretar_temporal(dados))
        self.assertIn("média e mediana mudaram em sentidos opostos", texto)
        self.assertIn("impede tratar", texto)

    def test_sem_datas_comparaveis_e_registros_duplicados(self):
        self.assertIn("Não há registros", interpretar_temporal([])[0])
        sem_media = " ".join(interpretar_temporal([registro(media="nan"), registro(data="2026-08-30", media="nan")]))
        self.assertIn("nenhuma data com média válida", sem_media)
        duplicados = " ".join(interpretar_temporal([registro(), registro(), registro(data="2026-08-30")]))
        self.assertIn("mais de um registro na mesma data", duplicados)
        self.assertNotIn("diferença final - inicial", duplicados)

    def test_mapbiomas_anual_referencia_nao_diagnostico_instantaneo(self):
        config = {"metodo": "classes anuais de vigor", "ano_camada": "2025", "fontes_raster": {"vigor": {"fonte": "MapBiomas Brasil"}}}
        texto = " ".join(interpretar_pastagens(config))
        self.assertIn("MODIS", texto)
        self.assertIn("EVI", texto)
        self.assertIn("Ano da camada de referência: 2025", texto)
        self.assertIn("não confirma permanência", texto)
        self.assertIn("MAPBIOMAS-VIGOR", texto)
        self.assertIn("ausência de classe", texto)
        local = " ".join(interpretar_pastagens({"metodo": "classes anuais de vigor"}))
        self.assertIn("não se presume que toda camada local seja MapBiomas", local)
        self.assertIn("ano da camada de referência não foi informado", local)

    def test_classes_ndvi_usam_limites_explicitos_e_evitam_validacao_circular(self):
        texto = " ".join(interpretar_pastagens({"metodo": "NDVI por data", "limites_ndvi": ["0.3", "0.6"]}))
        self.assertIn("NDVI < 0,3000", texto)
        self.assertIn("0,3000 <= NDVI < 0,6000", texto)
        self.assertIn("NDVI >= 0,6000", texto)
        self.assertIn("sem validar de forma independente", texto)
        self.assertIn("não representam limiares universais", texto)
        self.assertNotIn("MODIS", texto)
