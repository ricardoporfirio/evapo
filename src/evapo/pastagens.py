"""Análise adicional: ROI ∩ pastagem, seguida de estatísticas por vigor e data."""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from affine import Affine
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch

from .area import usar_imagem_inteira
from .camadas import (
    exportar_poligonos,
    ler_classes_raster,
    ler_mascara_pastagem,
    salvar_raster_classes,
)
from .estatisticas import estatisticas_descritivas, exportar_estatisticas
from .plots import mostrar_histograma, mostrar_mapa
from .processamento import calcular_produtos_roi
from .relatorios_pastagens import (
    salvar_relatorio_classe,
    salvar_relatorio_data,
    salvar_relatorio_pastagens,
)
from .vigor import CLASSES_VIGOR, classificar_vigor

PRODUTOS = {
    "albedo_toa": ((0, 1), "gray", "adimensional"),
    "ndvi": ((-1, 1), "RdYlGn", "adimensional"),
    "savi": ((-1, 1), "RdYlGn", "adimensional"),
    "iaf": ((0, 6), "YlGn", "m²/m²"),
    "albedo_superficie": ((0, 1), "gray", "adimensional"),
}


def area_pixel_hectares(grade):
    crs = rasterio.CRS.from_user_input(grade["crs"])
    if not crs.is_projected or crs.linear_units != "metre":
        raise ValueError("A análise de áreas exige uma grade projetada em metros.")
    transformacao = Affine(*grade["transform"])
    area_metros = abs(
        transformacao.a * transformacao.e - transformacao.b * transformacao.d
    )
    return area_metros / 10000


def mostrar_classes(classes, roi, data, destino):
    cores = ["#eeeeee"] + [c[2] for c in CLASSES_VIGOR.values()] + ["#9ca3af"]
    figura, eixo = plt.subplots(figsize=(8, 8), layout="constrained")
    dados = np.ma.array(classes, mask=~roi)
    eixo.imshow(
        dados,
        cmap=ListedColormap(cores),
        norm=BoundaryNorm(np.arange(-0.5, 5.5), 5),
        interpolation="nearest",
    )
    legenda = [Patch(color=cores[0], label="Fora da pastagem / cobertura desconhecida")]
    legenda += [
        Patch(color=cor, label=nome) for chave, nome, cor in CLASSES_VIGOR.values()
    ]
    legenda += [Patch(color=cores[4], label="Pastagem sem classe de vigor")]
    eixo.legend(
        handles=legenda, loc="upper center", bbox_to_anchor=(0.5, 0), fontsize=9
    )
    eixo.set_title(f"Vigor na pastagem — {data}")
    eixo.set_axis_off()
    figura.savefig(destino, dpi=150)
    plt.close(figura)


def processar_pastagens(
    cenas,
    roi,
    caminho_pastagem,
    caminho_vigor=None,
    destino="saida/pastagens",
    codigo_pastagem=15,
    limites_ndvi=None,
    ano_camada=None,
    L=0.5,
    caminho_mde=None,
):
    """Mantém a análise geral intacta; cria sua própria árvore de resultados."""
    if limites_ndvi is None and caminho_vigor is None:
        raise ValueError(
            "Informe o mapa --vigor-pastagens ou os dois --limites-vigor-ndvi."
        )
    # Valida os limites antes de produzir arquivos.
    if limites_ndvi is not None:
        classificar_vigor(np.ones((1, 1), dtype=bool), np.zeros((1, 1)), limites_ndvi)
    configuracao = {
        "area_analise": "imagem inteira" if usar_imagem_inteira(roi) else "ROI",
        "metodo": "NDVI por data"
        if limites_ndvi is not None
        else "classes anuais de vigor",
        "pastagem": str(Path(caminho_pastagem).resolve()),
        "vigor": str(Path(caminho_vigor).resolve()) if caminho_vigor else None,
        "codigo_pastagem_raster": codigo_pastagem,
        "limites_ndvi": list(limites_ndvi) if limites_ndvi is not None else None,
        "ano_camada": ano_camada,
        "L": L,
        "mde": str(caminho_mde) if caminho_mde else None,
        "regra_pixel": "centro do pixel; vizinho mais próximo para camadas categóricas",
        "legenda_raster": {
            "0": "fora da pastagem",
            "1": "baixo",
            "2": "moderado",
            "3": "alto",
            "4": "pastagem sem vigor",
            "255": "NoData",
        },
    }
    configuracao["fontes_raster"] = {}
    for nome, caminho in (("pastagem", caminho_pastagem), ("vigor", caminho_vigor)):
        if caminho and Path(caminho).suffix.lower() in (".tif", ".tiff"):
            with rasterio.open(caminho) as camada:
                configuracao["fontes_raster"][nome] = camada.tags()
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    registros, coberturas, grades = [], [], []
    for indice, cena in enumerate(cenas):
        print(f"Analisando pastagens por vigor — {cena['data']}", flush=True)
        produtos, mascara_roi, rgb, grade = calcular_produtos_roi(
            cena, roi, L, caminho_mde
        )
        del rgb
        pastagem, cobertura_conhecida = ler_mascara_pastagem(
            caminho_pastagem, grade, mascara_roi, codigo_pastagem
        )
        valores_vigor = (
            produtos["ndvi"]
            if limites_ndvi is not None
            else ler_classes_raster(caminho_vigor, grade, mascara_roi.shape)
        )
        classes = classificar_vigor(pastagem, valores_vigor, limites_ndvi)
        pasta = destino / cena["data"]
        pasta.mkdir(parents=True, exist_ok=True)
        classe_exportada = classes.copy()
        classe_exportada[~cobertura_conhecida] = 255
        salvar_raster_classes(classe_exportada, grade, pasta / "classes_vigor.tif")
        mascara_exportada = pastagem.astype("uint8")
        mascara_exportada[~cobertura_conhecida] = 255
        salvar_raster_classes(mascara_exportada, grade, pasta / "pastagem_mascara.tif")
        mostrar_classes(classes, mascara_roi, cena["data"], pasta / "vigor_mapa.png")
        # A camada vetorial de referência é derivada uma vez na grade nativa.
        if indice == 0:
            for extensao in ("geojson", "shp"):
                exportar_poligonos(
                    pastagem,
                    grade,
                    destino / "camadas" / f"pastagens.{extensao}",
                    propriedades={"classe": codigo_pastagem},
                )
        area_pixel = area_pixel_hectares(grade)
        resumo = {
            configuracao["area_analise"]: int(mascara_roi.sum()),
            "Cobertura de uso do solo desconhecida": int(
                (mascara_roi & ~cobertura_conhecida).sum()
            ),
            "Pastagem": int(pastagem.sum()),
            "Baixo vigor": int((classes == 1).sum()),
            "Vigor moderado": int((classes == 2).sum()),
            "Alto vigor": int((classes == 3).sum()),
            "Pastagem sem vigor classificado": int((classes == 4).sum()),
        }
        for nome, pixels in resumo.items():
            coberturas.append(
                {
                    "data": cena["data"],
                    "grupo": nome,
                    "pixels": pixels,
                    "area_ha_grade": pixels * area_pixel,
                }
            )
        registros_data = []
        for codigo, (chave, nome_classe, cor) in CLASSES_VIGOR.items():
            mascara_classe = classes == codigo
            pasta_classe = pasta / chave
            pasta_classe.mkdir(exist_ok=True)
            registros_classe = []
            for nome_produto, dados in produtos.items():
                intervalo, cores, unidade = PRODUTOS[nome_produto]
                estatisticas = estatisticas_descritivas(
                    dados,
                    intervalo,
                    mascara_roi=mascara_classe,
                    permitir_area_vazia=True,
                )
                estatisticas["base_area"] = (
                    f"ROI ∩ pastagem ∩ {nome_classe}; centros dos pixels"
                )
                registro = {
                    "data": cena["data"],
                    "satelite": cena["satelite"],
                    "vigor": chave,
                    "codigo_vigor": codigo,
                    "produto": nome_produto,
                    "area_classe_ha_grade": int(mascara_classe.sum()) * area_pixel,
                    "area_valida_ha_grade": estatisticas["pixels_validos"] * area_pixel,
                    **estatisticas,
                }
                registros.append(registro)
                registros_data.append(registro)
                registros_classe.append(registro)
                dados_classe = dados.copy()
                dados_classe[~mascara_classe] = np.nan
                titulo = f"{nome_produto.upper()} — {nome_classe} — {cena['data']}"
                mostrar_mapa(
                    dados_classe,
                    titulo,
                    intervalo,
                    cores,
                    unidade,
                    pasta_classe / f"{nome_produto}_mapa.png",
                )
                mostrar_histograma(
                    estatisticas,
                    titulo,
                    intervalo,
                    unidade,
                    pasta_classe / f"{nome_produto}_histograma.png",
                )
            exportar_estatisticas(registros_classe, pasta_classe / "estatisticas.csv")
            salvar_relatorio_classe(cena, nome_classe, registros_classe, pasta_classe)
        exportar_estatisticas(registros_data, pasta / "estatisticas.csv")
        salvar_relatorio_data(cena, resumo, configuracao, pasta)
        grades.append({"data": cena["data"], "satelite": cena["satelite"], **grade})
    exportar_estatisticas(registros, destino / "estatisticas_por_vigor.csv")
    exportar_estatisticas(coberturas, destino / "cobertura_por_vigor.csv")
    (destino / "manifesto.json").write_text(
        json.dumps(
            {"configuracao": configuracao, "roi": roi, "grades": grades},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    salvar_relatorio_pastagens(cenas, registros, configuracao, destino)
    from .relatorio_pdf import gerar_pdf_da_pasta

    gerar_pdf_da_pasta(destino, destino / "relatorio.pdf")
    print(
        f"Relatório das pastagens: {(destino / 'relatorio.pdf').resolve()}", flush=True
    )
    return registros
