"""Relatórios próprios das pastagens, sem substituir a análise geral da ROI."""

import html
from pathlib import Path

from evapo.calculos.estatisticas import bloco_estatistico
from evapo.relatorios.html import pagina
from evapo.calculos.produtos import unidade_produto


def salvar_relatorio_classe(cena, nome, registros, destino):
    corpo = '<p><a href="../relatorio.html">Pastagens desta data</a> · <a href="estatisticas.csv">CSV</a></p>'
    corpo += "<p>Somente centros de pixels dentro da ROI, da pastagem e desta classe de vigor. As máscaras QA são aplicadas a cada produto. Uma classe vazia permanece na tabela; sua média não é zero.</p>"
    for registro in registros:
        produto = registro["produto"]
        unidade = unidade_produto(produto)
        corpo += "<section>" + bloco_estatistico(registro, produto.upper(), unidade)
        corpo += f'<div class="figuras"><img src="{produto}_mapa.png" alt="Mapa de {produto}"><img src="{produto}_histograma.png" alt="Histograma de {produto}"></div></section>'
    Path(destino, "relatorio.html").write_text(
        pagina(f"{nome} — pastagens — {cena['data']}", corpo), encoding="utf-8"
    )


def descricao_metodo(configuracao):
    texto = f"<p>Área analisada: {configuracao.get('area_analise', 'ROI')}. Método: {html.escape(configuracao['metodo'])}. "
    if configuracao["limites_ndvi"] is not None:
        baixo, alto = configuracao["limites_ndvi"]
        texto += f"Baixo: NDVI &lt; {baixo}; moderado: {baixo} ≤ NDVI &lt; {alto}; alto: NDVI ≥ {alto}. Classes recalculadas em cada data. Limites fornecidos pelo usuário; não equivalem ao produto anual do MapBiomas. "
    else:
        texto += "Classes do mapa anual: 1 = baixo; 2 = moderado (médio no MapBiomas); 3 = alto. A mesma camada é usada como estratificação espacial em todas as datas. "
    if configuracao["ano_camada"] is not None:
        texto += f"Ano de referência da camada: {configuracao['ano_camada']}. "
    texto += "Uma camada de referência não comprova o uso do solo nem o vigor em anos posteriores. Pixels de pastagem sem classificação são contabilizados separadamente.</p>"
    return texto


def salvar_relatorio_data(cena, resumo, configuracao, destino):
    corpo = '<p><a href="../relatorio.html">Todas as datas analisadas</a> · <a href="estatisticas.csv">CSV por classe</a></p>'
    corpo += descricao_metodo(configuracao)
    corpo += '<section><h2>Máscara e classes de vigor</h2><img src="vigor_mapa.png" alt="Classes de vigor na pastagem"><p><a href="classes_vigor.tif">GeoTIFF de vigor</a> · <a href="pastagem_mascara.tif">Máscara GeoTIFF</a></p>'
    corpo += "<p>Áreas em hectares são calculadas na grade projetada, sem correção da distorção cartográfica. Classes sem observações válidas não recebem vigor baixo.</p><ul>"
    for nome, valor in resumo.items():
        corpo += f"<li>{html.escape(nome)}: {valor:,} pixels</li>"
    corpo += "</ul></section><section><h2>Análise por vigor</h2><ul>"
    for pasta, nome in (
        ("baixo", "Baixo vigor"),
        ("moderado", "Vigor moderado"),
        ("alto", "Alto vigor"),
    ):
        corpo += f'<li><a href="{pasta}/relatorio.html">{nome}</a></li>'
    corpo += "</ul></section>"
    Path(destino, "relatorio.html").write_text(
        pagina(f"Pastagens — {cena['data']}", corpo), encoding="utf-8"
    )


def salvar_relatorio_pastagens(cenas, registros, configuracao, destino):
    corpo = '<p>Análise adicional das áreas de pastagem. <a href="relatorio.pdf">Relatório interpretativo PDF</a> · <a href="estatisticas_por_vigor.csv">Estatísticas CSV</a> · <a href="cobertura_por_vigor.csv">Cobertura e áreas CSV</a> · <a href="manifesto.json">Fontes e parâmetros</a></p>'
    corpo += descricao_metodo(configuracao)
    corpo += '<section><h2>Camada de pastagem na ROI</h2><p>Polígonos derivados da camada de referência, antes das exclusões QA. Mantêm os buracos e os limites dos pixels.</p><p><a href="camadas/pastagens.geojson">GeoJSON</a> · Shapefile: <a href="camadas/pastagens.shp">SHP</a>, <a href="camadas/pastagens.shx">SHX</a>, <a href="camadas/pastagens.dbf">DBF</a>, <a href="camadas/pastagens.prj">PRJ</a>, <a href="camadas/pastagens.cpg">CPG</a> (mantenha todos juntos).</p></section>'
    corpo += "<section><h2>Datas</h2><ul>"
    for cena in cenas:
        corpo += f'<li><a href="{cena["data"]}/relatorio.html">{cena["data"]} — {cena["satelite"]}</a></li>'
    corpo += '</ul></section><section><h2>Comparação por classe</h2><div class="tabela"><table><tr><th>Data</th><th>Vigor</th><th>Produto</th><th>Pixels da classe</th><th>Pixels válidos</th><th>Cobertura (%)</th><th>Média</th><th>Mediana</th><th>Desvio padrão</th><th>Mínimo</th><th>Máximo</th></tr>'
    for r in registros:
        valores = [
            r["data"],
            r["vigor"],
            r["produto"],
            r["pixels_totais"],
            r["pixels_validos"],
        ]
        valores.extend(
            f"{r[chave]:.4f}"
            for chave in (
                "cobertura_percentual",
                "media",
                "mediana",
                "desvio_padrao",
                "minimo",
                "maximo",
            )
        )
        corpo += (
            "<tr>"
            + "".join(f"<td>{html.escape(str(v))}</td>" for v in valores)
            + "</tr>"
        )
    corpo += "</table></div><p>nan = resultado ausente. A cobertura de cada produto usa os pixels da classe como denominador. No método NDVI, pixels sem NDVI válido ficam sem classe e não entram nesse denominador.</p></section>"
    if not any(r["produto"] == "albedo_superficie" for r in registros):
        corpo += "<p>Albedo da superfície pendente: não foi informado um MDE.</p>"
    corpo += '<p>Fonte: <a href="https://brasil.mapbiomas.org/iniciativas-e-produtos/cobertura-e-uso-da-terra/pastagem/pastagem/">MapBiomas — pastagens</a>; <a href="https://brasil.mapbiomas.org/iniciativas-e-produtos/cobertura-e-uso-da-terra/pastagem/condicao-de-vigor/">condição de vigor</a>.</p>'
    Path(destino, "relatorio.html").write_text(
        pagina("Pastagens por classe de vigor", corpo), encoding="utf-8"
    )
