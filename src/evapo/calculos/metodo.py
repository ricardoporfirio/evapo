"""Identifica a metodologia usada em cada nova execução, sem alterar antigas."""

from evapo.calculos.albedo import PESOS_ALBEDO_TOA
from evapo.calculos.indices import L_IAF
from evapo.calculos.aceleracao import informacoes_aceleracao


def parametros_metodo():
    return {
        "metodologia_versao": 2,
        "aceleracao": informacoes_aceleracao(inicializar=False),
        "L_iaf": L_IAF,
        "modelo_albedo": "Silva et al. (2016), tabela 5; reflectâncias TOA B2–B7",
        "pesos_albedo_toa": {str(b): p for b, p in PESOS_ALBEDO_TOA.items()},
        "modelos_energia": "Emissividades SEBAL espectral/larga; água por QA; neve excluída; Ts em Kelvin e lambda em metros; sem correção atmosférica térmica completa",
        "modelo_solar": "d em UA do MTL; conferência/fallback na planilha; dr=1/d² apenas na irradiância",
    }
