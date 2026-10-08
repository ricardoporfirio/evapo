"""Lê máscaras de pastagem e mapas de vigor na grade de cada cena Landsat."""

import json
from pathlib import Path

import numpy as np
import rasterio
import shapefile
from affine import Affine
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, is_valid_geom, shapes
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom


def ler_classes_raster(caminho, grade, tamanho):
    """Vizinho mais próximo conserva códigos; NoData nunca vira uma classe."""
    with rasterio.open(caminho) as origem:
        if origem.count != 1 or origem.crs is None:
            raise ValueError("A camada deve ter uma banda e CRS. Exporte um único ano.")
        with WarpedVRT(
            origem,
            crs=grade["crs"],
            transform=Affine(*grade["transform"]),
            width=tamanho[1],
            height=tamanho[0],
            resampling=Resampling.nearest,
            dtype="float32",
            nodata=np.nan,
        ) as alinhada:
            dados = alinhada.read(1, masked=True).filled(np.nan)
    return dados


def ler_poligonos(caminho):
    """GeoJSON usa WGS84; shapefile exige o arquivo .prj ao lado do .shp."""
    caminho = Path(caminho)
    if caminho.suffix.lower() == ".shp":
        arquivo_crs = caminho.with_suffix(".prj")
        if not arquivo_crs.is_file():
            raise ValueError(
                "O shapefile precisa do arquivo .prj para identificar o CRS."
            )
        crs = rasterio.CRS.from_wkt(arquivo_crs.read_text(encoding="utf-8"))
        with shapefile.Reader(str(caminho)) as camada:
            geometrias = [forma.__geo_interface__ for forma in camada.iterShapes()]
    else:
        documento = json.loads(caminho.read_text(encoding="utf-8"))
        if documento.get("crs"):
            raise ValueError("Converta o GeoJSON para WGS84 (EPSG:4326).")
        crs = rasterio.CRS.from_epsg(4326)
        if documento.get("type") == "FeatureCollection":
            geometrias = [feicao["geometry"] for feicao in documento["features"]]
        elif documento.get("type") == "Feature":
            geometrias = [documento["geometry"]]
        else:
            geometrias = [documento]
    for geometria in geometrias:
        if not is_valid_geom(geometria) or geometria["type"] not in (
            "Polygon",
            "MultiPolygon",
        ):
            raise ValueError(
                "A camada de pastagem deve conter apenas polígonos válidos."
            )
    return geometrias, crs


def ler_mascara_pastagem(caminho, grade, mascara_roi, codigo=15):
    """Vetores devem conter somente pastagens; raster usa o código informado."""
    caminho = Path(caminho)
    if caminho.suffix.lower() in (".shp", ".geojson", ".json"):
        originais, crs = ler_poligonos(caminho)
        geometrias = [
            transform_geom(crs, grade["crs"], geometria) for geometria in originais
        ]
        if not geometrias:
            return np.zeros_like(mascara_roi), mascara_roi.copy()
        mascara = geometry_mask(
            geometrias,
            mascara_roi.shape,
            Affine(*grade["transform"]),
            invert=True,
            all_touched=False,
        )
        return mascara & mascara_roi, mascara_roi.copy()
    dados = ler_classes_raster(caminho, grade, mascara_roi.shape)
    cobertura_conhecida = mascara_roi & np.isfinite(dados)
    return cobertura_conhecida & (dados == codigo), cobertura_conhecida


def salvar_raster_classes(dados, grade, destino):
    """255 é NoData; zero identifica área conhecida fora da classe analisada."""
    with rasterio.open(
        destino,
        "w",
        driver="GTiff",
        width=dados.shape[1],
        height=dados.shape[0],
        count=1,
        dtype="uint8",
        crs=grade["crs"],
        transform=Affine(*grade["transform"]),
        nodata=255,
        compress="deflate",
    ) as arquivo:
        arquivo.write(dados.astype("uint8"), 1)


def exportar_poligonos(mascara, grade, destino, propriedades=None):
    """Polygoniza pixels selecionados, conservando buracos, em GeoJSON ou SHP."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    propriedades = propriedades or {"classe": 15}
    # GeoJSON em WGS84 também é aceito pelo seletor e por outros programas SIG.
    feicoes = []
    for geometria, valor in shapes(
        mascara.astype("uint8"),
        mask=mascara,
        transform=Affine(*grade["transform"]),
        connectivity=4,
    ):
        feicoes.append(
            {
                "type": "Feature",
                "geometry": transform_geom(grade["crs"], "EPSG:4326", geometria),
                "properties": propriedades,
            }
        )
    if destino.suffix.lower() == ".shp":
        with shapefile.Writer(
            str(destino), shapeType=shapefile.POLYGON, encoding="utf-8"
        ) as arquivo:
            for chave, valor in propriedades.items():
                arquivo.field(chave, "N" if isinstance(valor, int) else "C")
            for feicao in feicoes:
                arquivo.shape(feicao["geometry"])
                arquivo.record(*propriedades.values())
        destino.with_suffix(".prj").write_text(
            rasterio.CRS.from_epsg(4326).to_wkt(), encoding="utf-8"
        )
        destino.with_suffix(".cpg").write_text("UTF-8", encoding="utf-8")
    else:
        destino.write_text(
            json.dumps(
                {"type": "FeatureCollection", "features": feicoes}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
