"""Separa o vigor somente dentro da pastagem, sem classificar pixels ausentes."""

import numpy as np

CLASSES_VIGOR = {
    1: ("baixo", "Baixo vigor", "#fa6970"),
    2: ("moderado", "Vigor moderado", "#f7b47e"),
    3: ("alto", "Alto vigor", "#44b160"),
}


def classificar_vigor(pastagem, valores, limites_ndvi=None):
    """0: fora da pastagem; 4: pastagem sem classe; 1/2/3: vigor conhecido."""
    if pastagem.shape != valores.shape:
        raise ValueError("Pastagem e vigor precisam ter a mesma grade.")
    classes = np.zeros(pastagem.shape, dtype="uint8")
    classes[pastagem] = 4
    if limites_ndvi is None:
        # Códigos oficiais do produto Condição de Vigor do MapBiomas.
        for codigo in CLASSES_VIGOR:
            pixels_da_classe = pastagem & (valores == codigo)
            classes[pixels_da_classe] = codigo
    else:
        limite_baixo, limite_alto = limites_ndvi
        if not -1 < limite_baixo < limite_alto < 1:
            raise ValueError(
                "Os limites de NDVI devem satisfazer -1 < baixo < alto < 1."
            )
        ndvi_valido = np.isfinite(valores) & (valores >= -1) & (valores <= 1)
        pixels_classificaveis = pastagem & ndvi_valido
        baixo = pixels_classificaveis & (valores < limite_baixo)
        moderado = (
            pixels_classificaveis & (valores >= limite_baixo) & (valores < limite_alto)
        )
        alto = pixels_classificaveis & (valores >= limite_alto)
        classes[baixo] = 1
        classes[moderado] = 2
        classes[alto] = 3
    return classes
