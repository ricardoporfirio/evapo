"""Regressões de navegação e desenho, sem depender de uma janela Tk."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from evapo.mapa.cache_vistas import CacheVistas
from evapo.interface.sistema import SistemaEvapo


class MapaDesempenhoTest(unittest.TestCase):
    def criar_app(self):
        app = object.__new__(SistemaEvapo)
        app.figura = Figure(figsize=(5, 4))
        app.canvas = FigureCanvasAgg(app.figura)
        app.eixo = app.figura.add_axes([0.1, 0.1, 0.7, 0.8])
        app.eixo_cores = app.figura.add_axes([0.85, 0.2, 0.03, 0.6])
        app.geracao = 1
        app.produto = Mock()
        app.produto.get.return_value = "NDVI"
        app.camada = app.barra = app.vista_exibida = app.produto_exibido = None
        app.cenas = [{"data": "2025-06-16"}]
        app.indice = 0
        app.roi = None
        app.status = Mock()
        app.area = Mock()
        app.carregando = False
        app.navegacao = SimpleNamespace(inicio_do_movimento=None)
        app.cache_vistas = CacheVistas()
        return app

    def resultado(self):
        return ({"NDVI": np.arange(16, dtype="float32").reshape(4, 4) / 16,
                 "RGB": np.full((4, 4, 3), 0.5, dtype="float32")},
                (0, 0, 4, 4), None, None)

    def test_cache_nao_reenvia_imagem_ou_altera_posicao(self):
        app = self.criar_app()
        resultado = self.resultado()
        app.exibir(resultado, 1)
        app.eixo.set_xlim(1, 3)
        app.eixo.set_ylim(1, 3)
        with patch.object(app.camada, "set_data") as dados, patch.object(app.canvas, "draw_idle") as desenho:
            app.exibir(resultado, 1)
            dados.assert_not_called()
            desenho.assert_not_called()
        self.assertEqual(app.eixo.get_xlim(), (1, 3))
        self.assertEqual(app.eixo.get_ylim(), (1, 3))

    def test_rgb_e_indices_alternam_sem_modificar_dados(self):
        app = self.criar_app()
        resultado = self.resultado()
        app.produto.get.return_value = "RGB"
        app.exibir(resultado, 1)
        self.assertEqual(app.camada.get_array().dtype, np.uint8)
        self.assertEqual(resultado[0]["RGB"].dtype, np.float32)
        app.produto.get.return_value = "NDVI"
        app.exibir(resultado, 1)
        np.testing.assert_array_equal(app.camada.get_array(), resultado[0]["NDVI"])
        self.assertEqual(app.camada.get_interpolation_stage(), "data")
        self.assertTrue(app.eixo_cores.get_visible())
        with patch.object(app.camada, "set_cmap") as cores:
            app.exibir(self.resultado(), 1)
            cores.assert_not_called()

    def test_arrasto_nao_inicia_leituras(self):
        app = self.criar_app()
        app.timer_vista = None
        app.mapa_ativo = True
        app.navegacao.inicio_do_movimento = {"mouse_x": 100}
        app.leitura_em_andamento = False
        app.leitura_pendente = ("pedido",)
        # Os atributos restantes de uma leitura não são necessários durante pan.
        app.atualizar_vista()
        with patch("evapo.interface.sistema.threading.Thread") as thread:
            app.iniciar_leitura()
            thread.assert_not_called()

    def test_leitura_antiga_fica_no_cache_sem_sobrescrever_a_tela(self):
        app = self.criar_app()
        app.leitura_em_andamento = True
        app.leitura_pendente = None
        app.iniciar_leitura = Mock()
        resultado = self.resultado()
        app.finalizar_leitura(("cena", 0, resultado, None))
        self.assertIsNone(app.camada)
        self.assertIs(app.cache_vistas.buscar("cena", (0, 0, 4, 4), 1, "NDVI"), resultado)

    def test_leitura_concluida_atende_pedido_pendente_sem_reler(self):
        app = self.criar_app()
        app.leitura_em_andamento = True
        app.leitura_pendente = ("pedido",)
        app.atualizar_vista = Mock()
        app.iniciar_leitura = Mock()
        app.finalizar_leitura(("cena", 0, self.resultado(), None))
        app.atualizar_vista.assert_called_once_with()

    def test_l_savi_valida_sem_tk_e_preserva_padrao_para_chamadores_antigos(self):
        app = self.criar_app()
        self.assertEqual(app.valor_l_savi(), 0.5)
        app.l_savi = Mock()
        app.l_savi.get.return_value = "0,2"
        self.assertEqual(app.valor_l_savi(), 0.2)
        for invalido in ("", "nan", "inf", "-0.1", "1.1"):
            app.l_savi.get.return_value = invalido
            with self.assertRaises(ValueError):
                app.valor_l_savi()

    def test_leitura_agendada_preserva_l_do_pedido(self):
        app = self.criar_app()
        app.leitura_em_andamento = False
        app.leitura_pendente = ("cena", "limites", "roi", "mde", "chave", 1, 25, "SAVI", 0.2)
        app.fila = Mock()
        with patch("evapo.interface.sistema.threading.Thread") as thread, patch(
            "evapo.interface.sistema.ler_vista", return_value=self.resultado()
        ) as ler:
            app.iniciar_leitura()
            thread.call_args.kwargs["target"]()
        ler.assert_called_once_with("cena", "limites", "roi", "mde", tamanho=1200,
                                    temperatura_ar=25, produto="SAVI", L=0.2)


if __name__ == "__main__":
    unittest.main()
