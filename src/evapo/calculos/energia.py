"""Balanço radiativo com emissividades espectral e larga distintas.

As emissividades seguem Waters et al. (2002), manual SEBAL, equações 16a/b.
A correção térmica usa Kelvin e lambda em metros, sem correção atmosférica
térmica; somente o resultado Ts é convertido para Celsius.
"""

from pathlib import Path

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT

from evapo.calculos.aceleracao import tentar_calculo_gpu
from evapo.calculos.solar import fator_distancia_terra_sol

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


def calcular_proporcao_vegetacao(ndvi):
    """Pv descritivo com limites convencionais; não determina emissividade."""
    ndvi = np.asarray(ndvi, dtype="float32")
    valido = np.isfinite(ndvi) & (ndvi >= -1) & (ndvi <= 1)
    pv = np.clip((ndvi - 0.2) / 0.3, 0, 1) ** 2
    return np.where(valido, pv, np.nan).astype("float32")


def calcular_emissividades_sebal(ndvi, iaf, qa=None):
    """Retorna (epsilon_B10, epsilon_larga); água por QA e neve sem estimativa.

    Para terreno, exige NDVI > 0 e IAF SEBAL calculado com SAVI L=0,1.
    A água usa 0,99/0,985 (manual SEBAL, p.20). Neve é excluída porque a
    relação SAVI–IAF adotada não é calibrada para ela. Os limiares do Pv
    descritivo não são usados nestas emissividades.
    """
    if iaf is None:
        raise ValueError("Informe o IAF calculado com SAVI L=0,1 para estimar emissividade.")
    ndvi, iaf = np.broadcast_arrays(
        np.asarray(ndvi, dtype="float64"), np.asarray(iaf, dtype="float64"),
    )
    qualidade = np.zeros(ndvi.shape, dtype="uint16") if qa is None else np.broadcast_to(qa, ndvi.shape)
    valido_qa = ((qualidade & 31) == 0) & ((qualidade & (1 << 5)) == 0)
    acelerado = tentar_calculo_gpu(
        "emissividades_sebal", (ndvi, iaf, qualidade), (0,), 2, exige_fp64=True,
    )
    if acelerado is not None:
        return acelerado[0], acelerado[1]
    agua = valido_qa & ((qualidade & (1 << 7)) != 0)
    terreno = (
        valido_qa & ~agua & np.isfinite(ndvi) & (ndvi > 0) & (ndvi <= 1)
        & np.isfinite(iaf) & (iaf >= 0)
    )
    estreita = np.where(terreno, np.where(iaf >= 3, 0.98, 0.97 + 0.0033 * iaf), np.nan)
    larga = np.where(terreno, np.where(iaf >= 3, 0.98, 0.95 + 0.01 * iaf), np.nan)
    return (
        np.where(agua, 0.99, estreita).astype("float32"),
        np.where(agua, 0.985, larga).astype("float32"),
    )


def calcular_emissividade(ndvi, iaf=None, qa=None):
    """Retorno compatível (Pv, epsilon_larga), agora requer IAF explícito."""
    _, larga = calcular_emissividades_sebal(ndvi, iaf, qa)
    return calcular_proporcao_vegetacao(ndvi), larga


def calcular_termicos(dn, mtl, emissividade_b10=None, emissividade=None):
    """B10 corrige Ts; emissividade larga determina a emissão total.

    Chamadas antigas com uma emissividade mantêm o comportamento anterior.
    O processamento das cenas sempre fornece as duas emissividades.
    """
    if emissividade_b10 is None:
        emissividade_b10 = emissividade
    if emissividade_b10 is None:
        raise ValueError("Informe a emissividade espectral da B10 para estimar temperatura.")
    coef = mtl["LEVEL1_RADIOMETRIC_RESCALING"]
    constantes = mtl["LEVEL1_THERMAL_CONSTANTS"]
    mult = float(coef["RADIANCE_MULT_BAND_10"])
    aditivo = float(coef["RADIANCE_ADD_BAND_10"])
    k1 = float(constantes["K1_CONSTANT_BAND_10"])
    k2 = float(constantes["K2_CONSTANT_BAND_10"])
    if not all(np.isfinite(v) for v in (mult, aditivo, k1, k2)) or min(mult, k1, k2) <= 0:
        raise ValueError("Coeficientes térmicos B10 inválidos no MTL.")
    dn = np.ma.asarray(dn, dtype="float64").filled(np.nan)
    if emissividade is None:
        emissividade = emissividade_b10
    emissividade_b10 = np.asarray(emissividade_b10, dtype="float64")
    emissividade = np.asarray(emissividade, dtype="float64")
    entradas_gpu = np.broadcast_arrays(dn, emissividade_b10, emissividade)
    # NumPy preserva a grade do DN; formatos que expandem essa grade seguem CPU.
    if entradas_gpu[0].shape == dn.shape:
        acelerado = tentar_calculo_gpu(
            "termicos", entradas_gpu, (mult, aditivo, k1, k2, LAMBDA_B10, RHO, SIGMA),
            4, exige_fp64=True,
        )
        if acelerado is not None:
            return dict(zip(
                ("radiancia_b10", "temperatura_brilho", "temperatura_superficie", "radiacao_longa_emitida"),
                acelerado,
            ))
    radiancia = mult * dn + aditivo
    radiancia = np.where((dn > 0) & np.isfinite(dn) & (radiancia > 0), radiancia, np.nan)
    brilho_kelvin = k2 / np.log1p(k1 / radiancia)
    emissividade_b10 = np.where(
        np.isfinite(emissividade_b10) & (emissividade_b10 > 0) & (emissividade_b10 <= 1),
        emissividade_b10, np.nan,
    )
    emissividade = np.where(
        np.isfinite(emissividade) & (emissividade > 0) & (emissividade <= 1), emissividade, np.nan,
    )
    denominador = 1 + (LAMBDA_B10 * brilho_kelvin / RHO) * np.log(emissividade_b10)
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
    tau = np.where(np.isfinite(tau) & (tau > 0) & (tau < 1), tau, np.nan)
    atributos = mtl["IMAGE_ATTRIBUTES"]
    elevacao = float(atributos["SUN_ELEVATION"])
    if not np.isfinite(elevacao) or not 0 < elevacao <= 90:
        raise ValueError("Elevação solar inválida no MTL.")
    curta_sem_tau = 1367 * np.sin(np.deg2rad(elevacao)) * fator_distancia_terra_sol(mtl)
    temperatura_ar = validar_temperatura_ar(temperatura_ar)
    tem_ar = temperatura_ar is not None
    tem_saldo = tem_ar and all(v is not None for v in (emissividade, temperatura_superficie, albedo_superficie))
    nomes_gpu = ["radiacao_curta_incidente", "emissividade_atmosferica"]
    if tem_ar:
        nomes_gpu.append("radiacao_longa_incidente")
    if tem_saldo:
        nomes_gpu.append("saldo_radiacao")
    entradas_gpu = np.broadcast_arrays(
        tau, *(
            (np.asarray(emissividade, dtype="float64"),
             np.asarray(temperatura_superficie, dtype="float64"),
             np.asarray(albedo_superficie, dtype="float64"))
            if tem_saldo else (np.asarray(np.nan, dtype="float64"),) * 3
        ),
    )
    if entradas_gpu[0].shape == tau.shape:
        acelerado = tentar_calculo_gpu(
            "radiacoes", entradas_gpu,
            (curta_sem_tau, temperatura_ar + 273.15 if tem_ar else 0, int(tem_ar), int(tem_saldo), SIGMA),
            len(nomes_gpu), exige_fp64=True,
        )
        if acelerado is not None:
            return dict(zip(nomes_gpu, acelerado))
    curta = curta_sem_tau * tau
    emissividade_ar = 0.85 * (-np.log(tau)) ** 0.09
    emissividade_ar = np.where(emissividade_ar <= 1, emissividade_ar, np.nan)
    produtos = {"radiacao_curta_incidente": curta, "emissividade_atmosferica": emissividade_ar}
    if temperatura_ar is not None:
        longa = emissividade_ar * SIGMA * (temperatura_ar + 273.15)**4
        produtos["radiacao_longa_incidente"] = longa
        if all(v is not None for v in (emissividade, temperatura_superficie, albedo_superficie)):
            emissividade = np.asarray(emissividade, dtype="float64")
            temperatura_superficie = np.asarray(temperatura_superficie, dtype="float64")
            albedo_superficie = np.asarray(albedo_superficie, dtype="float64")
            emissividade = np.where(
                np.isfinite(emissividade) & (emissividade > 0) & (emissividade <= 1), emissividade, np.nan,
            )
            temperatura_superficie = np.where(
                np.isfinite(temperatura_superficie) & (temperatura_superficie > -273.15),
                temperatura_superficie, np.nan,
            )
            albedo_superficie = np.where(
                np.isfinite(albedo_superficie) & (albedo_superficie >= 0) & (albedo_superficie <= 1),
                albedo_superficie, np.nan,
            )
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


def produtos_termicos_cena(cena, ndvi, qa, saturacao, crs, transformacao, mascara=None, *, iaf=None):
    pv = calcular_proporcao_vegetacao(ndvi)
    emissividade_b10, emissividade = calcular_emissividades_sebal(ndvi, iaf, qa)
    valido = ((qa & 31) == 0) & ((saturacao & (1 << 11)) == 0)
    if mascara is not None:
        valido &= mascara
    emissividade_b10 = np.where(valido, emissividade_b10, np.nan)
    emissividade = np.where(valido, emissividade, np.nan)
    produtos = {
        "proporcao_vegetacao": np.where(valido, pv, np.nan),
        "emissividade_b10": emissividade_b10,
        "emissividade": emissividade,
    }
    bandas = sorted(p for p in Path(cena["caminho"]).parent.iterdir()
                    if p.name.upper().endswith("_B10.TIF"))
    if not bandas:
        return produtos
    dn = ler_raster_alinhado(bandas[0], crs, transformacao, ndvi.shape)
    # QA_RADSAT de Landsat 8/9 não contém bit de saturação da B10.
    # Não reutilizar os bits das bandas ópticas para o sensor térmico.
    dn[~valido] = np.nan
    try:
        produtos.update(calcular_termicos(dn, cena["mtl"], emissividade_b10, emissividade))
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
