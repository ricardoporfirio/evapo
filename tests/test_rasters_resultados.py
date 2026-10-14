"""Consulta resultados persistidos na grade nativa, incluindo NoData e vigor."""

import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import customtkinter as ctk
import numpy as np
import rasterio
from affine import Affine
from PIL import Image

from evapo.dados.rasters_resultados import salvar_produtos, consultar_pixel, ler_previa, salvar_histograma, histograma_produto
from evapo.interface.resultados import PainelResultados


class ResultadosPersistidosTest(unittest.TestCase):
    def setUp(self):
        temporaria = tempfile.TemporaryDirectory()
        self.addCleanup(temporaria.cleanup)
        self.saida = Path(temporaria.name)
        self.pasta = self.saida / "pastagens" / "2025-06-16"
        self.grade = {"crs": "EPSG:32723", "transform": [30, 0, 500000, 0, -30, 7600000]}
        self.dados = np.array([[np.nan, 0.123456789123], [0.6, 0.8]])
        salvar_produtos({"ndvi": self.dados, "savi": self.dados / 2}, self.grade, self.pasta)
        with rasterio.open(self.pasta / "classes_vigor.tif", "w", driver="GTiff",
                           count=1, height=2, width=2, dtype="uint8", crs=self.grade["crs"],
                           transform=Affine(*self.grade["transform"]), nodata=255) as destino:
            destino.write(np.array([[255, 1], [0, 3]], dtype="uint8"), 1)
        with rasterio.open(self.pasta / "pastagem_mascara.tif", "w", driver="GTiff",
                           count=1, height=2, width=2, dtype="uint8", crs=self.grade["crs"],
                           transform=Affine(*self.grade["transform"]), nodata=255) as destino:
            destino.write(np.array([[255, 1], [0, 1]], dtype="uint8"), 1)

    def test_histograma_amplia_escala_preservando_mascara_e_todos_os_validos(self):
        dados = np.array([[np.nan, 61.0], [-25.0, 70.0]])
        salvar_produtos({"temperatura_superficie": dados}, self.grade, self.pasta)
        completo = histograma_produto(self.pasta, "temperatura_superficie", (-20, 60))
        self.assertEqual(sum(completo["frequencias"]), completo["pixels_validos"])
        self.assertEqual(completo["pixels_validos"], 3)
        self.assertEqual((completo["bordas"][0], completo["bordas"][-1]), (-25, 70))
        filtrado = histograma_produto(
            self.pasta, "temperatura_superficie", (-20, 60),
            caminho_mascara=self.pasta / "classes_vigor.tif",
        )
        self.assertEqual(sum(filtrado["frequencias"]), 2)
        self.assertEqual(filtrado["media"], 65.5)
        self.assertEqual((filtrado["bordas"][0], filtrado["bordas"][-1]), (-20, 70))

    def test_png_salvo_sem_mascara_usa_produto_completo_mesmo_com_registro_por_vigor(self):
        classe = self.pasta / "baixo"
        classe.mkdir()
        for pasta, cores in ((self.pasta, ("blue", "cyan")), (classe, ("red", "pink"))):
            for sufixo, cor in zip(("mapa", "histograma"), cores):
                Image.new("RGB", (10, 10), cor).save(pasta / f"ndvi_{sufixo}.png")
        painel = SimpleNamespace(
            registro_figura={"data": "2025-06-16", "produto": "ndvi", "vigor": "baixo"},
            aplicar_mascara=SimpleNamespace(get=lambda: False),
            vigor=SimpleNamespace(get=lambda: "Todos"), figura_exibida=None,
            imagens_carregadas={}, pastas={"Pastagens": self.pasta.parent},
            analise=SimpleNamespace(get=lambda: "Pastagens"),
            imagem_mapa=Mock(), imagem_histograma=Mock(), imagem_vazia=None,
            mostrar_mapa_interativo=Mock(), mostrar_histograma_interativo=Mock(),
            canvas_mapa=None, botao_ampliar=Mock(), ajustar_figuras=Mock(),
        )
        PainelResultados.carregar_figuras(painel)
        self.assertEqual(painel.imagens_carregadas["mapa"].getpixel((0, 0)), (0, 0, 255))
        self.assertEqual(painel.imagens_carregadas["histograma"].getpixel((0, 0)), (0, 255, 255))
        painel.mostrar_histograma_interativo.assert_called_once_with(self.pasta, painel.registro_figura)

    def test_mascara_independente_e_aplicacao_no_produto(self):
        mascara = self.pasta / "classes_vigor.tif"
        dados, _, _ = ler_previa(self.pasta, "mascara_pastagem")
        self.assertTrue(dados.mask[0, 0])
        self.assertEqual(dados[1, 0], 0)
        self.assertEqual(dados[1, 1], 3)
        categorias = histograma_produto(self.pasta, "mascara_pastagem", (0, 1))
        self.assertEqual(categorias["frequencias"], [1, 1, 0, 1, 0])
        inteira = histograma_produto(self.pasta, "ndvi", (-1, 1))
        pastagens = histograma_produto(self.pasta, "ndvi", (-1, 1), caminho_mascara=mascara)
        self.assertEqual(inteira["pixels_validos"], 3)
        self.assertEqual(pastagens["pixels_validos"], 2)
        self.assertAlmostEqual(pastagens["media"], (0.123456789123 + 0.8) / 2)
        self.assertIsNone(consultar_pixel(self.pasta, "ndvi", 500015, 7599955, caminho_mascara=mascara))
        self.assertEqual(consultar_pixel(self.pasta, "ndvi", 500015, 7599955)["valores"]["ndvi"], 0.6)
        geral = self.saida / "roi" / "2025-06-16"
        salvar_produtos({"ndvi": self.dados}, self.grade, geral)
        filtrada, _, _ = ler_previa(geral, "ndvi", caminho_mascara=mascara)
        np.testing.assert_array_equal(np.ma.getmaskarray(filtrada), [[True, False], [True, False]])
        # Mesmo tamanho não garante o alinhamento: a transformação também deve coincidir.
        deslocada = {**self.grade, "transform": [30, 0, 500030, 0, -30, 7600000]}
        salvar_produtos({"ndvi": self.dados}, deslocada, geral)
        with self.assertRaisesRegex(ValueError, "mesma grade"):
            ler_previa(geral, "ndvi", caminho_mascara=mascara)

    def test_valor_exato_persistido_mascara_e_limites(self):
        self.dados[0, 1] = 99  # Alterar a entrada não altera a execução salva.
        pixel = consultar_pixel(self.pasta, "ndvi", 500045, 7599985, "baixo")
        self.assertEqual(pixel["valores"]["ndvi"], 0.123456789123)
        self.assertEqual(pixel["valores"]["savi"], 0.123456789123 / 2)
        self.assertEqual((pixel["linha"], pixel["coluna"]), (0, 1))
        self.assertEqual(pixel["centro"], (500045, 7599985))
        self.assertIsNone(consultar_pixel(self.pasta, "ndvi", 500015, 7599955, "baixo"))
        self.assertIsNone(consultar_pixel(self.pasta, "ndvi", 500060, 7599955))
        self.assertIsNone(consultar_pixel(self.pasta, "ndvi", 499999, 7599985))
        self.assertIsNone(consultar_pixel(self.pasta, "ndvi", 500015, 7599985)["valores"]["ndvi"])
        previa, _, _ = ler_previa(self.pasta, "ndvi", "baixo")
        np.testing.assert_array_equal(np.ma.getmaskarray(previa), [[True, False], [True, True]])

    def test_tres_niveis_de_vigor_sem_reclassificar_ausencias(self):
        pasta = self.saida / "tres_niveis"
        dados = np.array([[np.nan, 0.1, 0.2], [0.4, 0.3, 0.9]])
        salvar_produtos({"ndvi": dados}, self.grade, pasta)
        mascara = pasta / "classes_vigor.tif"
        with rasterio.open(mascara, "w", driver="GTiff", count=1, height=2, width=3,
                           dtype="uint8", crs=self.grade["crs"],
                           transform=Affine(*self.grade["transform"]), nodata=255) as destino:
            destino.write(np.array([[255, 1, 2], [0, 3, 4]], dtype="uint8"), 1)
        previa, _, _ = ler_previa(pasta, "mascara_pastagem")
        self.assertTrue(previa.mask[0, 0])
        np.testing.assert_array_equal(previa.compressed(), [1, 2, 0, 3, 4])
        histograma = histograma_produto(pasta, "mascara_pastagem", (0, 4))
        self.assertEqual(histograma["frequencias"], [1, 1, 1, 1, 1])
        integrado = histograma_produto(pasta, "ndvi", (-1, 1), caminho_mascara=mascara)
        self.assertEqual(integrado["pixels_validos"], 3)
        self.assertAlmostEqual(integrado["media"], 0.2)
        for vigor, esperado in (("baixo", 0.1), ("moderado", 0.2), ("alto", 0.3)):
            classe = histograma_produto(pasta, "ndvi", (-1, 1), vigor=vigor, caminho_mascara=mascara)
            self.assertEqual(classe["pixels_validos"], 1)
            self.assertAlmostEqual(classe["media"], esperado)
        pixel = consultar_pixel(pasta, "mascara_pastagem", 500075, 7599985)
        self.assertEqual(pixel["valores"]["mascara_pastagem"], 2)
        self.assertIsNone(consultar_pixel(pasta, "ndvi", 500075, 7599955, caminho_mascara=mascara))

    def test_troca_de_produto_clique_e_tabela_modal(self):
        janela = ctk.CTk()
        janela.withdraw()
        painel = PainelResultados(janela)
        try:
            pasta = self.saida / "pastagens"
            registros = [{"data": "2025-06-16", "produto": p, "vigor": "baixo", "media": "0.12"}
                         for p in ("ndvi", "savi")]
            with (pasta / "estatisticas_por_vigor.csv").open("w", encoding="utf-8", newline="") as arquivo:
                escritor = csv.DictWriter(arquivo, fieldnames=registros[0], delimiter=";")
                escritor.writeheader()
                escritor.writerows(registros)
            figuras = self.pasta / "baixo"
            figuras.mkdir()
            for produto in ("ndvi", "savi"):
                salvar_histograma({"bordas": np.array([-1, 0, 1]), "frequencias": np.array([0, 1])},
                                  figuras / f"{produto}_histograma.json")
            painel.atualizar(self.saida)
            self.assertFalse(painel.aplicar_mascara.get())
            painel.definir_visibilidade(True)
            self.assertIsNotNone(painel.canvas_mapa)
            self.assertIsNotNone(painel.canvas_histograma)
            self.assertEqual(painel.produto.get(), "NDVI")
            painel.clicar_pixel(SimpleNamespace(inaxes=painel.eixo_mapa, xdata=500015, ydata=7599955))
            self.assertEqual(painel.ultimo_pixel["valores"]["ndvi"], 0.6)
            painel.clicar_pixel(SimpleNamespace(inaxes=painel.eixo_mapa, xdata=500045, ydata=7599985))
            self.assertEqual(painel.ultimo_pixel["valores"]["ndvi"], 0.123456789123)
            self.assertIn("0,123457", painel.consulta_pixel.get())
            painel.produto.set("SAVI")
            painel.filtrar()
            self.assertEqual(painel.figura_exibida["produto"], "savi")
            self.assertIsNone(painel.ultimo_pixel)
            painel.clicar_pixel(SimpleNamespace(inaxes=painel.eixo_mapa, xdata=500045, ydata=7599985))
            self.assertIn("0,061728", painel.consulta_pixel.get())
            self.assertEqual(painel.check_mascara.cget("state"), "normal")
            painel.aplicar_mascara.set(False)
            painel.alternar_mascara()
            painel.clicar_pixel(SimpleNamespace(inaxes=painel.eixo_mapa, xdata=500015, ydata=7599955))
            self.assertEqual(painel.ultimo_pixel["valores"]["savi"], 0.3)
            painel.aplicar_mascara.set(True)
            painel.vigor.set("Todos")
            painel.alternar_mascara()
            painel.clicar_pixel(SimpleNamespace(inaxes=painel.eixo_mapa, xdata=500015, ydata=7599955))
            self.assertIsNone(painel.ultimo_pixel)
            painel.produto.set("Máscara de pastagem")
            painel.filtrar()
            self.assertEqual(painel.figura_exibida["produto"], "mascara_pastagem")
            self.assertIsNotNone(painel.canvas_histograma)
            self.assertEqual(painel.check_mascara.cget("state"), "disabled")
            painel.clicar_pixel(SimpleNamespace(inaxes=painel.eixo_mapa, xdata=500015, ydata=7599955))
            self.assertEqual(painel.ultimo_pixel["valores"]["mascara_pastagem"], 0)
            painel.clicar_pixel(SimpleNamespace(inaxes=painel.eixo_mapa, xdata=500045, ydata=7599955))
            self.assertEqual(painel.ultimo_pixel["valores"]["mascara_pastagem"], 3)
            self.assertIn("Alto vigor", painel.consulta_pixel.get())
            self.assertEqual(painel.escolha_vigor.cget("state"), "disabled")
            self.assertEqual(painel.janela_tabela.state(), "withdrawn")
            painel.abrir_tabela()
            self.assertEqual(painel.janela_tabela.grab_current(), painel.janela_tabela)
            painel.definir_visibilidade(False)
            self.assertEqual(painel.janela_tabela.state(), "withdrawn")
            self.assertIsNone(painel.janela_tabela.grab_current())
        finally:
            painel.destroy()
            for timer in janela.tk.call("after", "info"):
                janela.tk.call("after", "cancel", timer)
            janela.destroy()
