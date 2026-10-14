"""Valida fallback e compara kernels energéticos com a referência NumPy."""

import unittest
from unittest.mock import patch

import numpy as np

from evapo.calculos.aceleracao import informacoes_aceleracao, tentar_calculo_gpu
from evapo.calculos.energia import (
    LAMBDA_B10, RHO, SIGMA, calcular_emissividades_sebal,
    calcular_radiacoes, calcular_termicos,
)


MTL = {
    "IMAGE_ATTRIBUTES": {"SUN_ELEVATION": 30, "EARTH_SUN_DISTANCE": 1.02},
    "LEVEL1_RADIOMETRIC_RESCALING": {
        "RADIANCE_MULT_BAND_10": 0.0003342, "RADIANCE_ADD_BAND_10": 0.1,
    },
    "LEVEL1_THERMAL_CONSTANTS": {
        "K1_CONSTANT_BAND_10": 774.8853, "K2_CONSTANT_BAND_10": 1321.0789,
    },
}


def repetir(valores):
    """Grade que ultrapassa o limite de despacho GPU, incluindo suas bordas."""
    return np.resize(np.asarray(valores, dtype="float64"), 256 * 256).reshape(256, 256)


class FallbackEnergiaTest(unittest.TestCase):
    def test_todas_as_etapas_exigem_fp64_e_mantem_fallback_numpy(self):
        with patch("evapo.calculos.energia.tentar_calculo_gpu", return_value=None) as gpu:
            estreita, larga = calcular_emissividades_sebal([0.2, -0.2], [1, np.nan], [0, 128])
            np.testing.assert_allclose(estreita, [0.9733, 0.99], atol=1e-6)
            np.testing.assert_allclose(larga, [0.96, 0.985], atol=1e-6)
            radiancia_300k = 774.8853 / np.expm1(1321.0789 / 300)
            dn = (radiancia_300k - 0.1) / 0.0003342
            termicos = calcular_termicos([dn, 0], MTL, 1, 0.95)
            self.assertAlmostEqual(float(termicos["temperatura_superficie"][0]), 26.85, places=4)
            self.assertTrue(np.isnan(termicos["temperatura_superficie"][1]))
            radiacoes = calcular_radiacoes([0.75], MTL, 25, 0.95, 30, 0.2)
            self.assertTrue(np.isfinite(radiacoes["saldo_radiacao"]).all())
        self.assertEqual([c.args[0] for c in gpu.call_args_list], ["emissividades_sebal", "termicos", "radiacoes"])
        for chamada in gpu.call_args_list:
            self.assertIs(chamada.kwargs["exige_fp64"], True)
            self.assertEqual(len({np.shape(a) for a in chamada.args[1]}), 1)

    def test_metadados_invalidos_nao_chegam_ao_dispositivo(self):
        with patch("evapo.calculos.energia.tentar_calculo_gpu", return_value=None) as gpu:
            with self.assertRaises(ValueError):
                calcular_emissividades_sebal([0.2], None)
            invalido = {**MTL, "LEVEL1_RADIOMETRIC_RESCALING": {
                "RADIANCE_MULT_BAND_10": -1, "RADIANCE_ADD_BAND_10": 0,
            }}
            with self.assertRaises(ValueError):
                calcular_termicos([30000], invalido, 0.98, 0.98)
            with self.assertRaises(ValueError):
                calcular_radiacoes([0.75], {"IMAGE_ATTRIBUTES": {"SUN_ELEVATION": -1}})
            with self.assertRaises(ValueError):
                calcular_radiacoes([0.75], MTL, "nan")
            gpu.assert_not_called()

    def test_dispatch_preserva_produtos_opcionais_e_matrizes_numpy(self):
        def resultado(operacao, entradas, parametros, quantidade_saidas, **opcoes):
            return np.zeros((quantidade_saidas, *np.shape(entradas[0])), dtype="float32")

        with patch("evapo.calculos.energia.tentar_calculo_gpu", side_effect=resultado) as gpu:
            sem_ar = calcular_radiacoes([0.75, np.nan], MTL)
            com_ar = calcular_radiacoes([0.75, np.nan], MTL, 25)
            com_saldo = calcular_radiacoes([0.75, np.nan], MTL, 25, 0.98, 30, 0.2)
        self.assertEqual(len(sem_ar), 2)
        self.assertEqual(len(com_ar), 3)
        self.assertEqual(len(com_saldo), 4)
        self.assertIn("saldo_radiacao", com_saldo)
        self.assertNotIn("saldo_radiacao", com_ar)
        self.assertEqual([c.args[3] for c in gpu.call_args_list], [2, 3, 4])
        for dados in (*sem_ar.values(), *com_ar.values(), *com_saldo.values()):
            self.assertEqual(dados.dtype, np.dtype("float32"))
            self.assertEqual(dados.shape, (2,))


class OpenCLEnergiaTest(unittest.TestCase):
    def comparar(self, operacao, entradas, parametros, esperado, *, atol):
        estado = informacoes_aceleracao()
        if estado["backend"] != "opencl":
            if estado.get("gpus_detectadas"):
                self.fail(f"GPU detectada, mas sua qualificação falhou: {estado.get('motivo')}")
            self.skipTest(f"GPU OpenCL indisponível: {estado.get('motivo')}")
        if estado.get("precisao") != "FP64 e FP32":
            self.skipTest("GPU OpenCL disponível sem FP64; energia permanece na CPU.")
        obtido = tentar_calculo_gpu(operacao, entradas, parametros, len(esperado), exige_fp64=True)
        if obtido is None:
            self.fail(f"GPU FP64 selecionada falhou em {operacao}: {informacoes_aceleracao().get('motivo')}")
        self.assertEqual(obtido.shape, np.shape(esperado))
        self.assertEqual(obtido.dtype, np.dtype("float32"))
        # allclose isoladamente pode esconder perdas de pixels válidos.
        np.testing.assert_array_equal(np.isnan(obtido), np.isnan(esperado))
        np.testing.assert_array_equal(np.isfinite(obtido), np.isfinite(esperado))
        np.testing.assert_allclose(obtido, esperado, rtol=2e-6, atol=atol, equal_nan=True)

    def test_emissividades_agua_neve_limites_iaf_e_nodata(self):
        entradas = (
            repetir([0.2, -0.2, 0.3, 0.3, np.nan, 0, 1.1, 0.8, 0.8, 0.8, 0.3, 0.3]),
            repetir([1, np.nan, np.nan, 2, 0, 0, 1, 2.9999999, 3, 6, -1, np.inf]),
            repetir([0, 128, 128, 32, 128, 0, 0, 0, 0, 8, 0, 0]).astype("uint16"),
        )
        with patch("evapo.calculos.energia.tentar_calculo_gpu", return_value=None):
            esperado = np.stack(calcular_emissividades_sebal(*entradas))
        self.comparar("emissividades_sebal", entradas, (0,), esperado, atol=2e-7)

    def test_termicos_emissividades_distintas_dn_e_dominio_invalidos(self):
        entradas = (
            repetir([30000, 0, 1, 65535, np.nan, np.inf, -1, 30000, 30000, 30000, 30000, 30000]),
            repetir([0.97, 0.99, 1, 0.98, 0.99, 0.97, 0.97, 0, 1.1, np.nan, 0.99, 0.99]),
            repetir([0.95, 0.985, 1, 0.98, 0.985, 0.95, 0.95, 0.95, 0.95, 0.95, 0, np.nan]),
        )
        with patch("evapo.calculos.energia.tentar_calculo_gpu", return_value=None):
            esperado = np.stack(list(calcular_termicos(entradas[0], MTL, *entradas[1:]).values()))
        parametros = (0.0003342, 0.1, 774.8853, 1321.0789, LAMBDA_B10, RHO, SIGMA)
        self.comparar("termicos", entradas, parametros, esperado, atol=1e-4)

    def test_radiacoes_com_saldo_e_entradas_invalidas(self):
        entradas = (
            repetir([0.75, 0, 1, 1.1, 1e-6, np.nan, np.inf, 0.75, 0.75, 0.75, 0.75, 0.75]),
            repetir([0.95, 0.98, 0.98, 0.98, 0.98, 0.98, 0.98, 0, 1.1, np.nan, 0.985, 0.98]),
            repetir([30, 30, 30, 30, 30, 30, 30, 30, 30, 30, -273.15, 30]),
            repetir([0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 1.1]),
        )
        with patch("evapo.calculos.energia.tentar_calculo_gpu", return_value=None):
            esperado = np.stack(list(calcular_radiacoes(entradas[0], MTL, 25, *entradas[1:]).values()))
        parametros = (1367 * np.sin(np.deg2rad(30)) / 1.02**2, 298.15, 1, 1, SIGMA)
        self.comparar("radiacoes", entradas, parametros, esperado, atol=5e-4)

    def test_radiacoes_sem_ar_e_sem_saldo(self):
        tau = repetir([0.75, np.nan, 0, 1, 0.76])
        entradas = (tau,) + (np.full_like(tau, np.nan),) * 3
        for temperatura, saidas in ((None, 2), (25, 3)):
            with self.subTest(saidas=saidas):
                with patch("evapo.calculos.energia.tentar_calculo_gpu", return_value=None):
                    esperado = np.stack(list(calcular_radiacoes(tau, MTL, temperatura).values()))
                parametros = (1367 * np.sin(np.deg2rad(30)) / 1.02**2,
                              298.15 if temperatura is not None else 0, int(temperatura is not None), 0, SIGMA)
                self.comparar("radiacoes", entradas, parametros, esperado, atol=5e-4)


if __name__ == "__main__":
    unittest.main()
