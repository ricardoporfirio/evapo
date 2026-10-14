"""Compara CPU/OpenCL em dados válidos, QA, NoData e limiares científicos."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from evapo.calculos import aceleracao
from evapo.calculos.opticos import calcular_indices_opticos
from evapo.calculos.reflectancia import calcular_reflectancias


def mtl():
    coef = {}
    for b in range(1, 8):
        coef[f"REFLECTANCE_MULT_BAND_{b}"] = .00002
        coef[f"REFLECTANCE_ADD_BAND_{b}"] = -.1
    return {"IMAGE_ATTRIBUTES": {"SUN_ELEVATION": 30},
            "LEVEL1_RADIOMETRIC_RESCALING": coef}


class OpticosFallbackTest(unittest.TestCase):
    def test_validacao_l_e_grade_antes_da_gpu(self):
        with patch("evapo.calculos.opticos.tentar_calculo_gpu") as gpu:
            with self.assertRaises(ValueError):
                calcular_indices_opticos({b: np.zeros((2, 2)) for b in range(2, 8)}, np.nan)
            gpu.assert_not_called()
        with patch("evapo.calculos.reflectancia.tentar_calculo_gpu") as gpu:
            with self.assertRaises(ValueError):
                calcular_reflectancias(np.ones((7, 2, 2)), np.zeros((2, 2)),
                                       np.zeros((2, 2)), mtl(), np.ones((3, 3)))
            gpu.assert_not_called()

    def test_indice_com_banda_mascarada_preserva_nodata(self):
        rho = {b: np.ma.array([.1, .2], mask=[False, True]) for b in range(2, 8)}
        with patch("evapo.calculos.opticos.tentar_calculo_gpu", return_value=None):
            produtos = calcular_indices_opticos(rho)
        for dados in produtos.values():
            self.assertTrue(np.isfinite(dados[0]))
            self.assertTrue(np.isnan(dados[1]))


class OpticosOpenCLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        aceleracao.configurar_aceleracao("auto")
        estado = aceleracao.informacoes_aceleracao()
        if estado["backend"] != "opencl":
            if estado["gpus_detectadas"]:
                raise AssertionError(f"GPU detectada falhou: {estado['motivo']}")
            raise unittest.SkipTest(estado["motivo"])

    def comparar(self, cpu, gpu, atol=3e-6):
        self.assertEqual(set(cpu), set(gpu))
        for nome in cpu:
            with self.subTest(produto=nome):
                self.assertEqual(gpu[nome].dtype, np.dtype("float32"))
                np.testing.assert_array_equal(np.isfinite(cpu[nome]), np.isfinite(gpu[nome]))
                np.testing.assert_allclose(cpu[nome], gpu[nome], atol=atol, rtol=4e-6, equal_nan=True)

    def test_programa_optico_fp32_compila_e_executa_sem_kernels_fp64(self):
        # Executa também a variante usada por placas sem FP64, na GPU real.
        ativo = aceleracao._backend
        cl, device = ativo.cl, ativo.dispositivo
        sem_fp64 = SimpleNamespace(
            extensions="", single_fp_config=device.single_fp_config,
            global_mem_size=device.global_mem_size,
            max_mem_alloc_size=device.max_mem_alloc_size,
        )
        adaptador = SimpleNamespace(
            Context=lambda devices: cl.Context(devices=[device]),
            CommandQueue=lambda contexto, device: cl.CommandQueue(contexto, device=ativo.dispositivo),
            Program=cl.Program, Kernel=cl.Kernel, Buffer=cl.Buffer,
            mem_flags=cl.mem_flags, device_fp_config=cl.device_fp_config,
            enqueue_copy=cl.enqueue_copy,
        )
        variante = aceleracao._OpenCLBackend(adaptador, sem_fp64)
        self.assertFalse(variante.fp64)
        self.assertEqual(variante.dtype, np.dtype("float32"))
        variante.conferir()

    def test_reflectancia_mascara_qa_saturacao_zero_e_cena_em_blocos(self):
        if aceleracao.informacoes_aceleracao()["precisao"] != "FP64 e FP32":
            self.skipTest("Reflectância FP64 permanece CPU nesta placa.")
        rng = np.random.default_rng(53)
        dn = np.ma.array(rng.integers(0, 65000, (7, 256, 257), dtype="uint16"), mask=False)
        dn[:, 0, :4] = [5000, 6000, 0, 65535]
        dn.mask[2, 1, 1] = True
        qa, sat = np.zeros((256, 257), dtype="uint16"), np.zeros((256, 257), dtype="uint16")
        qa[0, 4:8] = [1, 8, 128, 32]
        sat[0, 8:12] = [1, 8, 64, 2048]
        area = np.ones(qa.shape, bool)
        area[1, 2] = False
        with patch("evapo.calculos.reflectancia.tentar_calculo_gpu", return_value=None):
            cpu = calcular_reflectancias(dn, qa, sat, mtl(), area)
        antes = aceleracao.informacoes_aceleracao()["blocos_gpu"]
        with patch.object(aceleracao, "LIMITE_PIXELS_BLOCO", 13_000):
            gpu = calcular_reflectancias(dn, qa, sat, mtl(), area)
        self.assertGreater(aceleracao.informacoes_aceleracao()["blocos_gpu"]-antes, 1)
        self.comparar(cpu, gpu, atol=1e-7)
        self.assertEqual(gpu[4][0, 0], 0)  # cancelamento que falha em float32

    def test_indices_limites_savi_iaf_e_entradas_invalidas(self):
        rng = np.random.default_rng(17)
        rho = {b: rng.uniform(0, 1, (256, 257)).astype("float32") for b in range(2, 8)}
        red, nir = rho[4], rho[5]
        red[0, :8] = [0, 0, -.01, np.nan, .1, .2, .1, .1]
        nir[0, :8] = [0, .1, .2, .1, np.inf, .2, .3, .9]
        limite_iaf3 = .69 - .59*np.exp(-.91*3)
        for j, limite in enumerate((.1, .687, limite_iaf3)):
            valores = [np.nextafter(np.float32(limite), -np.inf, dtype=np.float32),
                       np.float32(limite),
                       np.nextafter(np.float32(limite), np.inf, dtype=np.float32)]
            for k, savi in enumerate(valores):
                # S=.1L: nir=(S*(red+.1)+1.1*red)/(1.1-S)
                red[1+j, k] = .1
                nir[1+j, k] = (float(savi)*.2+.11)/(1.1-float(savi))
        for L in (0, .2, .5, 1):
            with self.subTest(L=L):
                with patch("evapo.calculos.opticos.tentar_calculo_gpu", return_value=None):
                    cpu = calcular_indices_opticos(rho, L)
                gpu = calcular_indices_opticos(rho, L)
                self.assertIn("opticos", aceleracao.informacoes_aceleracao()["operacoes_gpu"])
                self.assertEqual(aceleracao.informacoes_aceleracao()["backend"], "opencl")
                self.comparar(cpu, gpu)
                np.testing.assert_array_equal(cpu["iaf"][1:4, :3], gpu["iaf"][1:4, :3])


if __name__ == "__main__":
    unittest.main()
