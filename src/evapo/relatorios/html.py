"""Relatórios HTML locais com tabelas descritivas, figuras e links por data."""

import html
from datetime import date
from pathlib import Path

import numpy as np

from evapo.calculos.estatisticas import bloco_estatistico
from evapo.calculos.produtos import unidade_produto


def pagina(titulo, corpo):
    return f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titulo)}</title><style>
body{{font:16px system-ui;max-width:1150px;margin:30px auto;padding:0 20px;color:#183041;background:#f5f7fa}}
section{{background:white;padding:20px;margin:24px 0;border-radius:12px}}
a{{color:#185fa4}}p{{line-height:1.6}}table{{border-collapse:collapse;background:white}}
th,td{{padding:8px 12px;border-bottom:1px solid #e3e8ed}}th{{text-align:left}}
.figuras{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}
img{{max-width:100%;height:auto}}.tabela{{overflow-x:auto}}
</style><h1>{html.escape(titulo)}</h1>{corpo}</html>"""


def salvar_relatorio_cena(cena, registros, destino, imagem_inteira=False):
    data = date.fromisoformat(cena["data"]).strftime("%d/%m/%Y")
    area = "Imagem inteira" if imagem_inteira else "ROI"
    titulo = f"{area} — {data} — {cena['satelite'].replace('_', ' ')}"
    corpo = '<p><a href="../relatorio.html">Datas da análise</a> · <a href="estatisticas.csv">Baixar estatísticas CSV</a></p>'
    corpo += '<section><h2>Composição RGB</h2><p>B4/B3/B2; ajuste fixo de reflectância 0–0,30 e gamma 0,8. Cinza indica pixels excluídos.</p><img src="rgb_mapa.png" alt="RGB da ROI"></section>'
    for registro in registros:
        nome = registro["produto"]
        unidade = unidade_produto(nome)
        corpo += "<section>" + bloco_estatistico(
            registro, nome.replace("_", " ").upper(), unidade
        )
        corpo += f'<div class="figuras"><img src="{nome}_mapa.png" alt="Mapa de {nome}"><img src="{nome}_histograma.png" alt="Histograma de {nome}"></div></section>'
    Path(destino, "relatorio.html").write_text(pagina(titulo, corpo), encoding="utf-8")


def salvar_relatorio_geral(
    cenas, registros, destino, incluir_timelapse=False, imagem_inteira=False
):
    area = "Imagem inteira" if imagem_inteira else "ROI"
    descricao = (
        "Toda a grade nativa de cada imagem. O time lapse usa uma grade que abrange todas as cenas."
        if imagem_inteira
        else "A mesma ROI geográfica em todas as datas, considerando os centros dos pixels dentro do desenho."
    )
    corpo = f"<p>{descricao} Estatísticas em resolução nativa. QA pode excluir observações de nuvens, sombras e saturação.</p>"
    corpo += (
        '<p><a href="relatorio.pdf">Relatório interpretativo PDF</a> · '
        '<a href="estatisticas_todas_cenas_roi.csv">Baixar CSV consolidado</a></p>'
    )
    if incluir_timelapse:
        corpo += '<p><a href="timelapse/timelapse_interativo.html">Abrir time lapse interativo</a></p>'
    corpo += "<section><h2>Cenas</h2><ul>"
    for cena in cenas:
        data = date.fromisoformat(cena["data"]).strftime("%d/%m/%Y")
        corpo += f'<li><a href="{cena["data"]}/relatorio.html">{data} — {html.escape(cena["satelite"].replace("_", " "))}</a></li>'
    corpo += '</ul></section><section><h2>Comparação por data e produto</h2><div class="tabela"><table><thead><tr><th>Data</th><th>Produto</th><th>Pixels válidos</th><th>Cobertura (%)</th><th>Média</th><th>Mediana</th><th>Desvio padrão</th><th>Mínimo</th><th>Máximo</th></tr></thead><tbody>'
    for r in registros:
        valores = [r["data"], r["produto"], r["pixels_validos"]]
        for chave in (
            "cobertura_percentual",
            "media",
            "mediana",
            "desvio_padrao",
            "minimo",
            "maximo",
        ):
            valores.append(f"{r[chave]:.4f}" if np.isfinite(r[chave]) else "Sem dados")
        corpo += (
            "<tr>"
            + "".join(f"<td>{html.escape(str(v))}</td>" for v in valores)
            + "</tr>"
        )
    corpo += "</tbody></table></div></section>"
    if not any(r["produto"] == "albedo_superficie" for r in registros):
        corpo += "<p>Albedo da superfície pendente: não foi informado um MDE.</p>"
    Path(destino, "relatorio.html").write_text(
        pagina(f"Análise Landsat — {area} e datas selecionadas", corpo),
        encoding="utf-8",
    )
