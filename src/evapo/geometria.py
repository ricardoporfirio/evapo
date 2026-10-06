"""Verifica se o desenho forma uma área fechada, sem lados que se cruzam."""

import numpy as np


def _orientacao(inicio, fim, ponto):
    """Indica de que lado da reta está o ponto: positivo, negativo ou zero."""
    largura_do_segmento = fim[0] - inicio[0]
    altura_do_segmento = fim[1] - inicio[1]
    distancia_horizontal = ponto[0] - inicio[0]
    distancia_vertical = ponto[1] - inicio[1]
    return (
        largura_do_segmento * distancia_vertical
        - altura_do_segmento * distancia_horizontal
    )


def _ponto_no_segmento(inicio, fim, ponto):
    dentro_na_horizontal = min(inicio[0], fim[0]) <= ponto[0] <= max(inicio[0], fim[0])
    dentro_na_vertical = min(inicio[1], fim[1]) <= ponto[1] <= max(inicio[1], fim[1])
    return dentro_na_horizontal and dentro_na_vertical


def _segmentos_se_cruzam(inicio_1, fim_1, inicio_2, fim_2, tolerancia):
    lado_inicio_2 = _orientacao(inicio_1, fim_1, inicio_2)
    lado_fim_2 = _orientacao(inicio_1, fim_1, fim_2)
    lado_inicio_1 = _orientacao(inicio_2, fim_2, inicio_1)
    lado_fim_1 = _orientacao(inicio_2, fim_2, fim_1)

    primeiro_segmento_separa_pontos = lado_inicio_2 * lado_fim_2 < 0
    segundo_segmento_separa_pontos = lado_inicio_1 * lado_fim_1 < 0
    if primeiro_segmento_separa_pontos and segundo_segmento_separa_pontos:
        return True

    # Também rejeita lados que se encostam fora dos vértices vizinhos.
    contatos_possiveis = [
        (lado_inicio_2, inicio_1, fim_1, inicio_2),
        (lado_fim_2, inicio_1, fim_1, fim_2),
        (lado_inicio_1, inicio_2, fim_2, inicio_1),
        (lado_fim_1, inicio_2, fim_2, fim_1),
    ]
    for orientacao, inicio, fim, ponto in contatos_possiveis:
        alinhado_com_a_reta = abs(orientacao) <= tolerancia
        if alinhado_com_a_reta and _ponto_no_segmento(inicio, fim, ponto):
            return True
    return False


def validar_poligono(vertices):
    """Valida os vértices e devolve um anel com o primeiro ponto repetido no fim."""
    pontos = np.asarray(vertices, dtype="float64")
    formato_correto = pontos.ndim == 2 and pontos.shape[1] == 2
    if not formato_correto or len(pontos) < 3 or not np.isfinite(pontos).all():
        raise ValueError("Desenhe pelo menos três vértices válidos.")

    if np.array_equal(pontos[0], pontos[-1]):
        pontos = pontos[:-1]
    if len(np.unique(pontos, axis=0)) != len(pontos):
        raise ValueError("O desenho contém vértices repetidos.")

    # Trazer o desenho para perto da origem evita erros de arredondamento no UTM.
    pontos_locais = pontos - pontos[0]
    coordenadas_x = pontos_locais[:, 0]
    coordenadas_y = pontos_locais[:, 1]
    proximos_x = np.roll(coordenadas_x, -1)
    proximos_y = np.roll(coordenadas_y, -1)
    area = 0.5 * abs(np.sum(coordenadas_x * proximos_y - coordenadas_y * proximos_x))
    if area <= 1e-18:
        raise ValueError("A ROI precisa ter área maior que zero.")

    tamanho_do_desenho = np.ptp(pontos, axis=0).max()
    tolerancia = np.finfo(float).eps * tamanho_do_desenho**2 * 32
    quantidade_pontos = len(pontos)
    for indice_1 in range(quantidade_pontos):
        inicio_1 = pontos[indice_1]
        fim_1 = pontos[(indice_1 + 1) % quantidade_pontos]
        for indice_2 in range(indice_1 + 1, quantidade_pontos):
            lados_vizinhos = indice_2 == indice_1 + 1
            primeiro_e_ultimo_lado = indice_1 == 0 and indice_2 == quantidade_pontos - 1
            if lados_vizinhos or primeiro_e_ultimo_lado:
                continue
            inicio_2 = pontos[indice_2]
            fim_2 = pontos[(indice_2 + 1) % quantidade_pontos]
            if _segmentos_se_cruzam(inicio_1, fim_1, inicio_2, fim_2, tolerancia):
                raise ValueError(
                    "O polígono cruza a si mesmo. Redesenhe sem cruzamentos."
                )

    return np.vstack([pontos, pontos[0]]).tolist()
