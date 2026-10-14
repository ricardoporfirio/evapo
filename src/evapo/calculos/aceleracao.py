"""GPU OpenCL automática por processo; CPU NumPy em ausência ou falha de GPU.

Não importa PyOpenCL nem cria contexto ao importar o módulo. Arrays pequenos
ficam na CPU. Um lock protege inicialização, fila e kernels usados pelo mapa.
Somente o cálculo numérico vai à GPU; Rasterio, estatísticas e figuras usam CPU.
"""

import importlib
import logging
import os
from pathlib import Path
import tempfile
import threading

import numpy as np

MINIMO_PIXELS_GPU = 65_536
LIMITE_PIXELS_BLOCO = 1_048_576
_lock = threading.RLock()
_modo = "cpu" if os.environ.get("EVAPO_DISPOSITIVO", "auto").lower() == "cpu" else "auto"
_inicializado = False
_backend = None
_informacoes = {}
logger = logging.getLogger(__name__)


def configurar_aceleracao(modo="auto"):
    """Reinicia a seleção: automático por padrão; CPU pode ser forçada."""
    if modo not in ("auto", "cpu"):
        raise ValueError("Dispositivo deve ser auto ou cpu.")
    global _modo, _inicializado, _backend
    with _lock:
        _modo = modo
        _inicializado = False
        _backend = None
        _informacoes.clear()


def _estado_base():
    return {
        "modo": _modo,
        "backend": "numpy" if _modo == "cpu" else "pendente",
        "dispositivo": "CPU" if _modo == "cpu" else None,
        "fabricante": None,
        "precisao": None,
        "motivo": "CPU solicitada." if _modo == "cpu" else "Detecção ainda não necessária.",
        "operacoes_gpu": [],
        "operacoes_cpu_por_precisao": [],
        "blocos_gpu": 0,
        "pixels_gpu": 0,
        "gpus_detectadas": [],
    }


def _prioridade(dispositivo):
    # Sem preferência por fabricante. Memória compartilhada costuma indicar iGPU.
    return (not bool(dispositivo.host_unified_memory), int(dispositivo.global_mem_size))


def _descobrir_dispositivos(cl):
    dispositivos, problemas = [], []
    for plataforma in cl.get_platforms():
        try:
            candidatos = plataforma.get_devices(device_type=cl.device_type.GPU)
            for dispositivo in candidatos:
                if (dispositivo.type & cl.device_type.GPU and dispositivo.available
                        and dispositivo.compiler_available):
                    dispositivos.append(dispositivo)
        except Exception as erro:
            problemas.append(f"{plataforma.name}: {erro}")
    return sorted(dispositivos, key=_prioridade, reverse=True), problemas


class _OpenCLBackend:
    def __init__(self, cl, dispositivo):
        from evapo.calculos.kernels_opticos import KERNELS_OPTICOS
        from evapo.calculos.kernels_energia import KERNELS_ENERGIA

        self.cl = cl
        self.dispositivo = dispositivo
        extensoes = dispositivo.extensions.split()
        self.fp64 = "cl_khr_fp64" in extensoes or "cl_amd_fp64" in extensoes
        self.dtype = np.dtype("float64" if self.fp64 else "float32")
        self.contexto = cl.Context(devices=[dispositivo])
        self.fila = cl.CommandQueue(self.contexto, device=dispositivo)
        cabecalho = "typedef float real_t;\n"
        if self.fp64:
            extensao = "cl_khr_fp64" if "cl_khr_fp64" in extensoes else "cl_amd_fp64"
            cabecalho = f"#pragma OPENCL EXTENSION {extensao} : enable\ntypedef double real_t;\n"
        cache = Path(tempfile.gettempdir()) / "evapo-opencl-cache"
        cache.mkdir(parents=True, exist_ok=True)
        opcoes = ["-cl-std=CL1.2"]
        if dispositivo.single_fp_config & cl.device_fp_config.CORRECTLY_ROUNDED_DIVIDE_SQRT:
            opcoes.append("-cl-fp32-correctly-rounded-divide-sqrt")
        self.programa = cl.Program(
            self.contexto, cabecalho + KERNELS_OPTICOS + (KERNELS_ENERGIA if self.fp64 else ""),
        ).build(options=opcoes, cache_dir=str(cache))
        self.kernels = {}

    def tamanho_bloco(self, entradas, saidas):
        item = self.dtype.itemsize
        memoria = int(self.dispositivo.global_mem_size)
        alocacao = int(self.dispositivo.max_mem_alloc_size)
        orcamento = min(256 * 1024**2, memoria // 8)
        capacidade = min(
            orcamento // (entradas * item + saidas * 4),
            alocacao // (entradas * item), alocacao // (saidas * 4),
        )
        if capacidade < 1:
            raise RuntimeError("Memória OpenCL insuficiente para um bloco.")
        return max(1, min(LIMITE_PIXELS_BLOCO, capacidade))

    def executar(self, operacao, entradas, parametros, saidas):
        """Empacota blocos; nunca envia uma cena inteira à VRAM de uma vez."""
        cl = self.cl
        forma = entradas[0].shape
        planos = [np.ravel(entrada) for entrada in entradas]
        total = planos[0].size
        resultado = np.empty((saidas, total), dtype="float32")
        passo = min(total, self.tamanho_bloco(len(entradas), saidas))
        kernel = self.kernels.get(operacao)
        if kernel is None:
            kernel = self.kernels[operacao] = cl.Kernel(self.programa, operacao)
        parametros = np.ascontiguousarray(parametros, dtype=self.dtype)
        buffers = []
        blocos = 0
        try:
            memoria_entrada = cl.Buffer(self.contexto, cl.mem_flags.READ_ONLY, len(entradas)*passo*self.dtype.itemsize)
            buffers.append(memoria_entrada)
            memoria_parametros = cl.Buffer(self.contexto, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=parametros)
            buffers.append(memoria_parametros)
            memoria_saida = cl.Buffer(self.contexto, cl.mem_flags.WRITE_ONLY, saidas*passo*4)
            buffers.append(memoria_saida)
            for inicio in range(0, total, passo):
                fim = min(inicio + passo, total)
                n = fim - inicio
                pacote = np.empty((len(entradas), n), dtype=self.dtype)
                for k, plano in enumerate(planos):
                    pacote[k] = plano[inicio:fim]
                cl.enqueue_copy(self.fila, memoria_entrada, pacote, is_blocking=True)
                kernel(self.fila, (n,), None, memoria_entrada, memoria_parametros,
                       memoria_saida, np.int32(n))
                retorno = np.empty((saidas, n), dtype="float32")
                cl.enqueue_copy(self.fila, retorno, memoria_saida, is_blocking=True)
                resultado[:, inicio:fim] = retorno
                blocos += 1
        finally:
            for buffer in reversed(buffers):
                buffer.release()
        return resultado.reshape((saidas, *forma)), blocos

    def conferir(self):
        """Qualifica o dispositivo com NaN, limiares e cancelamento de DN."""
        from evapo.calculos.opticos import _indices_cpu, _reparar_limites
        from evapo.calculos.albedo import PESOS_ALBEDO_TOA
        from evapo.calculos.indices import L_IAF

        red = np.array([0, .1, .2, np.nan, -.01, .04, 0, .2], dtype="float32")
        nir = np.array([.04, .3, .2, .3, .2, .5, 0, .9], dtype="float32")
        rho = {b: np.full(red.shape, .2, dtype="float32") for b in range(2, 8)}
        rho[4], rho[5] = red, nir
        params = [.5, L_IAF, *PESOS_ALBEDO_TOA.values()]
        recebido, _ = self.executar("opticos", [rho[b] for b in range(2, 8)], params, 4)
        _reparar_limites(recebido, rho, .5)
        esperado = _indices_cpu(rho, .5)
        for a, b in zip(recebido, esperado.values()):
            np.testing.assert_array_equal(np.isfinite(a), np.isfinite(b))
            np.testing.assert_allclose(a, b, atol=2e-6, rtol=5e-6, equal_nan=True)
        if self.fp64:
            dn = np.array([5000, 6000, 65535, 0], dtype="float64")
            x = [dn]*7 + [np.zeros(4), np.zeros(4), np.ones(4)]
            p = [.5, *([.00002, -.1]*7)]
            obtido, _ = self.executar("reflectancias", x, p, 7)
            referencia = ((dn*.00002-.1)/.5).astype("float32")
            referencia[dn == 0] = np.nan
            for banda in obtido:
                np.testing.assert_array_equal(np.isfinite(banda), np.isfinite(referencia))
                np.testing.assert_allclose(banda, referencia, atol=1e-7, rtol=1e-6, equal_nan=True)
                if banda[0] != 0:
                    raise RuntimeError("Precisão insuficiente no limiar de reflectância zero.")


def _inicializar():
    global _backend, _inicializado
    if _inicializado:
        return
    _inicializado = True
    _informacoes.update(_estado_base())
    if _modo == "cpu":
        return
    motivos = []
    try:
        cl = importlib.import_module("pyopencl")
        dispositivos, motivos = _descobrir_dispositivos(cl)
        _informacoes["gpus_detectadas"] = [
            {"dispositivo": d.name.strip(), "fabricante": d.vendor.strip(),
             "memoria_bytes": int(d.global_mem_size)} for d in dispositivos
        ]
        for dispositivo in dispositivos:
            try:
                candidato = _OpenCLBackend(cl, dispositivo)
                candidato.conferir()
                _backend = candidato
                _informacoes.update(
                    backend="opencl", dispositivo=dispositivo.name.strip(),
                    fabricante=dispositivo.vendor.strip(),
                    precisao="FP64 e FP32" if candidato.fp64 else "FP32; etapas FP64 na CPU",
                    motivo=None,
                )
                return
            except Exception as erro:
                motivos.append(f"{dispositivo.name}: {erro}")
        if not dispositivos:
            motivos.append("Nenhuma GPU OpenCL disponível com compilador; verifique o driver da placa.")
    except ImportError:
        motivos.append("PyOpenCL não instalado; execute uv sync no projeto.")
    except Exception as erro:
        motivos.append(f"OpenCL indisponível: {erro}")
    _informacoes.update(backend="numpy", dispositivo="CPU", motivo="; ".join(motivos)[:2000])


def informacoes_aceleracao(inicializar=True):
    """Snapshot JSON: dispositivo selecionado e operações efetivamente executadas."""
    if inicializar:
        with _lock:
            _inicializar()
    # A interface lê o estado sem aguardar um kernel/compilação em outra thread.
    dados = _informacoes.copy() or _estado_base()
    return {k: [dict(a) if isinstance(a, dict) else a for a in v]
            if isinstance(v, list) else v for k, v in dados.items()}


def descricao_aceleracao(inicializar=True):
    dados = informacoes_aceleracao(inicializar)
    if dados["backend"] == "opencl":
        return f"GPU OpenCL: {dados['dispositivo']} ({dados['precisao']}); blocos pequenos na CPU"
    if dados["backend"] == "pendente":
        return "GPU: detecção automática no primeiro cálculo grande"
    return f"CPU NumPy: {dados['motivo']}"


def tentar_calculo_gpu(operacao, entradas, parametros, quantidade_saidas, *, exige_fp64=False):
    """Retorna NumPy ou None para recomputação CPU, inclusive após erro OpenCL."""
    entradas = np.broadcast_arrays(*[np.asarray(a) for a in entradas])
    if not entradas or entradas[0].size == 0 or entradas[0].size < MINIMO_PIXELS_GPU:
        return None
    global _backend
    with _lock:
        _inicializar()
        if _backend is None:
            return None
        if exige_fp64 and not _backend.fp64:
            if operacao not in _informacoes["operacoes_cpu_por_precisao"]:
                _informacoes["operacoes_cpu_por_precisao"].append(operacao)
            return None
        try:
            resultado, blocos = _backend.executar(operacao, entradas, parametros, quantidade_saidas)
            _informacoes["blocos_gpu"] += blocos
            _informacoes["pixels_gpu"] += entradas[0].size
            if operacao not in _informacoes["operacoes_gpu"]:
                _informacoes["operacoes_gpu"].append(operacao)
            return resultado
        except Exception as erro:
            motivo = (f"Falha OpenCL em {operacao} ({_informacoes['dispositivo']}); "
                      f"cálculo retomado na CPU: {erro}")
            logger.warning(motivo)
            _backend = None
            _informacoes.update(backend="numpy", dispositivo="CPU", fabricante=None,
                                precisao=None, motivo=motivo[:2000])
            return None
