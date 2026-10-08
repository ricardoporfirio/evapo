"""Baixa somente a região da ROI dos GeoTIFFs públicos do MapBiomas."""

import hashlib
import json
from pathlib import Path

import rasterio
from rasterio.features import geometry_mask, geometry_window
from rasterio.warp import transform_geom

URL_COBERTURA = (
    "https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/"
    "collection11/lulc/coverage/brazil_coverage/brazil_coverage-col11_{ano}.tif"
)
URL_VIGOR = (
    "https://storage.googleapis.com/mapbiomas-public/initiatives/brazil/lulc/"
    "collection_11/pasture_vigor/pasture_vigor-brazil_classification_{ano}.tif"
)
FONTE = "https://brasil.mapbiomas.org/downloads/mapas-para-download-geotiff/"


def baixar_recorte(url, roi, destino, ano):
    """Leitura HTTP por blocos evita baixar o mapa do Brasil inteiro."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.is_file():
        with rasterio.open(destino) as existente:
            if existente.tags().get("url_origem") == url:
                return destino
        raise ValueError(f"Recorte existente sem origem correspondente: {destino}")
    temporario = destino.with_suffix(".tmp.tif")
    try:
        with (
            rasterio.Env(
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                GDAL_HTTP_TIMEOUT="30",
            ),
            rasterio.open(url) as origem,
        ):
            geometria = transform_geom("EPSG:4326", origem.crs, roi["geometry"])
            janela = geometry_window(origem, [geometria])
            dados = origem.read(1, window=janela, masked=True).filled(255)
            transformacao = origem.window_transform(janela)
            dentro_roi = geometry_mask(
                [geometria],
                dados.shape,
                transformacao,
                invert=True,
            )
            dados[~dentro_roi] = 255
            with rasterio.open(
                temporario,
                "w",
                driver="GTiff",
                count=1,
                dtype="uint8",
                width=dados.shape[1],
                height=dados.shape[0],
                crs=origem.crs,
                transform=transformacao,
                nodata=255,
                compress="deflate",
            ) as arquivo:
                arquivo.write(dados, 1)
                arquivo.update_tags(
                    fonte="MapBiomas Brasil",
                    colecao="11",
                    ano=str(ano),
                    url_origem=url,
                    roi=json.dumps(roi["geometry"]),
                )
        temporario.replace(destino)
    except Exception:
        temporario.unlink(missing_ok=True)
        raise
    return destino


def obter_mapbiomas(roi, ano, pasta="entrada/mapbiomas"):
    if not 2000 <= ano <= 2025:
        raise ValueError(
            "A Coleção 11 de vigor consultada oferece os anos 2000 a 2025."
        )
    geometria = json.dumps(roi["geometry"], sort_keys=True).encode()
    identificador = hashlib.sha256(geometria).hexdigest()[:12]
    pasta = Path(pasta) / f"colecao11_{ano}_{identificador}"
    caminhos = []
    for nome, modelo_url in (("cobertura", URL_COBERTURA), ("vigor", URL_VIGOR)):
        print(f"Obtendo MapBiomas {ano}: {nome} na ROI...", flush=True)
        caminhos.append(
            baixar_recorte(modelo_url.format(ano=ano), roi, pasta / f"{nome}.tif", ano)
        )
    (pasta / "fonte.json").write_text(
        json.dumps(
            {
                "fonte": FONTE,
                "colecao": 11,
                "ano": ano,
                "roi": roi["geometry"],
                "cobertura": URL_COBERTURA.format(ano=ano),
                "vigor": URL_VIGOR.format(ano=ano),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return caminhos
