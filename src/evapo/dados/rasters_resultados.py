"""Valores processados persistidos, independentes das entradas e do projeto atual."""

from pathlib import Path
import json

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.windows import Window

CODIGOS = {"baixo": 1, "moderado": 2, "alto": 3}


def salvar_histograma(estatisticas, destino):
    dados = {chave: estatisticas[chave].tolist() for chave in ("bordas", "frequencias")}
    Path(destino).write_text(json.dumps(dados), encoding="utf-8")


def salvar_produtos(produtos, grade, pasta):
    pasta = Path(pasta) / "rasters"
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, dados in produtos.items():
        tipo = np.result_type(dados.dtype, np.float32)
        with rasterio.open(
            pasta / f"{nome}.tif", "w", driver="GTiff", count=1,
            height=dados.shape[0], width=dados.shape[1], dtype=tipo,
            crs=grade["crs"], transform=Affine(*grade["transform"]), nodata=np.nan,
            compress="deflate", predictor=3, tiled=True, BIGTIFF="IF_SAFER",
        ) as destino:
            for _, janela in destino.block_windows(1):
                linhas, colunas = janela.toslices()
                destino.write(dados[linhas, colunas].astype(tipo, copy=False), 1, window=janela)


def caminho_produto(pasta, produto, caminho_mascara=None):
    if produto == "mascara_pastagem":
        return Path(caminho_mascara) if caminho_mascara else Path(pasta) / "classes_vigor.tif"
    return Path(pasta) / "rasters" / f"{produto}.tif"


def validar_grade(origem, camada):
    if origem.shape != camada.shape or origem.crs != camada.crs or not origem.transform.almost_equals(camada.transform):
        raise ValueError("A máscara e o produto não pertencem à mesma grade processada.")


def ler_previa(pasta, produto, vigor=None, tamanho=1000, caminho_mascara=None):
    pasta = Path(pasta)
    with rasterio.open(caminho_produto(pasta, produto, caminho_mascara)) as origem:
        fator = min(1, tamanho / max(origem.shape))
        forma = (max(1, round(origem.height * fator)), max(1, round(origem.width * fator)))
        dados = origem.read(1, out_shape=forma, masked=True, resampling=Resampling.nearest)
        limites = origem.bounds
        crs = str(origem.crs)
        if caminho_mascara and produto != "mascara_pastagem":
            with rasterio.open(caminho_mascara) as mascara:
                validar_grade(origem, mascara)
                valores = mascara.read(1, out_shape=forma, masked=True, resampling=Resampling.nearest)
                dados = np.ma.masked_where(np.ma.getmaskarray(valores) | ~np.isin(valores.data, [1, 2, 3]), dados)
    if vigor:
        with rasterio.open((Path(caminho_mascara).parent if caminho_mascara else pasta) / "classes_vigor.tif") as classes:
            mascara = classes.read(1, out_shape=forma, resampling=Resampling.nearest)
        dados = np.ma.masked_where(mascara != CODIGOS[vigor], dados)
    return dados, limites, crs


def consultar_pixel(pasta, produto, x, y, vigor=None, caminho_mascara=None):
    """Lê a célula nativa; não consulta cores da prévia nem recalcula índices."""
    pasta = Path(pasta)
    with rasterio.open(caminho_produto(pasta, produto, caminho_mascara)) as origem:
        linha, coluna = origem.index(x, y)
        if not (0 <= linha < origem.height and 0 <= coluna < origem.width):
            return None
        centro = origem.xy(linha, coluna)
        crs = str(origem.crs)
        if caminho_mascara:
            with rasterio.open(caminho_mascara) as mascara:
                validar_grade(origem, mascara)
    janela = Window(coluna, linha, 1, 1)
    if vigor:
        with rasterio.open((Path(caminho_mascara).parent if caminho_mascara else pasta) / "classes_vigor.tif") as classes:
            if classes.read(1, window=janela)[0, 0] != CODIGOS[vigor]:
                return None
    valores = {}
    if caminho_mascara or produto == "mascara_pastagem":
        with rasterio.open(caminho_produto(pasta, "mascara_pastagem", caminho_mascara)) as mascara:
            valor = mascara.read(1, window=janela, masked=True)[0, 0]
            valores["mascara_pastagem"] = None if np.ma.is_masked(valor) else int(valor)
        if produto != "mascara_pastagem" and valores["mascara_pastagem"] not in (1, 2, 3):
            return None
    for caminho in sorted((pasta / "rasters").glob("*.tif")):
        with rasterio.open(caminho) as origem:
            valor = origem.read(1, window=janela, masked=True)[0, 0]
            valores[caminho.stem] = None if np.ma.is_masked(valor) or not np.isfinite(valor) else float(valor)
    return {"linha": linha, "coluna": coluna, "centro": centro, "crs": crs, "valores": valores}


def histograma_produto(pasta, produto, intervalo, vigor=None, caminho_mascara=None):
    """Conta todos os pixels nativos do escopo exibido, sem usar a prévia."""
    from contextlib import ExitStack

    frequencias = np.zeros(5 if produto == "mascara_pastagem" else 80, dtype="int64")
    bordas = np.arange(-0.5, 5.5) if produto == "mascara_pastagem" else np.linspace(*intervalo, 81)
    quantidade, soma = 0, 0.0
    with ExitStack() as arquivos:
        origem = arquivos.enter_context(rasterio.open(caminho_produto(pasta, produto, caminho_mascara)))
        mascara = None
        classes = None
        if caminho_mascara and produto != "mascara_pastagem":
            mascara = arquivos.enter_context(rasterio.open(caminho_mascara))
            validar_grade(origem, mascara)
        if vigor:
            classes = arquivos.enter_context(rasterio.open((Path(caminho_mascara).parent if caminho_mascara else Path(pasta)) / "classes_vigor.tif"))
            validar_grade(origem, classes)
        for _, janela in origem.block_windows(1):
            dados = origem.read(1, window=janela, masked=True)
            valido = ~np.ma.getmaskarray(dados) & np.isfinite(dados.data)
            if mascara:
                valores = mascara.read(1, window=janela, masked=True)
                valido &= ~np.ma.getmaskarray(valores) & np.isin(valores.data, [1, 2, 3])
            if classes:
                valido &= classes.read(1, window=janela) == CODIGOS[vigor]
            valores = dados.data[valido]
            frequencias += np.histogram(valores, bordas)[0]
            quantidade += valores.size
            soma += valores.sum(dtype="float64")
    return {"bordas": bordas.tolist(), "frequencias": frequencias.tolist(),
            "media": soma / quantidade if quantidade else None, "pixels_validos": quantidade}
