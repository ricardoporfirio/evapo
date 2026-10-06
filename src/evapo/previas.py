"""Prévias RGB de todas as datas, alinhadas na mesma grade para comparar nuvens."""

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds

from .metadados import carregar_mtl
from .reflectancia import calcular_reflectancias


class PreviasCenas:
    """Carrega uma data quando ela é selecionada e guarda a prévia na memória."""

    def __init__(self, caminhos, referencia, tamanho=1000):
        referencia = Path(referencia).resolve()
        caminhos_unicos = {Path(caminho).resolve() for caminho in caminhos}
        caminhos_unicos.add(referencia)
        self.cenas = []
        for caminho in sorted(caminhos_unicos):
            metadados = carregar_mtl(caminho.parent)
            atributos = metadados["IMAGE_ATTRIBUTES"]
            self.cenas.append(
                {
                    "caminho": caminho,
                    "data": atributos["DATE_ACQUIRED"],
                    "satelite": atributos["SPACECRAFT_ID"],
                    "mtl": metadados,
                }
            )
        self.cenas.sort(key=lambda cena: cena["data"])
        self.indice_inicial = next(
            indice
            for indice, cena in enumerate(self.cenas)
            if cena["caminho"] == referencia
        )

        with rasterio.open(referencia) as imagem:
            self.crs = imagem.crs
        if self.crs is None or not self.crs.is_projected:
            raise ValueError(
                "A imagem de referência precisa ter um CRS projetado em metros."
            )

        limites_cenas = []
        for cena in self.cenas:
            with rasterio.open(cena["caminho"]) as imagem:
                if imagem.crs is None or imagem.count != 7:
                    raise ValueError(
                        "Cada cena precisa ter sete bandas e CRS definido."
                    )
                limites_cenas.append(
                    transform_bounds(imagem.crs, self.crs, *imagem.bounds)
                )
        esquerda = min(limites[0] for limites in limites_cenas)
        inferior = min(limites[1] for limites in limites_cenas)
        direita = max(limites[2] for limites in limites_cenas)
        superior = max(limites[3] for limites in limites_cenas)

        # A mesma posição da tela corresponde ao mesmo local em todas as datas.
        resolucao_previa = max(direita - esquerda, superior - inferior) / tamanho
        self.largura = int(np.ceil((direita - esquerda) / resolucao_previa))
        self.altura = int(np.ceil((superior - inferior) / resolucao_previa))
        self.transformacao = from_bounds(
            esquerda, inferior, direita, superior, self.largura, self.altura
        )
        self.limites = [esquerda, direita, inferior, superior]
        self.cache = {}

    def carregar(self, indice):
        if indice in self.cache:
            return self.cache[indice]
        cena = self.cenas[indice]
        pasta = cena["caminho"].parent
        parametros_grade = {
            "crs": self.crs,
            "transform": self.transformacao,
            "width": self.largura,
            "height": self.altura,
        }
        with (
            rasterio.open(cena["caminho"]) as imagem,
            rasterio.open(next(pasta.glob("*_QA_PIXEL.TIF"))) as arquivo_qualidade,
            rasterio.open(next(pasta.glob("*_QA_RADSAT.TIF"))) as arquivo_saturacao,
        ):
            for auxiliar in (arquivo_qualidade, arquivo_saturacao):
                if (
                    auxiliar.shape != imagem.shape
                    or auxiliar.transform != imagem.transform
                    or auxiliar.crs != imagem.crs
                ):
                    raise ValueError(
                        "As máscaras QA precisam estar alinhadas com a cena."
                    )
            with (
                WarpedVRT(imagem, **parametros_grade) as imagem_alinhada,
                WarpedVRT(arquivo_qualidade, **parametros_grade) as qualidade_alinhada,
                WarpedVRT(arquivo_saturacao, **parametros_grade) as saturacao_alinhada,
            ):
                numeros_digitais = imagem_alinhada.read(masked=True)
                qualidade = qualidade_alinhada.read(1)
                saturacao = saturacao_alinhada.read(1)

        reflectancias = calcular_reflectancias(
            numeros_digitais, qualidade, saturacao, cena["mtl"]
        )
        imagem_rgb = np.stack([reflectancias[banda] for banda in (4, 3, 2)], axis=-1)
        pixels_visiveis = np.isfinite(imagem_rgb).all(axis=-1)
        imagem_rgb = np.clip(imagem_rgb / 0.3, 0, 1) ** 0.8
        imagem_rgb[~pixels_visiveis] = [0.9, 0.91, 0.92]
        previa = {
            "rgb": imagem_rgb,
            "percentual_visivel": 100
            * np.count_nonzero(pixels_visiveis)
            / pixels_visiveis.size,
        }
        self.cache[indice] = previa
        return previa
