"""Cache deve respeitar a área, a resolução e o contexto da imagem."""

import unittest

import numpy as np

from evapo.cache_vistas import CacheVistas


class CacheVistasTest(unittest.TestCase):
    def test_reutiliza_vista_sem_perder_detalhe(self):
        cache = CacheVistas()
        resultado = ({"NDVI": np.zeros((10, 10))}, (0, 0, 100, 100), None, None)
        cache.guardar("cena_roi", resultado)
        self.assertIs(cache.buscar("cena_roi", (20, 20, 80, 80), 10), resultado)
        self.assertIsNone(cache.buscar("cena_roi", (20, 20, 80, 80), 5))
        self.assertIsNone(cache.buscar("outra_roi", (20, 20, 80, 80), 10))
        self.assertIsNone(cache.buscar("cena_roi", (-1, 20, 80, 80), 10))

    def test_memoria_limitada(self):
        cache = CacheVistas(capacidade=2)
        resultado = ({"NDVI": np.zeros((2, 2))}, (0, 0, 2, 2), None, None)
        for chave in ("a", "b", "c"):
            cache.guardar(chave, resultado)
        self.assertIsNone(cache.buscar("a", (0, 0, 2, 2), 1))
        self.assertEqual(len(cache.vistas), 2)
