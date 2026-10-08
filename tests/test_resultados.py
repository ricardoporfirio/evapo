"""Confere filtros e a troca de figuras e animações na janela."""

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import customtkinter as ctk
from PIL import Image

from evapo.interface.resultados import PainelResultados


class TestResultados(unittest.TestCase):
    def test_filtros_legiveis_ordenacao_numerica_e_ausencias(self):
        janela = ctk.CTk()
        janela.withdraw()
        painel = PainelResultados(janela)
        try:
            painel.registros = [
                {"data": "2025-06-16", "produto": "temperatura_superficie", "media": "9"},
                {"data": "2025-07-18", "produto": "temperatura_superficie", "media": "10"},
                {"data": "2025-07-18", "produto": "temperatura_superficie", "media": "nan"},
                {"data": "2025-06-16", "produto": "albedo_toa", "media": "0.15"},
            ]
            painel.produto.set("Temperatura da superfície")
            painel.filtrar()
            self.assertEqual(len(painel.filtrados), 3)
            selecionado = painel.registro_figura
            painel.ordenar("media")
            self.assertEqual([r["media"] for r in painel.filtrados], ["9", "10", "nan"])
            painel.ordenar("media")
            self.assertEqual([r["media"] for r in painel.filtrados], ["10", "9", "nan"])
            self.assertIs(painel.registro_figura, selecionado)
            self.assertEqual(painel.tabela.item("2", "values")[6], "—")
            painel.data.set("18/07/2025")
            painel.filtrar()
            self.assertEqual(len(painel.filtrados), 2)
            painel.limpar_filtros()
            self.assertEqual(len(painel.filtrados), 4)
            painel.produto.set("Albedo no topo da atmosfera")
            painel.filtrar()
            self.assertEqual(len(painel.filtrados), 1)
            self.assertEqual(painel.metricas["media"].get(), "0,1500")
        finally:
            for timer in janela.tk.call("after", "info"):
                janela.tk.call("after", "cancel", timer)
            janela.destroy()

    def test_filtrar_trocar_analise_e_limpar_resultados(self):
        janela = ctk.CTk()
        janela.withdraw()
        painel = PainelResultados(janela)
        try:
            with tempfile.TemporaryDirectory() as temporaria:
                saida = Path(temporaria)
                campos = [
                    "data",
                    "produto",
                    "vigor",
                    "pixels_validos",
                    "cobertura_percentual",
                    "media",
                    "mediana",
                    "desvio_padrao",
                    "minimo",
                    "maximo",
                ]
                registro = dict(
                    zip(
                        campos,
                        [
                            "2025-06-16",
                            "ndvi",
                            "baixo",
                            "10",
                            "100",
                            "0.6",
                            "0.7",
                            "0.1",
                            "-0.65647",
                            "0.9",
                        ],
                    )
                )
                for nome, arquivo in (
                    ("roi", "estatisticas_todas_cenas_roi.csv"),
                    ("pastagens", "estatisticas_por_vigor.csv"),
                ):
                    pasta = saida / nome
                    pasta.mkdir()
                    with (pasta / arquivo).open(
                        "w", newline="", encoding="utf-8"
                    ) as destino:
                        escritor = csv.DictWriter(
                            destino, fieldnames=campos, delimiter=";"
                        )
                        escritor.writeheader()
                        escritor.writerow(registro)
                    figuras = pasta / registro["data"] / "baixo"
                    figuras.mkdir(parents=True)
                    for tipo in ("mapa", "histograma"):
                        Image.new("RGB", (20, 20), "green").save(
                            figuras / f"ndvi_{tipo}.png"
                        )
                temporal = saida / "roi" / "timelapse"
                temporal.mkdir()
                Image.new("RGB", (20, 20), "red").save(
                    temporal / "timelapse_ndvi.gif",
                    save_all=True,
                    append_images=[Image.new("RGB", (20, 20), "green")],
                    duration=100,
                )
                with patch("evapo.interface.resultados.Image.open", wraps=Image.open) as abrir:
                    painel.atualizar(saida, saida / "roi")
                    painel.data.set(registro["data"])
                    painel.produto.set("ndvi")
                    painel.filtrar()
                    janela.update_idletasks()
                    self.assertEqual(abrir.call_count, 0)
                self.assertEqual(len(painel.filtrados), 1)
                self.assertIn("Mínimo: -0,65647", painel.detalhes.get("1.0", "end"))
                self.assertEqual(painel.tabela.item("0", "values")[0], "16/06/2025")
                self.assertEqual(painel.tabela.item("0", "values")[2], "NDVI")
                self.assertEqual(painel.metricas["media"].get(), "0,6000")
                self.assertEqual(painel.metricas["cobertura_percentual"].get(), "100,00%")
                self.assertIs(painel.imagem_mapa.cget("image"), painel.imagem_vazia)
                painel.carregar_figuras()
                self.assertIsNot(painel.imagem_mapa.cget("image"), painel.imagem_vazia)
                with patch("evapo.interface.resultados.Image.open", wraps=Image.open) as abrir:
                    painel.ajustar_figuras()
                    painel.ajustar_figuras()
                    painel.ampliar_figura()
                    self.assertIn("NDVI", painel.janela_figura.title())
                    painel.janela_figura.destroy()
                    abrir.assert_not_called()
                painel.abas.set("Time lapse")
                painel.definir_visibilidade(True)
                self.assertIsNone(painel.animacao)
                painel.reproduzir()
                self.assertIsNotNone(painel.timer)
                painel.atualizar(saida, saida / "pastagens")
                self.assertEqual(painel.analise.get(), "Pastagens · ROI")
                self.assertEqual(painel.registros[0]["vigor"], "baixo")
                self.assertFalse(painel.imagens_carregadas)
                self.assertIs(painel.imagem_mapa.cget("image"), painel.imagem_vazia)
                self.assertIsNone(painel.timer)
                self.assertIsNone(painel.animacao)
                # Voltar ao GIF após uma análise sem animação não pode deixar uma imagem Tcl inválida.
                painel.atualizar(saida, saida / "roi")
                self.assertIsNone(painel.animacao)
                painel.reproduzir()
                self.assertEqual(painel.animacao.n_frames, 2)
                painel.definir_visibilidade(False)
                self.assertIsNone(painel.timer)
                self.assertIsNone(painel.animacao)
                painel.produto.set("inexistente")
                painel.filtrar()
                self.assertFalse(painel.tabela.get_children())
                self.assertEqual(painel.botao_figuras.cget("state"), "disabled")
                self.assertEqual(painel.detalhes.get("1.0", "end").strip(), "")
                painel.atualizar(saida / "vazia")
                self.assertFalse(painel.registros)
                self.assertIsNone(painel.animacao)
        finally:
            for timer in janela.tk.call("after", "info"):
                janela.tk.call("after", "cancel", timer)
            janela.destroy()
