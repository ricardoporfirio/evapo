"""Calcula estatisticas exatas dentro da ROI e exporta tabelas CSV/HTML."""

import csv
import html
from pathlib import Path

import numpy as np


def estatisticas_descritivas(
    dados, intervalo, bins=80, mascara_roi=None, permitir_area_vazia=False
):
    """Estatísticas exatas de todos os pixels finitos; desvio populacional."""
    dados = np.asarray(dados)
    if mascara_roi is not None and mascara_roi.shape != dados.shape:
        raise ValueError("A máscara ROI precisa ter a mesma forma dos dados.")
    pixels_area = int(
        dados.size if mascara_roi is None else np.count_nonzero(mascara_roi)
    )
    if not pixels_area and not permitir_area_vazia:
        raise ValueError("A ROI não contém centros de pixels nesta grade.")
    bordas = np.linspace(*intervalo, bins + 1)
    frequencias = np.zeros(bins, dtype="int64")
    partes = []
    total_validos, media, soma_desvios_quadrados = 0, 0.0, 0.0
    for inicio in range(0, dados.shape[0], 256):
        bloco = dados[inicio : inicio + 256]
        valido = np.isfinite(bloco)
        if mascara_roi is not None:
            valido &= mascara_roi[inicio : inicio + 256]
        valores_do_bloco = bloco[valido]
        if not valores_do_bloco.size:
            continue
        partes.append(valores_do_bloco)
        frequencias += np.histogram(valores_do_bloco, bordas)[0]
        # Junta os blocos sem manter toda a imagem em float64 na memória.
        quantidade_no_bloco = valores_do_bloco.size
        media_do_bloco = valores_do_bloco.mean(dtype="float64")
        diferenca_entre_medias = media_do_bloco - media
        quantidade_acumulada = total_validos + quantidade_no_bloco
        desvios_do_bloco = valores_do_bloco.astype("float64") - media_do_bloco
        soma_desvios_do_bloco = np.sum(desvios_do_bloco**2)
        ajuste_entre_blocos = (
            diferenca_entre_medias**2
            * total_validos
            * quantidade_no_bloco
            / quantidade_acumulada
        )
        soma_desvios_quadrados += soma_desvios_do_bloco + ajuste_entre_blocos
        media += diferenca_entre_medias * quantidade_no_bloco / quantidade_acumulada
        total_validos += quantidade_no_bloco
    if not total_validos:
        if mascara_roi is None:
            raise ValueError("Nenhum pixel válido para as estatísticas.")
        resultado = {
            "pixels_totais": pixels_area,
            "pixels_grade": int(dados.size),
            "pixels_fora_roi": int(dados.size - pixels_area),
            "pixels_validos": 0,
            "pixels_ausentes": pixels_area,
            "cobertura_percentual": 0.0 if pixels_area else np.nan,
            "base_area": "ROI; centros dos pixels",
        }
        resultado.update(
            {
                nome_estatistica: np.nan
                for nome_estatistica in (
                    "media",
                    "desvio_padrao",
                    "variancia",
                    "minimo",
                    "maximo",
                    "amplitude",
                    "p05",
                    "q1",
                    "mediana",
                    "q3",
                    "p95",
                    "intervalo_interquartil",
                )
            }
        )
        return dict(**resultado, frequencias=frequencias, bordas=bordas)
    if frequencias.sum() != total_validos:
        raise ValueError(
            "O intervalo do histograma não cobre todos os valores válidos."
        )
    valores = np.concatenate(partes)
    partes.clear()
    minimo, maximo = float(valores.min()), float(valores.max())
    percentil_5, quartil_1, mediana, quartil_3, percentil_95 = np.percentile(
        valores, [5, 25, 50, 75, 95], overwrite_input=True
    )
    variancia = soma_desvios_quadrados / total_validos
    desvio_padrao = np.sqrt(variancia)
    return {
        "pixels_totais": pixels_area,
        "pixels_grade": int(dados.size),
        "pixels_fora_roi": int(dados.size - pixels_area),
        "base_area": "grade completa"
        if mascara_roi is None
        else "ROI; centros dos pixels",
        "pixels_validos": int(total_validos),
        "pixels_ausentes": int(pixels_area - total_validos),
        "cobertura_percentual": 100 * total_validos / pixels_area,
        "media": float(media),
        "desvio_padrao": float(desvio_padrao),
        "variancia": float(variancia),
        "minimo": minimo,
        "maximo": maximo,
        "amplitude": maximo - minimo,
        "p05": float(percentil_5),
        "q1": float(quartil_1),
        "mediana": float(mediana),
        "q3": float(quartil_3),
        "p95": float(percentil_95),
        "intervalo_interquartil": float(quartil_3 - quartil_1),
        "frequencias": frequencias,
        "bordas": bordas,
    }


def bloco_estatistico(estatisticas, titulo, unidade="adimensional"):
    """Gera uma tabela HTML descritiva para os relatórios locais."""
    linhas = [
        ("Pixels da área analisada", f"{estatisticas['pixels_totais']:,}"),
        ("Pixels válidos", f"{estatisticas['pixels_validos']:,}"),
        ("Pixels ausentes / excluídos", f"{estatisticas['pixels_ausentes']:,}"),
        ("Cobertura válida da área", f"{estatisticas['cobertura_percentual']:.2f}%"),
    ]
    for rotulo, chave in [
        ("Média", "media"),
        ("Mediana", "mediana"),
        ("Desvio padrão populacional", "desvio_padrao"),
        ("Variância populacional", "variancia"),
        ("Mínimo", "minimo"),
        ("Percentil 5", "p05"),
        ("Quartil 1 (25%)", "q1"),
        ("Quartil 3 (75%)", "q3"),
        ("Percentil 95", "p95"),
        ("Máximo", "maximo"),
        ("Amplitude", "amplitude"),
        ("Intervalo interquartil", "intervalo_interquartil"),
    ]:
        linhas.append((rotulo, f"{estatisticas[chave]:.5f}"))
    corpo = "".join(
        f'<tr><td style="padding:5px 18px">{rotulo}</td><td style="text-align:right;padding:5px 18px">{valor}</td></tr>'
        for rotulo, valor in linhas
    )
    base = estatisticas.get("base_area", "grade completa")
    texto = f"<h3>{html.escape(titulo)}</h3><p>Unidade: {html.escape(unidade)}. Estatísticas de todos os pixels válidos; percentis exatos. Base: {html.escape(base)}.</p><table>{corpo}</table><p>Variância em unidades ao quadrado. Na ROI, pixels fora do desenho não entram no denominador da cobertura.</p>"
    if not estatisticas["pixels_validos"]:
        texto += "<p><strong>Sem pixels válidos nesta data/produto após as máscaras QA e ROI.</strong></p>"
    return texto


def exportar_estatisticas(registros, destino):
    linhas = [
        {
            nome_estatistica: valor
            for nome_estatistica, valor in rotulo.items()
            if nome_estatistica not in ("frequencias", "bordas")
        }
        for rotulo in registros
    ]
    if not linhas:
        return
    with Path(destino).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(linhas)
