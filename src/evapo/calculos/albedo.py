"""Albedo TOA de Silva et al. (2016) e correção atmosférica SEBAL.

Cada posição dos arrays representa um pixel. NaN significa que aquele pixel
não tem um resultado válido e deve ficar fora dos mapas e das estatísticas.
"""

import numpy as np

PESOS_ALBEDO_TOA = {
    2: 0.300,
    3: 0.277,
    4: 0.233,
    5: 0.143,
    6: 0.036,
    7: 0.012,
}


def calcular_albedo_toa(reflectancias):
    """Combina B2–B7 TOA, conforme Silva et al., tabela 5.

    Pesos publicados arredondados (soma 1,001). B1 não participa: os pesos
    B1–B7 de Ke et al. são para reflectâncias de superfície, não TOA.
    https://doi.org/10.1590/1807-1929/agriambi.v20n1p3-8
    """
    bandas = np.broadcast_arrays(*[
        np.ma.asarray(reflectancias[b], dtype="float32").filled(np.nan)
        for b in PESOS_ALBEDO_TOA
    ])
    albedo_toa = np.zeros(bandas[0].shape, dtype="float32")
    validos = np.ones(bandas[0].shape, dtype=bool)
    for reflectancia, peso in zip(bandas, PESOS_ALBEDO_TOA.values()):
        validos &= np.isfinite(reflectancia) & (reflectancia >= 0)
        albedo_toa += peso * reflectancia

    # O modelo ERDAS limita o albedo ao intervalo de 0 a 1.
    return np.where(validos, np.clip(albedo_toa, 0, 1), np.nan)


def calcular_transmissividade(altitude_m):
    """Estima a fração de radiação que atravessa a atmosfera, entre 0 e 1."""
    # NoData do MDE vira NaN, para não ser confundido com altitude zero.
    altitude = np.ma.asarray(altitude_m, dtype="float32").filled(np.nan)
    transmissividade = 0.75 + 0.00002 * altitude

    altitude_conhecida = np.isfinite(altitude)
    transmissividade_positiva = transmissividade > 0
    transmissividade_ate_um = transmissividade <= 1

    # As três condições precisam ser atendidas no mesmo pixel.
    pixels_validos = altitude_conhecida.copy()
    pixels_validos &= transmissividade_positiva
    pixels_validos &= transmissividade_ate_um

    resultado = np.full(altitude.shape, np.nan, dtype="float32")
    resultado[pixels_validos] = transmissividade[pixels_validos]
    return resultado


def corrigir_albedo_superficie(albedo_toa, tau_sw, albedo_atmosfera=0.03):
    """Correcao atmosferica e limites do modelo_albedo_superficie_srtm.gmd."""
    if not np.isfinite(albedo_atmosfera) or not 0 <= albedo_atmosfera < 1:
        raise ValueError("Albedo atmosferico deve estar entre 0 (inclusive) e 1.")
    albedo, transmissividade = np.broadcast_arrays(
        np.asarray(albedo_toa, dtype="float32"), np.asarray(tau_sw, dtype="float32")
    )
    pixels_validos = np.isfinite(albedo)
    pixels_validos &= np.isfinite(transmissividade)
    pixels_validos &= transmissividade > 0
    pixels_validos &= transmissividade <= 1

    numerador = albedo - albedo_atmosfera
    denominador = transmissividade * transmissividade
    resultado = np.full(albedo.shape, np.nan, dtype="float32")
    resultado[pixels_validos] = numerador[pixels_validos] / denominador[pixels_validos]

    # Reproduz os limites definidos no modelo ERDAS de albedo da superfície.
    abaixo_do_limite = pixels_validos & (resultado <= 0)
    acima_do_limite = pixels_validos & (resultado >= 1)
    resultado[abaixo_do_limite] = 0.00001
    resultado[acima_do_limite] = 1
    return resultado
