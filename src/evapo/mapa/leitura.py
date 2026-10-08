"""Lê só a vista do mapa; a consulta do pixel usa a resolução original."""

import numpy as np
import rasterio
from rasterio.features import geometry_mask, geometry_window
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds

from evapo.calculos.albedo import (
    calcular_albedo_toa,
    calcular_transmissividade,
    corrigir_albedo_superficie,
)
from evapo.dados.area import usar_imagem_inteira
from evapo.calculos.indices import calcular_iaf, calcular_ndvi, calcular_savi
from evapo.calculos.energia import calcular_radiacoes, produtos_termicos_cena
from evapo.calculos.produtos import PRODUTOS
from evapo.calculos.reflectancia import calcular_reflectancias


def ler_janela(cena, janela, tamanho=1100, roi=None, mde=None, temperatura_ar=None,
               produto=None):
    """A vista reduzida serve para navegar; tamanho=None lê pixels nativos."""
    pasta = cena["caminho"].parent
    with rasterio.open(cena["caminho"]) as imagem:
        if imagem.count != 7 or imagem.crs is None:
            raise ValueError("O empilhamento precisa ter sete bandas e CRS definido.")
        janela = janela.intersection(Window(0, 0, imagem.width, imagem.height))
        fator = max(1, max(janela.width, janela.height) / tamanho) if tamanho else 1
        altura = max(1, int(np.ceil(janela.height / fator)))
        largura = max(1, int(np.ceil(janela.width / fator)))
        dn = imagem.read(window=janela, out_shape=(7, altura, largura), masked=True)
        transformacao = imagem.window_transform(janela)
        transformacao = transformacao * transformacao.scale(
            janela.width / largura, janela.height / altura
        )
        crs = imagem.crs
        limites = rasterio.windows.bounds(janela, imagem.transform)
        for nome in ("QA_PIXEL", "QA_RADSAT"):
            with rasterio.open(next(pasta.glob(f"*_{nome}.TIF"))) as arquivo:
                if (
                    arquivo.crs != imagem.crs
                    or arquivo.transform != imagem.transform
                    or arquivo.shape != imagem.shape
                ):
                    raise ValueError("QA não alinhada com o empilhamento.")
                dados = arquivo.read(1, window=janela, out_shape=(altura, largura))
                if nome == "QA_PIXEL":
                    qa = dados
                else:
                    saturacao = dados
    mascara = None
    if not usar_imagem_inteira(roi):
        geometria = transform_geom("EPSG:4326", crs, roi["geometry"])
        mascara = geometry_mask(
            [geometria], (altura, largura), transformacao, invert=True
        )
    reflectancias = calcular_reflectancias(
        dn, qa, saturacao, cena["mtl"], mascara_roi=mascara
    )
    ndvi = calcular_ndvi(reflectancias[4], reflectancias[5])
    savi = calcular_savi(reflectancias[4], reflectancias[5])
    iaf = calcular_iaf(savi)
    iaf[(qa & ((1 << 7) | (1 << 5))) != 0] = np.nan
    rgb = np.stack([reflectancias[b] for b in (4, 3, 2)], axis=-1)
    rgb = np.clip(rgb / 0.3, 0, 1) ** 0.8
    rgb[~np.isfinite(rgb).all(axis=-1)] = [0.90, 0.91, 0.92]
    produtos = {
        "RGB": rgb,
        "NDVI": ndvi,
        "SAVI": savi,
        "IAF": iaf,
        "Albedo TOA": calcular_albedo_toa(reflectancias),
    }
    # A navegação nos índices ópticos não depende de B10 nem de elevação.
    # Consultas e processamento continuam recebendo todos os produtos por padrão.
    if produto in produtos:
        return produtos, limites, qa, saturacao
    adicionais = produtos_termicos_cena(cena, ndvi, qa, saturacao, crs, transformacao, mascara)
    if mde:
        with rasterio.open(mde) as modelo:
            if modelo.count != 1 or modelo.crs is None:
                raise ValueError("O MDE deve ter uma banda em metros e CRS definido.")
        with (
            rasterio.open(mde) as origem,
            WarpedVRT(
                origem,
                crs=crs,
                transform=transformacao,
                width=largura,
                height=altura,
                dtype="float32",
                nodata=np.nan,
            ) as vrt,
        ):
            altitude = (
                vrt.read(1, masked=True).filled(np.nan) * origem.scales[0]
                + origem.offsets[0]
            )
            tau = calcular_transmissividade(altitude)
            cobertura_cena = (~np.ma.getmaskarray(dn) & (dn.data != 0)).any(axis=0)
            tau[~cobertura_cena] = np.nan
            tau[((qa & 31) != 0) | ((saturacao & (1 << 11)) != 0)] = np.nan
            if mascara is not None:
                tau[~mascara] = np.nan
            adicionais["transmissividade"] = tau
            produtos["Albedo superfície"] = corrigir_albedo_superficie(
                produtos["Albedo TOA"], tau
            )
            adicionais.update(calcular_radiacoes(
                tau, cena["mtl"], temperatura_ar, adicionais["emissividade"],
                adicionais.get("temperatura_superficie"), produtos["Albedo superfície"],
            ))
    produtos.update({PRODUTOS[nome][0]: dados for nome, dados in adicionais.items()})
    return produtos, limites, qa, saturacao


def ler_vista(cena, limites=None, roi=None, mde=None, tamanho=1100, temperatura_ar=None,
              produto=None):
    with rasterio.open(cena["caminho"]) as imagem:
        janela = Window(0, 0, imagem.width, imagem.height)
        if limites is not None:
            esquerda, inferior, direita, superior = limites
            recorte = from_bounds(
                esquerda, inferior, direita, superior, imagem.transform
            )
            coluna, linha = (
                int(np.floor(recorte.col_off)),
                int(np.floor(recorte.row_off)),
            )
            largura = max(1, int(np.ceil(recorte.col_off + recorte.width)) - coluna)
            altura = max(1, int(np.ceil(recorte.row_off + recorte.height)) - linha)
            janela = Window(coluna, linha, largura, altura)
    return ler_janela(cena, janela, tamanho=tamanho, roi=roi, mde=mde,
                     temperatura_ar=temperatura_ar, produto=produto)


def consultar_pixel(cena, x, y, roi=None, mde=None, temperatura_ar=None):
    with rasterio.open(cena["caminho"]) as imagem:
        linha, coluna = imagem.index(x, y)
        if not (0 <= linha < imagem.height and 0 <= coluna < imagem.width):
            return None
    produtos, _limites, qa, saturacao = ler_janela(
        cena, Window(coluna, linha, 1, 1), tamanho=None, roi=roi, mde=mde, temperatura_ar=temperatura_ar
    )
    return {
        "linha": linha,
        "coluna": coluna,
        "qa": int(qa[0, 0]),
        "saturacao": int(saturacao[0, 0]),
        "valores": {
            nome: float(dados[0, 0])
            for nome, dados in produtos.items()
            if nome != "RGB"
        },
    }


def localizar_extremo(cena, produto, minimo=True, roi=None, mde=None, temperatura_ar=None):
    """Procura o extremo em todos os pixels nativos, em blocos de pouca memória."""
    melhor = None
    with rasterio.open(cena["caminho"]) as imagem:
        area = Window(0, 0, imagem.width, imagem.height)
        if not usar_imagem_inteira(roi):
            geometria = transform_geom("EPSG:4326", imagem.crs, roi["geometry"])
            area = geometry_window(imagem, [geometria]).intersection(area)
        linha_final = int(area.row_off + area.height)
        coluna_final = int(area.col_off + area.width)
        for linha in range(int(area.row_off), linha_final, 512):
            for coluna in range(int(area.col_off), coluna_final, 512):
                janela = Window(
                    coluna,
                    linha,
                    min(512, coluna_final - coluna),
                    min(512, linha_final - linha),
                )
                produtos, _, _, _ = ler_janela(
                    cena, janela, tamanho=None, roi=roi, mde=mde, temperatura_ar=temperatura_ar
                )
                if produto not in produtos:
                    raise ValueError("Produto indisponível: confira B10, MDE e temperatura do ar.")
                dados = produtos[produto]
                if not np.isfinite(dados).any():
                    continue
                indice = np.nanargmin(dados) if minimo else np.nanargmax(dados)
                r, c = np.unravel_index(indice, dados.shape)
                valor = float(dados[r, c])
                if melhor is None or (
                    valor < melhor[2] if minimo else valor > melhor[2]
                ):
                    x, y = imagem.xy(linha + r, coluna + c)
                    melhor = (x, y, valor)
    if melhor is None:
        raise ValueError("Não há pixels válidos nessa área/produto.")
    return melhor
