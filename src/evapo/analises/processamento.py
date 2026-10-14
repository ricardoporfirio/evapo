"""Processamento em resolução nativa da mesma ROI em todas as cenas."""

import json
from contextlib import ExitStack
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.features import geometry_mask, geometry_window
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom
from rasterio.windows import Window

from evapo.calculos.albedo import (
    calcular_transmissividade,
    corrigir_albedo_superficie,
)
from evapo.dados.area import usar_imagem_inteira
from evapo.calculos.estatisticas import estatisticas_descritivas, exportar_estatisticas
from evapo.calculos.opticos import calcular_indices_opticos
from evapo.calculos.metodo import parametros_metodo
from evapo.calculos.solar import informacoes_solares
from evapo.calculos.energia import calcular_radiacoes, produtos_termicos_cena, validar_temperatura_ar, pendencias_energia
from evapo.calculos.produtos import PRODUTOS
from evapo.relatorios.plots import mostrar_histograma, mostrar_mapa
from evapo.dados.rasters_resultados import salvar_produtos, salvar_histograma
from evapo.calculos.reflectancia import calcular_reflectancias
from evapo.relatorios.html import salvar_relatorio_cena, salvar_relatorio_geral


def calcular_produtos_roi(cena, roi, L=0.5, caminho_mde=None, temperatura_ar=None):
    """Recorta DN e QA antes do cálculo; círculos/polígonos mascaram fora da ROI."""
    pasta = cena["caminho"].parent
    solar = cena["mtl"].get("EVAPO_SOLAR") or informacoes_solares(cena["mtl"], data=cena["data"])
    mtl = {**cena["mtl"], "EVAPO_SOLAR": solar}
    with ExitStack() as arquivos_abertos:
        imagem = arquivos_abertos.enter_context(rasterio.open(cena["caminho"]))
        arquivo_qualidade = arquivos_abertos.enter_context(
            rasterio.open(next(pasta.glob("*_QA_PIXEL.TIF")))
        )
        arquivo_saturacao = arquivos_abertos.enter_context(
            rasterio.open(next(pasta.glob("*_QA_RADSAT.TIF")))
        )
        if imagem.count != 7 or imagem.crs is None:
            raise ValueError("Empilhamento deve ter sete bandas e CRS definido.")
        for arquivo_auxiliar in (arquivo_qualidade, arquivo_saturacao):
            if (
                arquivo_auxiliar.shape != imagem.shape
                or arquivo_auxiliar.transform != imagem.transform
                or arquivo_auxiliar.crs != imagem.crs
            ):
                raise ValueError(
                    "A imagem e as máscaras QA precisam ter a mesma grade."
                )
        if usar_imagem_inteira(roi):
            geometria_roi = None
            janela = Window(0, 0, imagem.width, imagem.height)
        else:
            geometria_roi = transform_geom("EPSG:4326", imagem.crs, roi["geometry"])
            # Boundless mantém a ROI completa se uma data não a cobrir totalmente.
            janela = geometry_window(imagem, [geometria_roi], boundless=True)
        transformacao = imagem.window_transform(janela)
        tamanho_recorte = (int(janela.height), int(janela.width))
        mascara_roi = (
            np.ones(tamanho_recorte, dtype=bool)
            if geometria_roi is None
            else geometry_mask(
                [geometria_roi],
                tamanho_recorte,
                transformacao,
                invert=True,
                all_touched=False,
            )
        )
        if not mascara_roi.any():
            raise ValueError(
                "ROI pequena demais: nenhum centro de pixel Landsat dentro do desenho."
            )
        numeros_digitais = imagem.read(
            window=janela, masked=True, boundless=True, fill_value=0
        )
        qualidade_pixels = arquivo_qualidade.read(
            1, window=janela, boundless=True, fill_value=1
        )
        saturacao_pixels = arquivo_saturacao.read(
            1, window=janela, boundless=True, fill_value=0
        )
        reflectancias = calcular_reflectancias(
            numeros_digitais,
            qualidade_pixels,
            saturacao_pixels,
            cena["mtl"],
            mascara_roi=mascara_roi,
        )
        cobertura_cena = (
            ~np.ma.getmaskarray(numeros_digitais) & (numeros_digitais.data != 0)
        ).any(axis=0)
        del numeros_digitais
        produtos = calcular_indices_opticos(reflectancias, L=L)
        ndvi, iaf = produtos["ndvi"], produtos["iaf"]
        bit_agua = 1 << 7
        bit_neve = 1 << 5
        pixels_agua_ou_neve = (qualidade_pixels & (bit_agua | bit_neve)) != 0
        iaf[pixels_agua_ou_neve] = np.nan
        albedo_toa = produtos["albedo_toa"]
        produtos.update(produtos_termicos_cena(
            cena, ndvi, qualidade_pixels, saturacao_pixels, imagem.crs,
            transformacao, mascara_roi, iaf=iaf,
        ))
        if caminho_mde is not None:
            modelo_elevacao = arquivos_abertos.enter_context(rasterio.open(caminho_mde))
            if modelo_elevacao.count != 1 or modelo_elevacao.crs is None:
                raise ValueError("MDE precisa ter uma banda em metros e CRS definido.")
            with WarpedVRT(
                modelo_elevacao,
                crs=imagem.crs,
                transform=transformacao,
                width=tamanho_recorte[1],
                height=tamanho_recorte[0],
                dtype="float32",
                nodata=np.nan,
            ) as elevacao_alinhada:
                altitude_metros = (
                    elevacao_alinhada.read(1, masked=True).filled(np.nan)
                    * modelo_elevacao.scales[0]
                    + modelo_elevacao.offsets[0]
                )
            transmissividade = calcular_transmissividade(altitude_metros)
            valido = mascara_roi & cobertura_cena & ((qualidade_pixels & 31) == 0) & ((saturacao_pixels & (1 << 11)) == 0)
            transmissividade[~valido] = np.nan
            produtos["transmissividade"] = transmissividade
            produtos["albedo_superficie"] = corrigir_albedo_superficie(
                albedo_toa, transmissividade
            )
            produtos.update(calcular_radiacoes(
                transmissividade, mtl, temperatura_ar,
                produtos["emissividade"], produtos.get("temperatura_superficie"),
                produtos["albedo_superficie"],
            ))
        imagem_rgb = np.stack([reflectancias[b] for b in (4, 3, 2)], axis=-1)
        imagem_rgb = np.clip(imagem_rgb / 0.3, 0, 1) ** 0.8
        imagem_rgb[~np.isfinite(imagem_rgb).all(axis=-1)] = [0.90, 0.91, 0.92]
        return (
            produtos,
            mascara_roi,
            imagem_rgb,
            {
                **parametros_metodo(),
                "solar": solar,
                "crs": str(imagem.crs),
                "pendencias": pendencias_energia(produtos),
                "transform": list(transformacao)[:6],
                "janela": {
                    "col_off": janela.col_off,
                    "row_off": janela.row_off,
                    "width": janela.width,
                    "height": janela.height,
                },
            },
        )


def processar_todas_cenas(cenas, roi, destino="saida/roi", L=0.5, caminho_mde=None, temperatura_ar=None):
    temperatura_ar = validar_temperatura_ar(temperatura_ar)
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    registros, manifestos = [], []
    imagem_inteira = usar_imagem_inteira(roi)
    nome_area = "Imagem inteira" if imagem_inteira else "ROI"
    configuracoes_figuras = PRODUTOS
    for cena in cenas:
        print(
            f"Processando {nome_area} — {cena['data']} — {cena['satelite']}", flush=True
        )
        pasta = destino / cena["data"]
        pasta.mkdir(exist_ok=True)
        produtos, mascara_roi, imagem_rgb, informacoes_grade = calcular_produtos_roi(
            cena, roi, L, caminho_mde, temperatura_ar
        )
        for pendencia in informacoes_grade["pendencias"]:
            print(f"{cena['data']}: {pendencia}", flush=True)
        salvar_produtos(produtos, informacoes_grade, pasta)
        figura, eixo = plt.subplots(figsize=(8, 8), layout="constrained")
        passo = max(1, int(np.ceil(max(imagem_rgb.shape[:2]) / 1200)))
        eixo.imshow(imagem_rgb[::passo, ::passo], interpolation="nearest")
        eixo.set_title(f"RGB — {nome_area} — {cena['data']} | {cena['satelite']}")
        eixo.set_axis_off()
        figura.savefig(pasta / "rgb_mapa.png", dpi=160)
        plt.close(figura)
        registros_da_cena = []
        for nome, dados in produtos.items():
            titulo, limites, mapa_cores, unidade = configuracoes_figuras[nome]
            titulo = f"{titulo} — {nome_area} — {cena['data']} | {cena['satelite']}"
            estatisticas = estatisticas_descritivas(
                dados, limites, mascara_roi=mascara_roi
            )
            if imagem_inteira:
                estatisticas["base_area"] = "imagem inteira; grade nativa de cada cena"
            registro = dict(
                data=cena["data"],
                satelite=cena["satelite"],
                produto=nome,
                unidade=PRODUTOS[nome][3],
                **estatisticas,
            )
            registros.append(registro)
            registros_da_cena.append(registro)
            salvar_histograma(estatisticas, pasta / f"{nome}_histograma.json")
            mostrar_mapa(
                dados, titulo, limites, mapa_cores, unidade, pasta / f"{nome}_mapa.png"
            )
            mostrar_histograma(
                estatisticas, titulo, limites, unidade, pasta / f"{nome}_histograma.png"
            )
        exportar_estatisticas(registros_da_cena, pasta / "estatisticas.csv")
        salvar_relatorio_cena(
            cena, registros_da_cena, pasta, imagem_inteira=imagem_inteira
        )
        manifestos.append(
            dict(data=cena["data"], satelite=cena["satelite"], **informacoes_grade)
        )
        # Cada cena é descartada antes da próxima; não acumula rasters integrais.
        del produtos, mascara_roi, imagem_rgb, dados
    exportar_estatisticas(registros, destino / "estatisticas_todas_cenas_roi.csv")
    (destino / "manifesto_roi.json").write_text(
        json.dumps(
            {
                **parametros_metodo(),
                "roi": roi,
                "L": L,
                "mde": str(caminho_mde) if caminho_mde else None,
                "temperatura_ar_c": temperatura_ar,
                "resolucao": "nativa; imagem inteira"
                if imagem_inteira
                else "nativa; centro dos pixels dentro da ROI",
                "cenas": manifestos,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    salvar_relatorio_geral(cenas, registros, destino, imagem_inteira=imagem_inteira)
    from evapo.relatorios.pdf import gerar_pdf_da_pasta

    gerar_pdf_da_pasta(destino, destino / "relatorio.pdf")
    return registros
