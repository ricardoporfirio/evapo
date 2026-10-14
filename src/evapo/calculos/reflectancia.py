"""Converte DN em reflectância TOA e aplica as máscaras QA por banda."""

import numpy as np

from evapo.calculos.aceleracao import tentar_calculo_gpu


def converter_reflectancia(dn, banda, mtl):
    """Aplica os coeficientes MTL e a correção pela elevação solar."""
    elevacao_solar_graus = float(mtl["IMAGE_ATTRIBUTES"]["SUN_ELEVATION"])
    elevacao_solar_radianos = np.deg2rad(elevacao_solar_graus)
    seno_elevacao_solar = np.sin(elevacao_solar_radianos)
    if not np.isfinite(seno_elevacao_solar) or seno_elevacao_solar <= 0:
        raise ValueError("Elevação solar inválida nos metadados.")
    coeficientes = mtl["LEVEL1_RADIOMETRIC_RESCALING"]
    fator_multiplicativo = float(coeficientes[f"REFLECTANCE_MULT_BAND_{banda}"])
    termo_aditivo = float(coeficientes[f"REFLECTANCE_ADD_BAND_{banda}"])

    numeros_digitais = np.asarray(dn, dtype="float64")
    reflectancia_sem_correcao = numeros_digitais * fator_multiplicativo + termo_aditivo
    reflectancia_corrigida = reflectancia_sem_correcao / seno_elevacao_solar
    return reflectancia_corrigida.astype("float32")


def calcular_reflectancias(dn, qa, sat, mtl, mascara_roi=None):
    """Retorna B1–B7 com preenchimento, nuvens, sombras e saturação como NaN."""
    if dn.shape[0] != 7 or dn.shape[1:] != qa.shape or qa.shape != sat.shape:
        raise ValueError("DN B1–B7 e QA devem ter a mesma grade.")
    if mascara_roi is not None and mascara_roi.shape != qa.shape:
        raise ValueError("A máscara ROI não está alinhada com DN e QA.")
    elevacao = float(mtl["IMAGE_ATTRIBUTES"]["SUN_ELEVATION"])
    seno = np.sin(np.deg2rad(elevacao))
    if not np.isfinite(seno) or seno <= 0:
        raise ValueError("Elevação solar inválida nos metadados.")
    coef = mtl["LEVEL1_RADIOMETRIC_RESCALING"]
    parametros = [seno]
    for banda in range(1, 8):
        parametros.extend((float(coef[f"REFLECTANCE_MULT_BAND_{banda}"]),
                           float(coef[f"REFLECTANCE_ADD_BAND_{banda}"])))
    numeros_gpu = np.ma.asarray(dn).filled(0)
    area_gpu = np.ones(qa.shape, dtype=bool) if mascara_roi is None else mascara_roi
    gpu = tentar_calculo_gpu(
        "reflectancias", [*numeros_gpu, qa, sat, area_gpu], parametros, 7,
        exige_fp64=True,
    )
    if gpu is not None:
        return {b: gpu[b-1] for b in range(1, 8)}
    # QA_PIXEL: bits 0–4 marcam preenchimento, nuvens, cirrus e sombras.
    sem_nuvens_ou_preenchimento = (qa & 31) == 0
    # QA_RADSAT: bit 11 identifica oclusão do terreno.
    sem_oclusao_do_terreno = (sat & (1 << 11)) == 0
    pixels_da_area = sem_nuvens_ou_preenchimento & sem_oclusao_do_terreno
    if mascara_roi is not None:
        if mascara_roi.shape != qa.shape:
            raise ValueError("A máscara ROI não está alinhada com DN e QA.")
        pixels_da_area &= mascara_roi
    resultado = {}
    for banda in range(1, 8):
        numeros_digitais = np.ma.asarray(dn[banda - 1])
        sem_nodata = ~np.ma.getmaskarray(numeros_digitais)
        numero_digital_presente = numeros_digitais.data != 0
        bit_saturacao_da_banda = 1 << (banda - 1)
        banda_sem_saturacao = (sat & bit_saturacao_da_banda) == 0

        pixels_validos = pixels_da_area.copy()
        pixels_validos &= sem_nodata
        pixels_validos &= numero_digital_presente
        pixels_validos &= banda_sem_saturacao

        reflectancia = converter_reflectancia(numeros_digitais.data, banda, mtl)
        reflectancia[~pixels_validos] = np.nan
        resultado[banda] = reflectancia
    return resultado
