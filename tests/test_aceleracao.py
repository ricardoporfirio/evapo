"""Exercita seleção OpenCL, concorrência, memória e fallback sem GPU física."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from evapo.calculos import aceleracao
from evapo.calculos.opticos import calcular_indices_opticos


GPU = 4
CPU = 2


def dispositivo(nome="GPU de teste", fabricante="Fabricante", *, memoria=8 * 1024**3,
                integrada=False, fp64=True, tipo=GPU, disponivel=True, compilador=True):
    return SimpleNamespace(
        name=nome, vendor=fabricante, type=tipo, available=disponivel,
        compiler_available=compilador, host_unified_memory=integrada,
        global_mem_size=memoria, max_mem_alloc_size=memoria // 4,
        extensions="cl_khr_fp64" if fp64 else "",
    )


def plataforma(dispositivos=(), erro=None, nome="Plataforma de teste"):
    return SimpleNamespace(
        name=nome,
        get_devices=Mock(side_effect=erro, return_value=list(dispositivos)),
    )


def runtime(*plataformas, erro=None):
    return SimpleNamespace(
        device_type=SimpleNamespace(GPU=GPU),
        get_platforms=Mock(side_effect=erro, return_value=list(plataformas)),
    )


class BackendSimulado:
    def __init__(self, cl, gpu):
        self.dispositivo = gpu
        self.fp64 = bool(gpu.extensions)
        self.conferir = Mock()
        self.executar = Mock(side_effect=self._executar)

    def _executar(self, operacao, entradas, parametros, saidas):
        base = sum(np.asarray(a) for a in entradas) + parametros[0]
        return np.stack([base + n for n in range(saidas)]).astype("float32"), 3


class SelecaoAceleracaoTest(unittest.TestCase):
    def setUp(self):
        aceleracao.configurar_aceleracao("auto")
        self.addCleanup(aceleracao.configurar_aceleracao, "auto")
        self.dados = np.ones((256, 256), dtype="float32")

    def simular(self, cl, factory=BackendSimulado):
        importacao = patch.object(aceleracao.importlib, "import_module", return_value=cl)
        construcao = patch.object(aceleracao, "_OpenCLBackend", side_effect=factory)
        self.addCleanup(importacao.stop)
        self.addCleanup(construcao.stop)
        return importacao.start(), construcao.start()

    def test_cpu_forcada_e_snapshot_pendente_nao_importam_opencl(self):
        with patch.object(aceleracao.importlib, "import_module") as importar:
            self.assertEqual(aceleracao.informacoes_aceleracao(False)["backend"], "pendente")
            aceleracao.configurar_aceleracao("cpu")
            info = aceleracao.informacoes_aceleracao()
            self.assertEqual(info["backend"], "numpy")
            self.assertIn("CPU solicitada", aceleracao.descricao_aceleracao())
            self.assertIsNone(aceleracao.tentar_calculo_gpu("teste", [self.dados], [0], 1))
            importar.assert_not_called()
        with self.assertRaises(ValueError):
            aceleracao.configurar_aceleracao("nvidia")

    def test_ausencia_pyopencl_ou_runtime_preserva_cpu(self):
        for erro in (ModuleNotFoundError("pyopencl"), RuntimeError("PLATFORM_NOT_FOUND_KHR")):
            with self.subTest(erro=erro):
                aceleracao.configurar_aceleracao("auto")
                if isinstance(erro, ImportError):
                    importar = Mock(side_effect=erro)
                else:
                    importar = Mock(return_value=runtime(erro=erro))
                with patch.object(aceleracao.importlib, "import_module", importar):
                    self.assertIsNone(aceleracao.tentar_calculo_gpu("teste", [self.dados], [0], 1))
                    info = aceleracao.informacoes_aceleracao()
                self.assertEqual(info["backend"], "numpy")
                self.assertEqual(info["dispositivo"], "CPU")
                self.assertTrue(info["motivo"])
                importar.assert_called_once_with("pyopencl")

    def test_ausencia_gpu_e_dispositivos_sem_compilador_nao_inicializam_backend(self):
        cl = runtime(plataforma([
            dispositivo("CPU OpenCL", tipo=CPU),
            dispositivo("GPU indisponível", disponivel=False),
            dispositivo("GPU sem compilador", compilador=False),
        ]))
        _, construir = self.simular(cl)
        info = aceleracao.informacoes_aceleracao()
        self.assertEqual(info["backend"], "numpy")
        self.assertEqual(info["gpus_detectadas"], [])
        self.assertIn("Nenhuma GPU", info["motivo"])
        construir.assert_not_called()

    def test_plataforma_com_erro_nao_impede_gpu_de_outra_plataforma(self):
        gpu = dispositivo("GPU válida")
        cl = runtime(
            plataforma(erro=RuntimeError("driver inválido"), nome="Plataforma inválida"),
            plataforma([gpu]),
        )
        encontrados, problemas = aceleracao._descobrir_dispositivos(cl)
        self.assertEqual(encontrados, [gpu])
        self.assertIn("driver inválido", problemas[0])
        self.simular(cl)
        self.assertEqual(aceleracao.informacoes_aceleracao()["dispositivo"], "GPU válida")

    def test_nvidia_intel_e_amd_sao_aceitas_sem_preferencia_de_marca(self):
        for marca in ("NVIDIA", "Intel(R) Corporation", "Advanced Micro Devices, Inc."):
            with self.subTest(marca=marca):
                aceleracao.configurar_aceleracao("auto")
                cl = runtime(plataforma([dispositivo(fabricante=marca)]))
                with patch.object(aceleracao.importlib, "import_module", return_value=cl), patch.object(
                    aceleracao, "_OpenCLBackend", side_effect=BackendSimulado,
                ):
                    info = aceleracao.informacoes_aceleracao()
                self.assertEqual(info["backend"], "opencl")
                self.assertEqual(info["fabricante"], marca)

    def test_prioriza_gpu_discreta_e_memoria_independentemente_do_fabricante(self):
        intel = dispositivo("Intel integrada", "Intel", memoria=32 * 1024**3, integrada=True)
        nvidia = dispositivo("NVIDIA discreta", "NVIDIA", memoria=2 * 1024**3)
        amd = dispositivo("AMD discreta", "AMD", memoria=8 * 1024**3)
        self.simular(runtime(plataforma([intel, nvidia, amd])))
        info = aceleracao.informacoes_aceleracao()
        self.assertEqual(info["dispositivo"], "AMD discreta")
        self.assertEqual(len(info["gpus_detectadas"]), 3)

    def test_dispositivo_que_falha_na_verificacao_da_lugar_ao_proximo(self):
        ruim = dispositivo("GPU falha", memoria=16 * 1024**3)
        boa = dispositivo("GPU boa", memoria=8 * 1024**3)

        def factory(cl, gpu):
            backend = BackendSimulado(cl, gpu)
            if gpu is ruim:
                backend.conferir.side_effect = AssertionError("resultado do kernel incorreto")
            return backend

        _, construir = self.simular(runtime(plataforma([ruim, boa])), factory)
        info = aceleracao.informacoes_aceleracao()
        self.assertEqual(info["dispositivo"], "GPU boa")
        self.assertEqual(construir.call_count, 2)

    def test_limiar_broadcast_e_contadores_so_registram_operacoes_executadas(self):
        importar, construir = self.simular(runtime(plataforma([dispositivo()])))
        pequeno = np.zeros(aceleracao.MINIMO_PIXELS_GPU - 1, dtype="float32")
        self.assertIsNone(aceleracao.tentar_calculo_gpu("pequeno", [pequeno], [0], 1))
        importar.assert_not_called()
        for _ in range(2):
            resultado = aceleracao.tentar_calculo_gpu("teste", [self.dados, 2], [3], 2)
            self.assertEqual(resultado.shape, (2, 256, 256))
            self.assertEqual(resultado.dtype, np.dtype("float32"))
            np.testing.assert_array_equal(resultado[:, 0, 0], [6, 7])
        info = aceleracao.informacoes_aceleracao()
        self.assertEqual(info["operacoes_gpu"], ["teste"])
        self.assertEqual(info["blocos_gpu"], 6)
        self.assertEqual(info["pixels_gpu"], 2 * self.dados.size)
        self.assertEqual(construir.call_count, 1)
        info["operacoes_gpu"].append("não executada")
        self.assertEqual(aceleracao.informacoes_aceleracao()["operacoes_gpu"], ["teste"])

    def test_gpu_sem_fp64_mantem_operacoes_de_precisao_dupla_na_cpu(self):
        self.simular(runtime(plataforma([dispositivo(fp64=False)])))
        for _ in range(2):
            self.assertIsNone(aceleracao.tentar_calculo_gpu(
                "reflectancias", [self.dados], [0], 1, exige_fp64=True,
            ))
        self.assertIsNotNone(aceleracao.tentar_calculo_gpu("opticos", [self.dados], [0], 1))
        info = aceleracao.informacoes_aceleracao()
        self.assertEqual(info["operacoes_cpu_por_precisao"], ["reflectancias"])
        self.assertEqual(info["operacoes_gpu"], ["opticos"])

    def test_falha_de_memoria_recalcula_produto_na_cpu_e_desativa_backend(self):
        backend = BackendSimulado(None, dispositivo())
        backend.executar.side_effect = MemoryError("memória do dispositivo esgotada")
        importar, _ = self.simular(runtime(plataforma([backend.dispositivo])), lambda *args: backend)
        rho = {b: np.full(self.dados.shape, .2, dtype="float32") for b in range(2, 8)}
        rho[4][:] = .1
        rho[5][:] = .4
        with self.assertLogs(aceleracao.logger, level="WARNING"):
            produtos = calcular_indices_opticos(rho)
        np.testing.assert_allclose(produtos["ndvi"], .6, atol=1e-6)
        np.testing.assert_allclose(produtos["savi"], .45, atol=1e-6)
        self.assertIsNone(aceleracao.tentar_calculo_gpu("opticos", [self.dados], [0], 1))
        backend.executar.assert_called_once()
        importar.assert_called_once()
        info = aceleracao.informacoes_aceleracao()
        self.assertEqual(info["backend"], "numpy")
        self.assertIn("memória do dispositivo esgotada", info["motivo"])
        self.assertEqual(info["operacoes_gpu"], [])

    def test_inicializacao_e_execucao_concorrentes_preservam_fila_e_resultados(self):
        backend = BackendSimulado(None, dispositivo())
        contador = {"ativos": 0, "maximo": 0}

        def executar(*args):
            contador["ativos"] += 1
            contador["maximo"] = max(contador["maximo"], contador["ativos"])
            try:
                time.sleep(.005)
                return backend._executar(*args)
            finally:
                contador["ativos"] -= 1

        backend.executar.side_effect = executar
        _, construir = self.simular(runtime(plataforma([backend.dispositivo])), lambda *args: backend)
        barreira = threading.Barrier(6)

        def calcular(indice):
            barreira.wait(timeout=5)
            return aceleracao.tentar_calculo_gpu("teste", [self.dados], [indice], 1)

        with ThreadPoolExecutor(max_workers=6) as executor:
            resultados = list(executor.map(calcular, range(6)))
        for indice, resultado in enumerate(resultados):
            np.testing.assert_array_equal(resultado, indice + 1)
        construir.assert_called_once()
        backend.conferir.assert_called_once()
        self.assertEqual(contador["maximo"], 1)
        self.assertEqual(aceleracao.informacoes_aceleracao()["pixels_gpu"], 6 * self.dados.size)


class MemoriaOpenCLTest(unittest.TestCase):
    def criar_backend(self, *, memoria=8192, alocacao=128):
        backend = object.__new__(aceleracao._OpenCLBackend)
        backend.dtype = np.dtype("float64")
        backend.dispositivo = dispositivo(memoria=memoria)
        backend.dispositivo.max_mem_alloc_size = alocacao
        backend.contexto = object()
        backend.fila = object()
        backend.programa = object()
        backend.kernels = {}
        return backend

    def test_bloco_respeita_orcamento_total_alocacao_e_limite_de_pixels(self):
        backend = self.criar_backend()
        passo = backend.tamanho_bloco(2, 1)
        self.assertLessEqual(passo * (2 * 8 + 4), 8192 // 8)
        self.assertLessEqual(passo * 2 * 8, 128)
        self.assertLessEqual(passo * 4, 128)
        self.assertGreaterEqual(passo, 1)
        backend.dispositivo.max_mem_alloc_size = 1
        with self.assertRaisesRegex(RuntimeError, "Memória OpenCL insuficiente"):
            backend.tamanho_bloco(2, 1)
        backend = self.criar_backend(memoria=64 * 1024**3, alocacao=16 * 1024**3)
        self.assertLessEqual(backend.tamanho_bloco(1, 1), aceleracao.LIMITE_PIXELS_BLOCO)

    def test_execucao_em_blocos_preserva_ordem_ultimo_bloco_e_libera_buffers(self):
        backend = self.criar_backend(memoria=8192, alocacao=80)
        buffers, tamanhos = [], []

        class Buffer:
            def __init__(self, contexto, flags, size=None, hostbuf=None):
                self.bytes = np.empty(size if hostbuf is None else hostbuf.nbytes, dtype="uint8")
                if hostbuf is not None:
                    self.bytes[:] = hostbuf.view("uint8").ravel()
                self.liberado = False
                buffers.append(self)

            def release(self):
                self.liberado = True

        def copiar(fila, destino, origem, **opcoes):
            if isinstance(destino, Buffer):
                origem_bytes = np.ascontiguousarray(origem).view("uint8").ravel()
                destino.bytes[:origem_bytes.size] = origem_bytes
            else:
                destino.view("uint8").ravel()[:] = origem.bytes[:destino.nbytes]

        def kernel(fila, global_size, local_size, entrada, parametros, saida, quantidade):
            n = int(quantidade)
            tamanhos.append(n)
            a, b = entrada.bytes[:2*n*8].view("float64").reshape(2, n)
            fator = parametros.bytes.view("float64")[0]
            valores = np.stack([a + fator*b, a-b]).astype("float32")
            saida.bytes[:valores.nbytes] = valores.view("uint8").ravel()

        backend.cl = SimpleNamespace(
            Buffer=Buffer, Kernel=Mock(return_value=kernel), enqueue_copy=copiar,
            mem_flags=SimpleNamespace(READ_ONLY=1, COPY_HOST_PTR=2, WRITE_ONLY=4),
        )
        a = np.arange(24, dtype="float64").reshape(4, 6)
        b = a[:, ::-1]
        resultado, blocos = backend.executar("teste", [a, b], [2], 2)
        np.testing.assert_array_equal(resultado, np.stack([a+2*b, a-b]).astype("float32"))
        self.assertEqual(sum(tamanhos), a.size)
        self.assertEqual(blocos, len(tamanhos))
        self.assertGreater(blocos, 1)
        self.assertLess(tamanhos[-1], tamanhos[0])
        self.assertTrue(all(buffer.liberado for buffer in buffers))
        self.assertEqual(len(buffers), 3)
        backend.cl.Kernel.assert_called_once()
        backend.cl.enqueue_copy = Mock(side_effect=MemoryError("falha na transferência"))
        with self.assertRaises(MemoryError):
            backend.executar("teste", [a, b], [2], 2)
        self.assertTrue(all(buffer.liberado for buffer in buffers))


if __name__ == "__main__":
    unittest.main()
