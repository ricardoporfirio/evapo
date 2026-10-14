"""Nomes, unidades e escalas de apresentação dos produtos calculados."""

# Os intervalos controlam apenas figuras/histogramas, nunca recortam os dados.
PRODUTOS = {
    "albedo_toa": ("Albedo TOA", (0, 1), "gray", "adimensional"),
    "ndvi": ("NDVI", (-1, 1), "RdYlGn", "adimensional"),
    "savi": ("SAVI", (-1, 1), "RdYlGn", "adimensional"),
    "iaf": ("IAF", (0, 6), "YlGn", "m²/m²"),
    "albedo_superficie": ("Albedo superfície", (0, 1), "gray", "adimensional"),
    "proporcao_vegetacao": ("Proporção de vegetação", (0, 1), "YlGn", "adimensional"),
    "emissividade": ("Emissividade superfície", (0.95, 1), "viridis", "adimensional"),
    "emissividade_b10": ("Emissividade B10", (0.97, 1), "viridis", "adimensional"),
    "radiancia_b10": ("Radiância B10", (0, 20), "inferno", "W/m²/sr/µm"),
    "temperatura_brilho": ("Temperatura de brilho", (250, 330), "inferno", "K"),
    "temperatura_superficie": ("Temperatura superfície", (-20, 60), "inferno", "°C"),
    "transmissividade": ("Transmissividade", (0.7, 1), "viridis", "adimensional"),
    "emissividade_atmosferica": ("Emissividade atmosfera", (0, 1), "viridis", "adimensional"),
    "radiacao_curta_incidente": ("Onda curta incidente", (0, 1200), "inferno", "W/m²"),
    "radiacao_longa_emitida": ("Onda longa emitida", (0, 700), "inferno", "W/m²"),
    "radiacao_longa_incidente": ("Onda longa incidente", (0, 700), "inferno", "W/m²"),
    "saldo_radiacao": ("Saldo de radiação", (-200, 1000), "RdYlBu_r", "W/m²"),
}

DEPENDENCIAS_MDE = {
    "albedo_superficie", "transmissividade", "emissividade_atmosferica",
    "radiacao_curta_incidente", "radiacao_longa_incidente", "saldo_radiacao",
}
DEPENDENCIAS_AR = {"radiacao_longa_incidente", "saldo_radiacao"}


def unidade_produto(nome):
    return PRODUTOS.get(nome, (None, None, None, "adimensional"))[3]
