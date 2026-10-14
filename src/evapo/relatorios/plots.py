"""Salva mapas e histogramas individuais sem abrir janelas de figuras."""

import matplotlib.pyplot as plt
import numpy as np

from evapo.calculos.estatisticas import intervalo_dados


def mostrar_mapa(
    dados, titulo, intervalo, cmap="viridis", unidade="adimensional", destino=None
):
    intervalo = intervalo_dados(dados, intervalo)
    fig, ax = plt.subplots(figsize=(8, 8), layout="constrained")
    passo = max(1, int(np.ceil(max(dados.shape[:2]) / 1200)))
    cores = plt.get_cmap(cmap).copy()
    cores.set_bad("#e5e7eb")
    im = ax.imshow(
        dados[::passo, ::passo],
        cmap=cores,
        vmin=intervalo[0],
        vmax=intervalo[1],
        interpolation="nearest",
    )
    ax.set_title(titulo)
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, label=unidade, shrink=0.8)
    if destino:
        fig.savefig(destino, dpi=160)
    plt.close(fig)


def mostrar_histograma(est, titulo, intervalo, unidade="adimensional", destino=None):
    fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
    ax.stairs(est["frequencias"], est["bordas"], fill=True, color="#497eab", alpha=0.8)
    if est["pixels_validos"]:
        ax.axvspan(
            est["q1"],
            est["q3"],
            alpha=0.15,
            color="#ef9b20",
            label="Intervalo interquartil",
        )
        ax.axvline(
            est["media"],
            color="#b22222",
            linestyle="--",
            label=f"Média: {est['media']:.4f}",
        )
        ax.axvline(
            est["mediana"],
            color="#293847",
            linestyle=":",
            label=f"Mediana: {est['mediana']:.4f}",
        )
        ax.legend()
    else:
        ax.text(
            0.5,
            0.5,
            "Sem pixels válidos nesta data / ROI",
            transform=ax.transAxes,
            ha="center",
        )
    ax.set(
        title=f"Histograma — {titulo}",
        xlabel=f"{titulo} ({unidade})",
        ylabel="Número de pixels",
        xlim=(est["bordas"][0], est["bordas"][-1]),
    )
    ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
    ax.grid(axis="y", alpha=0.2)
    if destino:
        fig.savefig(destino, dpi=160)
    plt.close(fig)
