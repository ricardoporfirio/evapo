"""Índices/albedo em um estágio GPU; conserva as funções NumPy de referência."""

import numpy as np

from evapo.calculos.aceleracao import tentar_calculo_gpu
from evapo.calculos.albedo import PESOS_ALBEDO_TOA, calcular_albedo_toa
from evapo.calculos.indices import L_IAF, calcular_iaf_reflectancias, calcular_ndvi, calcular_savi


def _indices_cpu(reflectancias, L):
    red, nir = reflectancias[4], reflectancias[5]
    return {
        "albedo_toa": calcular_albedo_toa(reflectancias),
        "ndvi": calcular_ndvi(red, nir),
        "savi": calcular_savi(red, nir, L=L),
        "iaf": calcular_iaf_reflectancias(red, nir),
    }


def _reparar_limites(resultado, reflectancias, L):
    # Uma diferença de 1 ULP junto de 0,687 altera a saturação do IAF.
    # Recalcula somente pixels próximos desses limites com a referência NumPy.
    red = np.asarray(reflectancias[4], dtype="float32")
    nir = np.asarray(reflectancias[5], dtype="float32")
    with np.errstate(invalid="ignore", divide="ignore"):
        s = (1 + L_IAF) * (nir-red) / (nir+red+L_IAF)
        exibido = (1 + L) * (nir-red) / (nir+red+L)
    risco = (np.abs(s-.1) < 2e-6) | (np.abs(s-.687) < 2e-6)
    risco |= np.abs(np.abs(exibido)-1) < 2e-6
    risco |= np.abs(resultado[3]-3) < 1e-5  # troca de ramo da emissividade
    if np.any(risco):
        amostra = {b: np.asarray(reflectancias[b])[risco] for b in range(2, 8)}
        for destino, referencia in zip(resultado, _indices_cpu(amostra, L).values()):
            destino[risco] = referencia


def calcular_indices_opticos(reflectancias, L=0.5):
    """Retorna albedo_toa, NDVI, SAVI e IAF NumPy; CPU em cenas pequenas."""
    if not np.isfinite(L) or not 0 <= L <= 1:
        raise ValueError("L deve estar entre 0 e 1.")
    rho = {b: np.ma.asarray(reflectancias[b], dtype="float32").filled(np.nan)
           for b in range(2, 8)}
    resultado = tentar_calculo_gpu(
        "opticos", [rho[b] for b in range(2, 8)],
        [L, L_IAF, *PESOS_ALBEDO_TOA.values()], 4,
    )
    if resultado is None:
        return _indices_cpu(rho, L)
    _reparar_limites(resultado, rho, L)
    return dict(zip(("albedo_toa", "ndvi", "savi", "iaf"), resultado))
