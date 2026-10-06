"""Distingue ROI desenhada de imagem inteira e delimita a região de download."""

import rasterio
from rasterio.warp import transform_bounds


def usar_imagem_inteira(roi):
    return roi is None or roi.get("properties", {}).get("imagem_inteira") is True


def delimitacao_cenas(cenas):
    """Envelope das cenas selecionadas em WGS84, apenas para obter camadas."""
    limites = []
    for cena in cenas:
        with rasterio.open(cena["caminho"]) as imagem:
            limites.append(transform_bounds(imagem.crs, "EPSG:4326", *imagem.bounds))
    esquerda = min(l[0] for l in limites)
    inferior = min(l[1] for l in limites)
    direita = max(l[2] for l in limites)
    superior = max(l[3] for l in limites)
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [esquerda, inferior],
                    [direita, inferior],
                    [direita, superior],
                    [esquerda, superior],
                    [esquerda, inferior],
                ]
            ],
        },
    }
