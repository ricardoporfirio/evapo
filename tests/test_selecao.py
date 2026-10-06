"""Confere a seleção persistida e a compatibilidade com ROIs antigas."""

import tempfile
import unittest
from pathlib import Path

from evapo.roi import carregar_roi, salvar_roi
from evapo.selecao import filtrar_cenas_selecionadas, identificar_cena


class TestSelecao(unittest.TestCase):
    def setUp(self):
        self.cenas = [
            {"caminho": Path("entrada/data_a/imagem.tif")},
            {"caminho": Path("entrada/data_b/imagem.tif")},
            {"caminho": Path("entrada/data_c/imagem.tif")},
        ]

    def test_roi_antiga_usa_todas(self):
        self.assertEqual(filtrar_cenas_selecionadas(self.cenas, {}), self.cenas)

    def test_selecao_salva_e_preserva_ordem_das_cenas(self):
        escolhidas = [identificar_cena(self.cenas[2]), identificar_cena(self.cenas[0])]
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "roi.geojson"
            salvar_roi(
                [(0, 0), (1, 0), (1, 1), (0, 1)],
                "EPSG:4326",
                destino,
                imagens_selecionadas=escolhidas,
            )
            roi = carregar_roi(destino)
        self.assertEqual(roi["properties"]["imagens_selecionadas"], escolhidas)
        self.assertEqual(
            filtrar_cenas_selecionadas(self.cenas, roi),
            [self.cenas[0], self.cenas[2]],
        )

    def test_selecao_vazia_rejeitada(self):
        with self.assertRaisesRegex(ValueError, "pelo menos uma"):
            filtrar_cenas_selecionadas(
                self.cenas, {"properties": {"imagens_selecionadas": []}}
            )

    def test_imagem_ausente_pede_atualizacao(self):
        roi = {"properties": {"imagens_selecionadas": ["outra/imagem.tif"]}}
        with self.assertRaisesRegex(ValueError, "editar-roi"):
            filtrar_cenas_selecionadas(self.cenas, roi)
