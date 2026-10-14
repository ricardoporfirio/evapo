"""Verifica fórmulas com valores conhecidos e exclusão de pixels fora da ROI."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from evapo.calculos.albedo import (
    calcular_albedo_toa,
    calcular_transmissividade,
    corrigir_albedo_superficie,
)
from evapo.calculos.estatisticas import estatisticas_descritivas
from evapo.calculos.indices import calcular_iaf, calcular_iaf_reflectancias, calcular_ndvi, calcular_savi
from evapo.calculos.reflectancia import calcular_reflectancias
from evapo.mapa.roi import carregar_roi, salvar_roi, validar_poligono


class CalculosTest(unittest.TestCase):
    def test_reflectancia_e_qa_por_banda(self):
        coef = {}
        for b in range(1, 8):
            coef[f"REFLECTANCE_MULT_BAND_{b}"] = 0.00002
            coef[f"REFLECTANCE_ADD_BAND_{b}"] = -0.1
        mtl = {
            "IMAGE_ATTRIBUTES": {"SUN_ELEVATION": 30},
            "LEVEL1_RADIOMETRIC_RESCALING": coef,
        }
        dn = np.full((7, 1, 3), 10000, dtype="uint16")
        rho = calcular_reflectancias(
            dn, np.array([[0, 8, 0]]), np.array([[0, 0, 1 << 3]]), mtl
        )
        np.testing.assert_allclose(rho[4][0, 0], 0.2, rtol=1e-6)
        self.assertTrue(np.isnan(rho[4][0, 1:]).all())
        self.assertTrue(np.isfinite(rho[5][0, 2]))

    def test_indices(self):
        np.testing.assert_allclose(calcular_ndvi([0.1], [0.4]), [0.6])
        np.testing.assert_allclose(calcular_savi([0.1], [0.4]), [0.45])
        np.testing.assert_allclose(calcular_iaf([0.1, 0.687]), [0, 6])
        self.assertTrue(np.isnan(calcular_ndvi([0], [0])[0]))

    def test_albedo(self):
        rho = {b: np.array([0.2], dtype="float32") for b in range(1, 8)}
        np.testing.assert_allclose(calcular_albedo_toa(rho), [0.2002], rtol=1e-6)
        np.testing.assert_allclose(calcular_transmissividade([0, 1000]), [0.75, 0.77])
        np.testing.assert_allclose(
            corrigir_albedo_superficie([0.2], [0.75]), [(0.2 - 0.03) / 0.75**2]
        )
        np.testing.assert_allclose(
            corrigir_albedo_superficie([0, 1], [0.75, 0.75]), [0.00001, 1]
        )

    def test_albedo_toa_usa_b2_b7_sem_depender_da_b1(self):
        # Alvos com espectros distintos detectam a troca indevida de pesos.
        rho = {b: np.array([v, v], dtype="float32") for b, v in
               enumerate([0.9, 0.1, 0.2, 0.15, 0.5, 0.3, 0.25], 1)}
        rho[1][1] = np.nan  # B1 é excluída do modelo TOA.
        esperado = 0.300*0.1 + 0.277*0.2 + 0.233*0.15 + 0.143*0.5 + 0.036*0.3 + 0.012*0.25
        np.testing.assert_allclose(calcular_albedo_toa(rho), [esperado, esperado], rtol=1e-6)
        rho[4][0] = np.inf
        rho[7][1] = -0.01
        self.assertTrue(np.isnan(calcular_albedo_toa(rho)).all())

    def test_iaf_usa_savi_da_calibracao_independente_do_l_exibido(self):
        esperado = -np.log((0.69 - 0.55) / 0.59) / 0.91
        np.testing.assert_allclose(calcular_iaf_reflectancias([0.1], [0.4]), [esperado], rtol=1e-6)
        savi_exibido = calcular_savi([0.1], [0.4], L=0.5)
        self.assertAlmostEqual(float(savi_exibido[0]), 0.45, places=6)
        self.assertGreater(float(calcular_iaf_reflectancias([0.1], [0.4])[0]),
                           float(calcular_iaf(savi_exibido)[0]))

    def test_estatisticas_usam_somente_roi(self):
        dados = np.array([[1, 100], [3, np.nan]])
        mask = np.array([[True, False], [True, False]])
        s = estatisticas_descritivas(dados, (0, 100), mascara_roi=mask)
        self.assertEqual(s["pixels_totais"], 2)
        self.assertEqual(s["media"], 2)
        self.assertEqual(s["variancia"], 1)
        self.assertEqual(s["cobertura_percentual"], 100)
        np.testing.assert_allclose([s["q1"], s["mediana"], s["q3"]], [1.5, 2, 2.5])

    def test_roi_sem_observacoes_validas(self):
        s = estatisticas_descritivas(
            np.full((2, 2), np.nan), (0, 1), mascara_roi=np.ones((2, 2), dtype=bool)
        )
        self.assertEqual(s["pixels_validos"], 0)
        self.assertEqual(s["pixels_ausentes"], 4)
        self.assertTrue(np.isnan(s["media"]))

    def test_geometria_e_geojson(self):
        with self.assertRaises(ValueError):
            validar_poligono([(0, 0), (1, 1), (0, 1), (1, 0)])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "roi.geojson"
            esperado = salvar_roi(
                [
                    (500000, 7600000),
                    (500030, 7600000),
                    (500030, 7600030),
                    (500000, 7600030),
                ],
                "EPSG:32623",
                p,
            )
            carregado = carregar_roi(p)["geometry"]
            self.assertEqual(carregado["type"], esperado["geometry"]["type"])
            np.testing.assert_allclose(
                carregado["coordinates"], esperado["geometry"]["coordinates"]
            )


if __name__ == "__main__":
    unittest.main()
