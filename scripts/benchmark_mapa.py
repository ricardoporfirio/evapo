"""Mede leitura e desenho com cenas reais, sem abrir ou alterar o projeto."""

import argparse
from pathlib import Path
from statistics import median
from time import perf_counter

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from evapo.mapa.cache_vistas import CacheVistas
from evapo.mapa.leitura import ler_vista
from evapo.dados.metadados import descobrir_cenas


def medir(funcao, repeticoes):
    tempos = []
    for _ in range(repeticoes):
        inicio = perf_counter()
        resultado = funcao()
        tempos.append(perf_counter() - inicio)
    return median(tempos), resultado


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", type=Path, default=Path("entrada"))
    parser.add_argument("--repeticoes", type=int, default=3)
    args = parser.parse_args()
    if args.repeticoes < 1:
        parser.error("--repeticoes deve ser positivo")
    cena = descobrir_cenas(args.entrada)[0]
    print(f"Cena: {cena['data']} / {cena['caminho'].name}")
    completo, anterior = medir(lambda: ler_vista(cena, tamanho=1200), args.repeticoes)
    optico, resultado = medir(lambda: ler_vista(cena, tamanho=1200, produto="NDVI"), args.repeticoes)
    np.testing.assert_array_equal(anterior[0]["NDVI"], resultado[0]["NDVI"])
    print(f"Leitura completa: {completo * 1000:.1f} ms; optica: {optico * 1000:.1f} ms")
    figura = Figure(figsize=(9, 7))
    canvas = FigureCanvasAgg(figura)
    eixo = figura.add_axes([0.08, 0.12, 0.76, 0.80])
    a, b, c, d = resultado[1]
    camada = eixo.imshow(resultado[0]["NDVI"], extent=(a, c, b, d), interpolation="nearest")
    for etapa in ("auto", "data"):
        camada.set_interpolation_stage(etapa)
        canvas.draw()
        inicio = perf_counter()
        for i in range(20):
            eixo.set_xlim(a + i * 3000, c + i * 3000)
            canvas.draw()
        print(f"Desenho ({etapa}): {(perf_counter() - inicio) * 1000 / 20:.1f} ms/quadro")
    cache = CacheVistas()
    cache.guardar("cena", resultado)
    resolucao = max((c - a) / resultado[0]["NDVI"].shape[1],
                    (d - b) / resultado[0]["NDVI"].shape[0])
    tempo, reutilizado = medir(lambda: cache.buscar("cena", (a, b, c, d), resolucao, "NDVI"), 100)
    assert reutilizado is resultado
    print(f"Consulta ao cache: {tempo * 1000:.3f} ms")
    print("NDVI identico entre a leitura completa e a leitura optica.")


if __name__ == "__main__":
    main()
