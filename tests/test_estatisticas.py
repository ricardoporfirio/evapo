"""Escalas sugeridas não podem remover observações válidas das distribuições."""

import unittest
from unittest.mock import patch

import numpy as np
from matplotlib.figure import Figure

from evapo.calculos.estatisticas import estatisticas_descritivas, intervalo_dados
from evapo.relatorios.plots import mostrar_histograma, mostrar_mapa


class EscalasEstatisticasTest(unittest.TestCase):
    def test_extremos_fora_da_escala_continuam_nas_estatisticas_e_histograma(self):
        dados = np.array([[-25, 20, 61], [999, np.nan, np.inf]], dtype="float32")
        roi = np.array([[True, True, True], [False, True, True]])
        resultado = estatisticas_descritivas(dados, (-20, 60), mascara_roi=roi)
        self.assertEqual(resultado["pixels_validos"], 3)
        self.assertEqual(resultado["frequencias"].sum(), 3)
        np.testing.assert_allclose(resultado["bordas"][[0, -1]], [-25, 61])
        self.assertAlmostEqual(resultado["media"], np.mean([-25, 20, 61]))
        self.assertAlmostEqual(resultado["variancia"], np.var([-25, 20, 61]))
        self.assertEqual(resultado["mediana"], 20)

    def test_escala_sugerida_e_mantida_quando_cobre_os_dados(self):
        resultado = estatisticas_descritivas(np.array([[0, 1]]), (-1, 1))
        np.testing.assert_array_equal(resultado["bordas"], np.linspace(-1, 1, 81))
        dados = np.ma.array([[999, np.nan, -25, 61]], mask=[[True, False, False, False]])
        self.assertEqual(intervalo_dados(dados, (-20, 60)), (-25, 61))

    def test_figuras_exibem_os_extremos_e_as_bordas_completas(self):
        dados = np.array([[-25.0, 61.0]])
        resultado = estatisticas_descritivas(dados, (-20, 60))
        figura = Figure()
        eixo = figura.add_subplot()
        with patch("evapo.relatorios.plots.plt.subplots", return_value=(figura, eixo)):
            mostrar_histograma(resultado, "Temperatura", (-20, 60))
        self.assertEqual(eixo.get_xlim(), (-25, 61))
        figura = Figure()
        eixo = figura.add_subplot()
        with patch("evapo.relatorios.plots.plt.subplots", return_value=(figura, eixo)):
            mostrar_mapa(dados, "Temperatura", (-20, 60))
        self.assertEqual(eixo.images[0].get_clim(), (-25, 61))


if __name__ == "__main__":
    unittest.main()
