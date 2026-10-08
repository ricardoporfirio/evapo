"""Modelos térmicos e radiativos das aulas 5/6, com unidades físicas explícitas.

Usa o modelo condicional executável de emissividade da Aula 6, página 5.
A correção térmica usa Kelvin e lambda em metros; somente o resultado Ts
é convertido para Celsius. Não reproduz os erros de unidade da página 9.
"""

from pathlib import Path

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT

SIGMA = 5.67e-8  # W m-2 K-4
LAMBDA_B10 = 10.895e-6  # metros, valor adotado nas aulas
RHO = 1.438e-2  # m K


def validar_temperatura_ar(valor):
    if valor is None or str(valor).strip() == "":
        return None
    try:
        temperatura = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("Informe a temperatura do ar em °C ou deixe o campo vazio.") from None
    if not np.isfinite(temperatura) or temperatura <= -273.15:
        raise ValueError("A temperatura do ar deve ser finita e maior que -273,15 °C.")
    return temperatura


def calcular_emissividade(ndvi):
    ndvi = np.asarray(ndvi, dtype="float32")
    valido = np.isfinite(ndvi) & (ndvi >= -1) & (ndvi <= 1)
    pv = np.clip((ndvi - 0.2) / 0.3, 0, 1) ** 2
    emissividade = np.where(
        ndvi < 0.2, 0.966,
        np.where(ndvi > 0.5, 0.978, 0.973 * pv + 0.966 * (1 - pv) + 0.005),
    )
    return np.where(valido, pv, np.nan), np.where(valido, emissividade, np.nan)


def calcular_termicos(dn, mtl, emissividade):
    coef = mtl["LEVEL1_RADIOMETRIC_RESCALING"]
    constantes = mtl["LEVEL1_THERMAL_CONSTANTS"]
    mult = float(coef["RADIANCE_MULT_BAND_10"])
    aditivo = float(coef["RADIANCE_ADD_BAND_10"])
    k1 = float(constantes["K1_CONSTANT_BAND_10"])
    k2 = float(constantes["K2_CONSTANT_BAND_10"])
    if not all(np.isfinite(v) for v in (mult, aditivo, k1, k2)) or min(mult, k1, k2) <= 0:
        raise ValueError("Coeficientes térmicos B10 inválidos no MTL.")
    dn = np.ma.asarray(dn, dtype="float64").filled(np.nan)
    radiancia = mult * dn + aditivo
    radiancia = np.where((dn > 0) & np.isfinite(dn) & (radiancia > 0), radiancia, np.nan)
    brilho_kelvin = k2 / np.log1p(k1 / radiancia)
    emissividade = np.asarray(emissividade, dtype="float64")
    emissividade = np.where((emissividade > 0) & (emissividade <= 1), emissividade, np.nan)
    denominador = 1 + (LAMBDA_B10 * brilho_kelvin / RHO) * np.log(emissividade)
    ts_kelvin = np.divide(
        brilho_kelvin, denominador,
        out=np.full_like(brilho_kelvin, np.nan), where=denominador > 0,
    )
    return {
        "radiancia_b10": radiancia.astype("float32"),
        "temperatura_brilho": brilho_kelvin.astype("float32"),
        "temperatura_superficie": (ts_kelvin - 273.15).astype("float32"),
        "radiacao_longa_emitida": (emissividade * SIGMA * ts_kelvin**4).astype("float32"),
    }


def calcular_radiacoes(tau, mtl, temperatura_ar=None, emissividade=None,
                       temperatura_superficie=None, albedo_superficie=None):
    tau = np.asarray(tau, dtype="float64")
    tau = np.where(np.isfinite(tau) & (tau > 0) & (tau <= 1), tau, np.nan)
    atributos = mtl["IMAGE_ATTRIBUTES"]
    elevacao = float(atributos["SUN_ELEVATION"])
    distancia = float(atributos["EARTH_SUN_DISTANCE"])
    if not np.isfinite(elevacao) or not 0 < elevacao <= 90:
        raise ValueError("Elevação solar inválida no MTL.")
    if not np.isfinite(distancia) or distancia <= 0:
        raise ValueError("Distância Terra–Sol inválida no MTL.")
    # dr = 1/d²: a distância Terra–Sol no MTL está em unidades astronômicas.
    curta = 1367 * np.sin(np.deg2rad(elevacao)) / distancia**2 * tau
    emissividade_ar = 0.85 * (-np.log(tau)) ** 0.09
    produtos = {"radiacao_curta_incidente": curta, "emissividade_atmosferica": emissividade_ar}
    temperatura_ar = validar_temperatura_ar(temperatura_ar)
    if temperatura_ar is not None:
        longa = emissividade_ar * SIGMA * (temperatura_ar + 273.15)**4
        produtos["radiacao_longa_incidente"] = longa
        if all(v is not None for v in (emissividade, temperatura_superficie, albedo_superficie)):
            emissividade = np.asarray(emissividade, dtype="float64")
            temperatura_superficie = np.asarray(temperatura_superficie, dtype="float64")
            albedo_superficie = np.asarray(albedo_superficie, dtype="float64")
            emitida = emissividade * SIGMA * (temperatura_superficie + 273.15)**4
            produtos["saldo_radiacao"] = (
                (1 - albedo_superficie) * curta + longa - emitida - (1 - emissividade) * longa
            )
    return {nome: np.asarray(dados, dtype="float32") for nome, dados in produtos.items()}


def ler_raster_alinhado(caminho, crs, transformacao, forma):
    """Lê B10 ou MDE na grade solicitada; NoData e áreas descobertas viram NaN."""
    with rasterio.open(caminho) as origem:
        if origem.count != 1 or origem.crs is None:
            raise ValueError(f"Raster deve ter uma banda e CRS definido: {caminho}")
        with WarpedVRT(origem, crs=crs, transform=transformacao,
                       width=forma[1], height=forma[0], dtype="float32", nodata=np.nan) as vrt:
            dados = vrt.read(1, masked=True).filled(np.nan)
        return dados * origem.scales[0] + origem.offsets[0]


def produtos_termicos_cena(cena, ndvi, qa, saturacao, crs, transformacao, mascara=None):
    pv, emissividade = calcular_emissividade(ndvi)
    produtos = {"proporcao_vegetacao": pv, "emissividade": emissividade}
    bandas = sorted(p for p in Path(cena["caminho"]).parent.iterdir()
                    if p.name.upper().endswith("_B10.TIF"))
    if not bandas:
        return produtos
    dn = ler_raster_alinhado(bandas[0], crs, transformacao, ndvi.shape)
    # QA_RADSAT de Landsat 8/9 não contém bit de saturação da B10.
    # Não reutilizar os bits das bandas ópticas para o sensor térmico.
    valido = ((qa & 31) == 0) & ((saturacao & (1 << 11)) == 0)
    if mascara is not None:
        valido &= mascara
    dn[~valido] = np.nan
    try:
        produtos.update(calcular_termicos(dn, cena["mtl"], emissividade))
    except KeyError as erro:
        raise ValueError(f"Metadado térmico ausente no MTL: {erro.args[0]}") from erro
    return produtos


def pendencias_energia(produtos):
    pendencias = []
    if "temperatura_superficie" not in produtos:
        pendencias.append("Banda B10 ausente: temperatura e onda longa emitida pendentes.")
    if "albedo_superficie" not in produtos:
        pendencias.append("MDE ausente: albedo da superfície, transmissividade e radiações dependentes de altitude pendentes.")
    if "radiacao_longa_incidente" not in produtos:
        pendencias.append("Onda longa incidente exige MDE e temperatura do ar informada.")
    if "saldo_radiacao" not in produtos:
        pendencias.append("Saldo de radiação exige B10, MDE e temperatura do ar informada.")
    return pendencias
