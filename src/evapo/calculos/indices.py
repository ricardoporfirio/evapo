"""Calcula NDVI, SAVI e IAF a partir das reflectancias RED e NIR."""

import numpy as np


def calcular_ndvi(vermelho, infravermelho):
    """NDVI = (NIR - RED) / (NIR + RED); entradas em reflectancia."""
    vermelho = np.asarray(vermelho, dtype="float32")
    infravermelho = np.asarray(infravermelho, dtype="float32")
    denominador = infravermelho + vermelho
    pixels_validos = np.isfinite(vermelho)
    pixels_validos &= np.isfinite(infravermelho)
    pixels_validos &= vermelho >= 0
    pixels_validos &= infravermelho >= 0
    # Evita dividir por zero ou por um número muito próximo de zero.
    pixels_validos &= denominador > 1e-8
    numerador = infravermelho - vermelho
    resultado = np.full(denominador.shape, np.nan, dtype="float32")
    resultado[pixels_validos] = numerador[pixels_validos] / denominador[pixels_validos]
    return resultado


def calcular_savi(vermelho, infravermelho, L=0.5):
    """SAVI = (1 + L) * (NIR - RED) / (NIR + RED + L)."""
    if not np.isfinite(L) or not 0 <= L <= 1:
        raise ValueError("L deve estar entre 0 e 1.")
    vermelho = np.asarray(vermelho, dtype="float32")
    infravermelho = np.asarray(infravermelho, dtype="float32")
    denominador = infravermelho + vermelho + L
    pixels_validos = np.isfinite(vermelho)
    pixels_validos &= np.isfinite(infravermelho)
    pixels_validos &= vermelho >= 0
    pixels_validos &= infravermelho >= 0
    pixels_validos &= denominador > 1e-8
    numerador = (1 + L) * (infravermelho - vermelho)
    resultado = np.full(denominador.shape, np.nan, dtype="float32")
    resultado[pixels_validos] = numerador[pixels_validos] / denominador[pixels_validos]
    fora_do_intervalo = (resultado < -1) | (resultado > 1)
    resultado[fora_do_intervalo] = np.nan
    return resultado


def calcular_iaf(savi):
    """IAF empirico SEBAL (m2/m2): zero em SAVI <= 0.1 e 6 em SAVI >= 0.687."""
    savi = np.asarray(savi, dtype="float32")
    resultado = np.full(savi.shape, np.nan, dtype="float32")
    pixels_validos = np.isfinite(savi)
    pixels_validos &= savi >= -1
    pixels_validos &= savi <= 1

    pouca_vegetacao = pixels_validos & (savi <= 0.1)
    vegetacao_no_limite = pixels_validos & (savi >= 0.687)
    calcular_pela_formula = pixels_validos & (savi > 0.1) & (savi < 0.687)

    resultado[pouca_vegetacao] = 0
    resultado[vegetacao_no_limite] = 6
    # Calcula o logaritmo apenas onde seu argumento é positivo.
    argumento_logaritmo = (0.69 - savi[calcular_pela_formula]) / 0.59
    resultado[calcular_pela_formula] = -np.log(argumento_logaritmo) / 0.91
    return np.clip(resultado, 0, 6)
