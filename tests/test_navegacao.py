"""Verifica zoom/pan sem alterar a geometria já desenhada no mapa."""

import unittest
from unittest.mock import Mock
from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backend_bases import MouseButton
from matplotlib.patches import Polygon

from evapo.mapa.navegacao import NavegacaoMapa


class NavegacaoTest(unittest.TestCase):
    def setUp(self):
        self.figura, self.eixo = plt.subplots()
        self.eixo.set_xlim(0, 100)
        self.eixo.set_ylim(0, 100)
        self.figura.canvas.draw()
        self.modos = []
        self.navegacao = NavegacaoMapa(self.eixo, self.modos.append)

    def tearDown(self):
        plt.close(self.figura)

    def test_zoom_e_ver_tudo(self):
        self.navegacao.aplicar_zoom(aproximar=True)
        np.testing.assert_allclose(self.eixo.get_xlim(), [10, 90])
        self.navegacao.ver_tudo()
        np.testing.assert_allclose(self.eixo.get_xlim(), [0, 100])

    def test_roda_aproxima_no_cursor(self):
        evento = SimpleNamespace(inaxes=self.eixo, step=1, xdata=25, ydata=25)
        self.navegacao.usar_roda(evento)
        np.testing.assert_allclose(self.eixo.get_xlim(), [5, 85])

    def test_pan_preserva_roi(self):
        contorno = Polygon([(20, 20), (40, 20), (40, 40)], closed=True)
        self.eixo.add_patch(contorno)
        vertices_antes = contorno.get_xy().copy()
        self.navegacao.escolher_modo("mover")
        inicio = SimpleNamespace(
            inaxes=self.eixo, button=MouseButton.LEFT, x=100, y=100
        )
        self.navegacao.iniciar_movimento(inicio)
        movimento = SimpleNamespace(x=150, y=100)
        self.navegacao.mover_mapa(movimento)
        self.assertLess(self.eixo.get_xlim()[0], 0)
        np.testing.assert_array_equal(contorno.get_xy(), vertices_antes)
        self.navegacao.terminar_movimento(inicio)
        self.assertIsNone(self.navegacao.inicio_do_movimento)

    def test_botao_do_meio_restaura_desenho(self):
        evento = SimpleNamespace(
            inaxes=self.eixo, button=MouseButton.MIDDLE, x=100, y=100
        )
        self.navegacao.iniciar_movimento(evento)
        self.assertEqual(self.modos[-1], "mover")
        self.navegacao.terminar_movimento(evento)
        self.assertEqual(self.modos[-1], "desenhar")

    def test_atualiza_detalhe_apenas_ao_soltar_botao_do_arrasto(self):
        fim = Mock()
        self.navegacao.ao_terminar = fim
        self.navegacao.escolher_modo("mover")
        inicio = SimpleNamespace(inaxes=self.eixo, button=MouseButton.LEFT, x=100, y=100)
        self.navegacao.iniciar_movimento(inicio)
        self.navegacao.mover_mapa(SimpleNamespace(x=150, y=120))
        self.navegacao.terminar_movimento(SimpleNamespace(button=MouseButton.RIGHT))
        fim.assert_not_called()
        self.navegacao.terminar_movimento(inicio)
        fim.assert_called_once_with()
        self.assertIsNone(self.navegacao.inicio_do_movimento)


if __name__ == "__main__":
    unittest.main()
