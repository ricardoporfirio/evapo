"""Gera o relatório técnico em Word a partir de uma execução concluída."""

import argparse
import csv
import json
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.ticker import FuncFormatter
import numpy as np
import rasterio

from word_ooxml import build_docx


GREEN = "#245943"
COLORS = {"ROI": "#253e52", "baixo": "#d45e3c", "moderado": "#cf9c29", "alto": "#2b7851"}


def br(value, digits=2):
    if value is None:
        return "Não disponível"
    return f"{float(value):,.{digits}f}".replace(",", "@ ").replace(".", ",").replace("@ ", ".")


def dt(value):
    return date.fromisoformat(value).strftime("%d/%m/%Y")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter=";"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execucao", type=Path, required=True)
    parser.add_argument("--saida", type=Path, required=True)
    args = parser.parse_args()
    run = args.execucao.resolve()
    out = args.saida.resolve()
    figs = out.parent / "figuras_relatorio"
    figs.mkdir(parents=True, exist_ok=True)
    roi_rows = read_csv(run / "roi" / "estatisticas_todas_cenas_roi.csv")
    vigor_rows = read_csv(run / "pastagens" / "estatisticas_por_vigor.csv")
    coverage_rows = read_csv(run / "pastagens" / "cobertura_por_vigor.csv")
    config = json.loads((run / "configuracao.evapo.json").read_text(encoding="utf-8"))
    manifest = json.loads((run / "pastagens" / "manifesto.json").read_text(encoding="utf-8"))
    audit = json.loads((Path(__file__).parent / "auditoria_mde.json").read_text(encoding="utf-8"))
    dates = sorted({row["data"] for row in roi_rows})
    stats = {(r["data"], r["produto"]): r for r in roi_rows}
    vstats = {(r["data"], r["vigor"], r["produto"]): r for r in vigor_rows}
    first, last = dates[0], dates[-1]
    classes = ["baixo", "moderado", "alto"]
    def val(d, p, field="media", group="ROI"):
        row = stats[d, p] if group == "ROI" else vstats[d, group, p]
        return float(row[field])
    def summary_rows(products, digits=3):
        return [[dt(d)] + [br(val(d, p), digits) for p in products] for d in dates]
    n_roi = int(float(stats[first, "ndvi"]["pixels_totais"]))
    area_roi = n_roi * 0.09
    class_counts = {g: int(float(vstats[first, g, "ndvi"]["pixels_totais"])) for g in classes}
    n_pasture = sum(class_counts.values()) + 2

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.titleweight": "bold", "axes.labelcolor": "#26382e",
                         "savefig.facecolor": "white", "figure.facecolor": "white"})
    x = np.arange(len(dates))
    labels = [dt(d) for d in dates]
    comma = FuncFormatter(lambda v, _: br(v, 2))

    # As linhas apenas conectam as observações nas datas disponíveis.
    fig, axes = plt.subplots(2, 1, figsize=(8.6, 6.0), sharex=True, layout="constrained")
    for ax, product, ylabel in zip(axes, ["ndvi", "savi"], ["NDVI médio", "SAVI médio, L = 0,5"]):
        for group in ["ROI"] + classes:
            ax.plot(x, [val(d, product, group=group) for d in dates], marker="o", linewidth=1.8,
                    color=COLORS[group], label="Área total" if group == "ROI" else group.capitalize())
        ax.set_ylabel(ylabel)
        ax.yaxis.set_major_formatter(comma)
        ax.grid(axis="y", alpha=0.18)
    axes[0].legend(ncols=4, frameon=False, fontsize=9, loc="best")
    axes[1].set_xticks(x, labels, fontsize=9)
    fig.savefig(figs / "indices_temporais.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.0), layout="constrained")
    axes[0].plot(x, [val(d, "temperatura_superficie") for d in dates], color="#bd623d", marker="o")
    axes[0].set_ylabel("Temperatura média da superfície (°C)")
    axes[1].plot(x, [val(d, "saldo_radiacao") for d in dates], color=GREEN, marker="o")
    axes[1].set_ylabel("Saldo médio de radiação (W/m²)")
    for ax in axes:
        ax.set_xticks(x, [date.fromisoformat(d).strftime("%d/%m/%y") for d in dates], rotation=25, fontsize=8)
        ax.yaxis.set_major_formatter(comma)
        ax.grid(axis="y", alpha=0.18)
    fig.savefig(figs / "temperatura_radiacao.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.6, 3.3), layout="constrained")
    products = [("ndvi", "NDVI", "#356e54"), ("temperatura_superficie", "Temperatura da superfície", "#cf9352"),
                ("saldo_radiacao", "Saldo de radiação", "#5c7f99")]
    for k, (product, label, color) in enumerate(products):
        ax.bar(x + (k - 1) * 0.24, [val(d, product, "cobertura_percentual") for d in dates],
               0.23, label=label, color=color)
    ax.axhline(100 * audit["comparacao"]["pixels_validos_roi"] / n_roi, linestyle=":", color="#666666", linewidth=1)
    ax.set_xticks(x, labels, fontsize=9)
    ax.set_ylabel("Pixels válidos na ROI (%)")
    ax.set_ylim(0, 112)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: br(v, 0)))
    ax.legend(ncols=3, frameon=False, fontsize=8.5, loc="upper center")
    ax.grid(axis="y", alpha=0.18)
    fig.savefig(figs / "cobertura_valida.png", dpi=180)
    plt.close(fig)

    with rasterio.open(run / "pastagens" / first / "classes_vigor.tif") as ds:
        class_raster = ds.read(1)
    extent = [0, class_raster.shape[1] * 0.03, 0, class_raster.shape[0] * 0.03]
    cmap = ListedColormap(["#eeeeea", "#de7545", "#d9b34f", "#46845b", "#8f8f8f", "#ffffff"])
    shown = class_raster.copy()
    shown[shown == 255] = 5
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.7), layout="constrained")
    axes[0].imshow(shown, cmap=cmap, norm=BoundaryNorm(np.arange(-0.5, 6), 6), extent=extent, interpolation="nearest")
    axes[0].set_title("Classes anuais de vigor, 2025", fontsize=11)
    from matplotlib.patches import Patch
    axes[0].legend(handles=[Patch(color=cmap(i), label=name) for i, name in enumerate(
        ["Fora da pastagem", "Baixo", "Moderado", "Alto", "Sem vigor"] )],
        loc="lower left", fontsize=7, framealpha=0.95)
    with rasterio.open(run / "roi" / first / "rasters" / "transmissividade.tif") as ds:
        tau = ds.read(1, masked=True).filled(np.nan)
    axes[1].imshow(np.isfinite(tau).astype(int), cmap=ListedColormap(["#eeeeea", "#46845b"]),
                   extent=extent, interpolation="nearest", vmin=0, vmax=1)
    axes[1].set_title("Transmissividade válida, 16/06/2025", fontsize=11)
    axes[1].legend(handles=[Patch(color="#46845b", label="Valor válido"), Patch(color="#eeeeea", label="Sem resultado")],
                   loc="upper right", fontsize=8, framealpha=0.95)
    for ax in axes:
        ax.set_xlabel("Distância na grade (km)")
        ax.set_ylabel("Distância na grade (km)")
        ax.set_aspect("equal")
    fig.savefig(figs / "vigor_cobertura.png", dpi=180)
    plt.close(fig)

    selected = [first, "2025-12-25", last]
    fig, axes = plt.subplots(1, 3, figsize=(8.6, 3.7), layout="constrained")
    cm = plt.get_cmap("RdYlGn").with_extremes(bad="#eeeeea")
    for ax, d in zip(axes, selected):
        with rasterio.open(run / "roi" / d / "rasters" / "ndvi.tif") as ds:
            raster = ds.read(1, masked=True)
        im = ax.imshow(raster, cmap=cm, vmin=-1, vmax=1, interpolation="nearest", extent=extent)
        ax.set_title(dt(d), fontsize=10)
        ax.set_xlabel("Distância na grade (km)")
        ax.set_yticks([])
    fig.colorbar(im, ax=axes, shrink=0.78, pad=0.02, label="NDVI")
    fig.savefig(figs / "mapas_ndvi.png", dpi=180)
    plt.close(fig)

    blocks = []
    def b(kind, text=None, **kw):
        block = {"type": kind, **kw}
        if text is not None:
            block["text"] = text
        blocks.append(block)
    def p(text): b("paragraph", text)
    def h(text): b("heading2", text)
    def table(headers, rows, widths_cm=None):
        options = {"widths_cm": widths_cm} if widths_cm else {}
        b("table", headers=headers, rows=rows, **options)
    def image(name, caption, width=15.8):
        b("image", path=str(figs / name), width_cm=width)
        b("caption", caption)
    def eq(text): b("note", text)
    def page(): b("pagebreak")

    b("subtitle", "RELATÓRIO TÉCNICO")
    b("title", "Análise multitemporal de imagens Landsat e avaliação de pastagens")
    b("subtitle", "Projeto Trabalho Evapo")
    p("Processamento de índices de vegetação, propriedades térmicas e componentes do balanço de radiação em área de interesse.")
    p(f"Período das imagens: {dt(first)} a {dt(last)}.")
    p("Data de elaboração: 13 de outubro de 2026.")
    p(f"Execução de referência: {run.name}.")
    b("note", "Documento elaborado a partir do código do projeto, da configuração salva em RES e dos resultados de uma nova execução realizada após revisão dos cálculos, das máscaras e da reprojeção.")
    page()

    b("heading1", "1. Introdução")
    p("O sensoriamento remoto permite caracterizar a distribuição espacial da vegetação e acompanhar diferenças entre aquisições por meio da resposta espectral e térmica da superfície. Em áreas de pastagem, índices de vegetação, albedo, temperatura e radiação oferecem informações complementares para a avaliação ambiental e o planejamento de levantamentos de campo. A interpretação exige considerar a qualidade das imagens, a escala dos sensores e o conjunto de pixels efetivamente observado em cada data.")
    p("O projeto Trabalho Evapo consiste em uma aplicação Python destinada ao processamento de cenas Landsat sobre uma área de interesse comum. O sistema integra seleção de imagens e recortes, calibração radiométrica, cálculo de produtos, consulta de pixels, estatísticas descritivas e exportação de mapas, histogramas, relatórios e animações temporais. Também incorpora camadas MapBiomas para delimitar pastagens e estratificar os resultados por classes anuais de vigor.")
    p(f"Este relatório documenta a metodologia implementada e analisa os resultados de cinco aquisições, entre {dt(first)} e {dt(last)}. Os objetivos específicos são descrever os dados e os parâmetros utilizados, comparar indicadores espectrais e térmicos, examinar a estratificação por vigor e avaliar a cobertura espacial dos produtos. As conclusões têm caráter descritivo e não atribuem causalidade às diferenças entre datas.")
    p("O processamento contempla componentes necessários a estudos de balanço de energia. A estimativa final de evapotranspiração exige etapas adicionais, incluindo fluxos de calor e procedimentos de integração temporal que não compõem os produtos desta execução.")
    b("heading1", "2. Materiais e métodos")
    h("2.1. Dados de entrada e área de estudo")
    p(f"A delimitação foi obtida do projeto salvo em RES. O polígono está em coordenadas geográficas WGS84, aproximadamente entre as longitudes 43,51° O e 43,34° O e as latitudes 21,69° S e 21,49° S. A seleção por centros de pixels contém {br(n_roi, 0)} pixels de 30 m por 30 m, equivalentes a {br(area_roi)} ha na grade projetada. Cada pixel corresponde a 0,09 ha.")
    table(["Aquisição", "Satélite", "Sensores", "Órbita/ponto"],
          [[dt(d), "Landsat 8" if d.startswith("2025") else "Landsat 9", "OLI e TIRS" if d.startswith("2025") else "OLI-2 e TIRS-2", "217/075"] for d in dates])
    b("note", "As datas são de aquisição, conforme os metadados MTL. As datas presentes nos nomes dos empilhamentos podem indicar o processamento do arquivo.")
    page()

    h("2.2. Insumos auxiliares, implementação e controle de qualidade")
    p("Foram utilizados empilhamentos com sete bandas ópticas, banda térmica B10, máscaras QA_PIXEL e QA_RADSAT e metadados MTL de cada cena Level-1. Os coeficientes radiométricos, as constantes térmicas, a elevação solar e a distância Terra-Sol são específicos de cada aquisição. As bandas ópticas são processadas na grade de 30 m. A banda térmica tem resolução instrumental de 100 m e é reamostrada para a grade óptica, sem adquirir detalhe térmico de 30 m [1, 2].")
    p("O modelo de elevação corresponde ao arquivo recorte_srtm_s22_w044_1arc_v3_utm_wgs84.img. As camadas de cobertura e vigor são as registradas como MapBiomas Brasil, Coleção 11, ano de referência 2025. A temperatura do ar informada no projeto é 25 °C e foi aplicada a todas as datas. O SAVI exibido utiliza L = 0,5; o cálculo interno do IAF utiliza L = 0,1.")
    p("A execução utiliza Python 3.14, NumPy e Rasterio para os cálculos e o tratamento geoespacial, Matplotlib e Pillow para as figuras e animações, ReportLab para os relatórios PDF e CustomTkinter para a interface. O manifesto registra processamento OpenCL em GPU NVIDIA GeForce RTX 4060, com precisão intermediária FP64 nas operações compatíveis e produtos exportados em float32. Não foi realizado ensaio de desempenho para quantificar ganho de velocidade.")
    p("O recorte considera os centros dos pixels contidos no polígono. São excluídos preenchimento, nuvem dilatada, cirrus, nuvem e sombra, identificados pelos bits 0 a 4 de QA_PIXEL, além de oclusão de terreno em QA_RADSAT. A saturação é tratada por banda óptica, e valores digitais nulos ou NoData são descartados. Água identificada em QA pode permanecer no NDVI, mas água e neve são excluídas do IAF. A validade de cada produto resulta da combinação de suas entradas e máscaras.")
    h("2.3. Reflectância e índices de vegetação")
    p("A reflectância utilizada nos índices é a reflectância no topo da atmosfera, denominada TOA. O procedimento segue a calibração do produto Level-1, com multiplicador Mρ, termo aditivo Aρ e elevação solar θ obtidos do MTL [1].")
    eq("ρTOA = (Mρ × DN + Aρ) / sen(θ)")
    eq("NDVI = (ρB5 − ρB4) / (ρB5 + ρB4)")
    eq("SAVI = (1 + L) × (ρB5 − ρB4) / (ρB5 + ρB4 + L)")
    p("O NDVI descreve o contraste entre infravermelho próximo e vermelho. O SAVI incorpora um termo de ajuste à influência do solo, sem representar correção atmosférica [3]. Os índices calculados com reflectância TOA permanecem sensíveis às condições de aquisição e da atmosfera.")
    page()

    h("2.3. Reflectância e índices de vegetação, continuação")
    p("O índice de área foliar, IAF, é estimado pela relação empírica implementada a partir do SAVI interno com L = 0,1, de acordo com a parametrização adotada no projeto [6]. Essa escolha independe do L = 0,5 utilizado no SAVI apresentado ao usuário.")
    eq("IAF = −ln[(0,69 − SAVIIAF) / 0,59] / 0,91")
    p("O resultado é fixado em zero para SAVIIAF ≤ 0,1 e em seis para SAVIIAF ≥ 0,687, sendo limitado ao intervalo de zero a seis. A transferência dessa relação para pastagens brasileiras requer validação local. O produto de proporção de vegetação é calculado como o quadrado da razão (NDVI − 0,2)/0,3, limitada previamente entre zero e um. Esse produto é descritivo e não participa do cálculo das emissividades nesta versão.")
    h("2.4. Albedo, temperatura e componentes de radiação")
    p("O albedo TOA combina as reflectâncias B2 a B7 pelos pesos de Silva et al. (2016), tabela 5 [4]. Os pesos são aplicados como publicados, com soma arredondada de 1,001. A banda B1 não integra a combinação. O albedo TOA é limitado entre zero e um.")
    eq("αTOA = 0,300ρB2 + 0,277ρB3 + 0,233ρB4 + 0,143ρB5 + 0,036ρB6 + 0,012ρB7")
    eq("τ = 0,75 + 0,00002z;     αs = (αTOA − 0,03) / τ²")
    p("Na expressão, z representa a altitude em metros e τ a transmissividade atmosférica estimada. O albedo de superfície é limitado entre 0,00001 e um, conforme o modelo local. Trata-se de correção atmosférica simplificada, associada à condição de céu claro. Pixels sem altitude válida permanecem sem resultado.")
    p("As emissividades espectral B10 e de banda larga são calculadas separadamente. Para terreno com NDVI positivo e IAF inferior a três, utilizam-se εB10 = 0,97 + 0,0033IAF e ε0 = 0,95 + 0,01IAF. Para IAF igual ou superior a três, ambas são 0,98. Água identificada por QA recebe 0,99 e 0,985, respectivamente; neve é excluída. Essas relações empíricas requerem avaliação local e espectral.")
    eq("L10 = ML × DN10 + AL;     BT = K2 / ln(K1/L10 + 1)")
    eq("Ts = BT / [1 + (λBT/c2) × ln(εB10)] − 273,15")
    p("BT é calculada em Kelvin. Adotam-se λ = 10,895 × 10⁻⁶ m e c2 = 1,438 × 10⁻² m K. A temperatura da superfície, Ts, é apresentada em graus Celsius após a correção por emissividade. Não se realiza correção atmosférica térmica completa, portanto o resultado deve ser tratado como estimativa [1, 7].")
    page()

    h("2.4. Componentes de radiação, continuação")
    p("A distância Terra-Sol d, em unidades astronômicas, é obtida prioritariamente do MTL. O fator dr = 1/d² é aplicado à irradiância e não é reaplicado à reflectância calibrada. A planilha solar fornecida com o projeto permite conferir a distância por dia do ano. As equações radiativas utilizam a constante de Stefan-Boltzmann σ = 5,67 × 10⁻⁸ W m⁻² K⁻⁴ e temperatura do ar Ta = 298,15 K.")
    eq("Rs↓ = 1367 × sen(θ) × dr × τ")
    eq("εatm = 0,85 × [−ln(τ)]^(0,09)")
    eq("Rl↓ = εatm × σ × Ta⁴;     Rl↑ = ε0 × σ × (Ts + 273,15)⁴")
    eq("Rn = (1 − αs)Rs↓ + Rl↓ − Rl↑ − (1 − ε0)Rl↓")
    p("Rs↓ representa a radiação de onda curta incidente; Rl↓ e Rl↑ representam a onda longa incidente e emitida; Rn é o saldo de radiação. Todos esses produtos são instantâneos, expressos em W/m². A temperatura do ar fixa constitui parâmetro de entrada e não uma medição meteorológica específica de cada aquisição.")
    h("2.5. Análise de pastagens e estatísticas")
    p("As pastagens são delimitadas pelo código 15 da camada de cobertura. A camada anual de vigor fornece as classes baixo, moderado e alto, registradas como códigos 1, 2 e 3. O produto MapBiomas é uma classificação anual e não é recalculado a partir do NDVI de cada cena [5]. A mesma referência de 2025 foi aplicada também às imagens de 2026. As camadas categóricas são alinhadas por vizinho mais próximo.")
    p("As estatísticas são calculadas na resolução nativa, sobre pixels finitos de cada produto, para a ROI e para a interseção entre ROI, pastagem e classe de vigor. São utilizados média, desvio padrão populacional, variância, mínimo, máximo, mediana e percentis. Os percentis representam a distribuição espacial dos pixels; não constituem intervalos de confiança. A área válida é obtida multiplicando o número de pixels válidos por 0,09 ha.")
    p("A cobertura percentual corresponde ao número de pixels válidos dividido pelo total de pixels da área ou da classe em análise. Portanto, esse percentual mede disponibilidade de observações, e não cobertura vegetal. As estatísticas da ROI foram extraídas de estatisticas_todas_cenas_roi.csv; a análise por classe utiliza estatisticas_por_vigor.csv. Os mapas completos existentes na pasta pastagens não devem ser interpretados automaticamente como mapas mascarados apenas às pastagens.")
    h("2.6. Revisão do código antes da reexecução")
    p("Antes do processamento, foram conferidos índices, emissividades, radiações, leitura de rasters, máscaras e integração CPU/GPU. Os 38 testes executados nas rotinas correspondentes passaram. Para o MDE, a leitura WarpedVRT foi comparada com reproject e com um controle geométrico independente. As máscaras coincidiram e a diferença máxima de altitude foi zero. Essa verificação não identificou falha de reprojeção capaz de explicar a ausência de resultados no norte da ROI.")
    page()

    b("heading1", "3. Resultados")
    h("3.1. Produtos gerados e síntese da área total")
    p("A reexecução gerou 17 produtos por data, totalizando 85 combinações de data e produto na análise geral. A análise de pastagens contém 255 combinações de data, produto e classe de vigor. Foram exportados rasters numéricos, tabelas CSV, mapas, histogramas, relatórios PDF e HTML e animações temporais da análise geral. O projeto salvo recebeu a referência à nova execução.")
    table(["Data", "NDVI", "SAVI", "IAF (m²/m²)", "Ts (°C)", "Rn (W/m²)"],
          [[dt(d), br(val(d,"ndvi"),3), br(val(d,"savi"),3), br(val(d,"iaf"),3),
            br(val(d,"temperatura_superficie")), br(val(d,"saldo_radiacao"))] for d in dates])
    b("caption", "Tabela 1. Médias da ROI, calculadas separadamente sobre os pixels válidos de cada produto.")
    peak = max(dates, key=lambda d: val(d, "ndvi"))
    low = min(dates, key=lambda d: val(d, "ndvi"))
    p(f"O maior NDVI médio ocorreu em {dt(peak)}, com {br(val(peak,'ndvi'),3)}, e o menor em {dt(low)}, com {br(val(low,'ndvi'),3)}. Entre a primeira e a última aquisição, a média passou de {br(val(first,'ndvi'),3)} para {br(val(last,'ndvi'),3)}, diferença de {br(val(last,'ndvi')-val(first,'ndvi'),3)}. Essa comparação descreve as observações disponíveis e não representa uma tendência contínua ao longo de todo o período.")
    p("NDVI, SAVI e IAF compartilham as bandas vermelho e infravermelho próximo. A concordância entre eles não constitui validação independente da estimativa de área foliar.")
    p("Em 18/07/2025, a menor cobertura válida pode afetar a comparação das médias. Recomenda-se analisar também uma interseção comum de pixels válidos entre datas.")
    h("3.2. Distribuição espacial do NDVI")
    image("mapas_ndvi.png", "Figura 1. NDVI da ROI em três aquisições, com a mesma escala de cores. Áreas sem observação válida são apresentadas em cinza.", 15.8)
    page()

    h("3.3. Estratificação das pastagens por vigor")
    p(f"A camada de referência identifica {br(n_pasture,0)} pixels de pastagem, equivalentes a {br(n_pasture*0.09)} ha e {br(100*n_pasture/n_roi)}% da ROI. A composição por vigor é constante entre datas, pois a classificação anual de 2025 permanece fixa. Foram registrados dois pixels de pastagem sem classe de vigor, correspondentes a 0,18 ha.")
    table(["Vigor", "Pixels", "Área (ha)", "% da pastagem"],
          [[g.capitalize(),br(class_counts[g],0),br(class_counts[g]*0.09),br(100*class_counts[g]/n_pasture)] for g in classes]
          + [["Sem classe", "2", "0,18", br(200/n_pasture,4)]])
    b("caption", "Tabela 2. Área de pastagem por classe anual de vigor. Percentuais calculados sobre toda a pastagem identificada.")
    image("vigor_cobertura.png", "Figura 2. Classes de vigor de 2025 e disponibilidade de transmissividade na primeira aquisição. Eixos expressam distâncias relativas na grade; a porção superior corresponde ao norte.", 15.3)
    p("A distribuição do vigor deve ser interpretada em conjunto com a cobertura do MDE. As classes não possuem a mesma proporção de área com altitude disponível. Isso limita comparações de produtos radiativos que dependem do relevo e impede estender suas médias a toda a área de cada classe.")
    page()

    h("3.3. Indicadores espectrais por classe de vigor")
    table(["Data", "Baixo", "Moderado", "Alto"],
          [[dt(d)] + [br(val(d,"ndvi",group=g),3) for g in classes] for d in dates])
    b("caption", "Tabela 3. NDVI médio por classe anual de vigor de pastagem.")
    image("indices_temporais.png", "Figura 3. Médias de NDVI e SAVI na ROI e nas classes de vigor. O eixo apresenta apenas as datas analisadas; as linhas conectam observações e não representam interpolação temporal.", 15.8)
    ordered = all(val(d,"ndvi",group="baixo") < val(d,"ndvi",group="moderado") < val(d,"ndvi",group="alto") for d in dates)
    if ordered:
        p("Em todas as aquisições, o NDVI médio apresentou a ordenação baixo, moderado e alto. Esse comportamento é compatível com diferenças no sinal espectral da vegetação entre os estratos anuais, mas não comprova a condição instantânea de manejo ou a produtividade das pastagens.")
    else:
        p("A comparação das médias mostra diferenças entre as classes anuais de vigor. A ordenação espectral não é necessariamente constante em todas as aquisições, pois as classes representam a referência anual e os índices respondem às condições de cada data.")
    p("Sazonalidade, manejo, condições atmosféricas e participação do solo no pixel são hipóteses possíveis para as diferenças observadas. Os arquivos analisados não incluem medições de campo ou séries meteorológicas que permitam separar quantitativamente essas contribuições.")
    page()

    h("3.4. Temperatura e componentes do balanço de radiação")
    table(["Data", "α superfície", "Rs↓ (W/m²)", "Rl↑ (W/m²)", "Rl↓ (W/m²)"],
          [[dt(d),br(val(d,"albedo_superficie"),3),br(val(d,"radiacao_curta_incidente")),
            br(val(d,"radiacao_longa_emitida")),br(val(d,"radiacao_longa_incidente"))] for d in dates])
    b("caption", "Tabela 4. Médias dos componentes radiativos. Cada coluna utiliza sua própria máscara de validade.")
    hot = max(dates,key=lambda d:val(d,"temperatura_superficie"))
    cold = min(dates,key=lambda d:val(d,"temperatura_superficie"))
    radmax = max(dates,key=lambda d:val(d,"saldo_radiacao"))
    p(f"A temperatura média estimada da superfície variou de {br(val(cold,'temperatura_superficie'))} °C, em {dt(cold)}, a {br(val(hot,'temperatura_superficie'))} °C, em {dt(hot)}. O maior saldo médio de radiação ocorreu em {dt(radmax)}, com {br(val(radmax,'saldo_radiacao'))} W/m². A temperatura da superfície é obtida independentemente do MDE nesta implementação, enquanto o saldo de radiação depende da altitude e representa uma parcela menor da ROI.")
    image("temperatura_radiacao.png", "Figura 4. Médias de temperatura da superfície e saldo de radiação nas datas disponíveis. Os dois produtos possuem suportes espaciais distintos.", 15.8)
    p("A variação da onda curta incidente resulta, em parte, da elevação solar, da distância Terra-Sol e da transmissividade adotadas para cada cena. A onda longa incidente utiliza a mesma temperatura do ar de 25 °C em todas as datas. Dessa forma, diferenças entre aquisições combinam as condições de entrada e a resposta dos pixels válidos, sem permitir atribuição isolada ao vigor da pastagem.")
    p("O balanço deve ser verificado pixel a pixel. Não se deve exigir fechamento por substituição direta das médias da tabela nas equações, pois os termos podem ter máscaras distintas e as médias dos produtos de variáveis não equivalem aos produtos de suas médias.")
    page()

    h("3.5. Cobertura válida e efeito da extensão do MDE")
    p(f"A auditoria identificou altitude disponível em {br(audit['comparacao']['pixels_validos_roi'],0)} pixels da ROI, equivalentes a {br(audit['comparacao']['pixels_validos_roi']*0.09)} ha e {br(100*audit['comparacao']['pixels_validos_roi']/n_roi)}% da área. Esse limite precede as máscaras de nuvem e qualidade. O recorte de elevação alcança a parte sul da ROI; a parte norte está fora de sua extensão.")
    table(["Data", "NDVI (%)", "Ts (%)", "α superfície (%)", "Rn (%)"],
          [[dt(d)] + [br(val(d,p,"cobertura_percentual")) for p in ["ndvi","temperatura_superficie","albedo_superficie","saldo_radiacao"]] for d in dates])
    b("caption", "Tabela 5. Cobertura válida por produto, relativa ao total de 411.387 pixels da ROI.")
    image("cobertura_valida.png", "Figura 5. Disponibilidade espacial de três produtos. A linha pontilhada indica o limite físico de cobertura do MDE na ROI, antes das demais máscaras.", 15.8)
    p("Antes dos filtros QA, o MDE abrange 78,47% da classe de baixo vigor, 44,80% da classe moderada e 15,94% da classe de alto vigor. A cobertura desigual decorre da posição espacial dessas classes. As médias de albedo de superfície e radiação em alto vigor, por exemplo, descrevem apenas a pequena parcela da classe com altitude disponível.")
    p("Os dados do MDE existente são válidos dentro de sua extensão. A limitação não foi produzida por falha de reprojeção ou conversão entre os sistemas de coordenadas examinados. A grade Landsat registra EPSG:32623 com coordenadas norte negativas, e o MDE registra EPSG:32723; a comparação independente confirmou o alinhamento físico adotado. Para ampliar a cobertura, é necessário um MDE com extensão suficiente, seguido de novo processamento.")
    page()

    h("3.6. Síntese dos demais produtos")
    products_all = [
        ("albedo_toa","Albedo TOA",3), ("proporcao_vegetacao","Proporção de vegetação",3),
        ("emissividade_b10","Emissividade B10",4), ("emissividade","Emissividade de banda larga",4),
        ("radiancia_b10","Radiância B10¹",3), ("temperatura_brilho","Temperatura de brilho (K)",2),
        ("transmissividade","Transmissividade",4), ("emissividade_atmosferica","Emissividade atmosférica",4)]
    table(["Produto"] + [date.fromisoformat(d).strftime("%d/%m/%y") for d in dates],
          [[name] + [br(val(d,pname),digits) for d in dates] for pname,name,digits in products_all],
          widths_cm=[4.3, 2.42, 2.42, 2.42, 2.42, 2.42])
    b("caption", "Tabela 6. Médias de produtos complementares da ROI. Grandezas sem unidade explícita são adimensionais. ¹ Radiância em W/(m² sr µm).")
    p("A proporção de vegetação deriva do NDVI, e as emissividades derivam do IAF e das regras para água e neve. Como compartilham entradas e relações matemáticas, esses produtos não constituem observações independentes.")
    p("A transmissividade e a emissividade atmosférica refletem a parametrização com altitude. Médias semelhantes entre datas podem envolver máscaras diferentes e não comprovam estabilidade das condições atmosféricas reais.")
    h("3.7. Limitações e alcance da interpretação")
    p("A série possui somente cinco aquisições, com intervalos desiguais e duas plataformas orbitais. As comparações utilizam reflectância TOA e não incorporam normalização atmosférica completa entre cenas. A parametrização do albedo foi proposta para OLI/Landsat 8 e aplicada também a OLI-2/Landsat 9 nesta implementação, sem avaliação independente de equivalência no presente estudo.")
    p("A referência de vigor de 2025 não permite afirmar mudança de classe entre 2025 e 2026. O IAF e as emissividades utilizam relações empíricas cuja aplicação local ainda precisa ser validada. A temperatura de superfície não equivale a uma medição de campo nem ao produto oficial de temperatura Level-2. As radiações são estimativas instantâneas de céu claro e não totais diários de energia.")
    p("O conjunto processado permite descrever padrões espaciais e diferenças observadas. A atribuição de degradação, recuperação, estresse hídrico, produtividade ou consumo de água exigiria informações complementares e um desenho de validação apropriado.")
    page()

    b("heading1", "4. Conclusão")
    p("O projeto Trabalho Evapo integrou o processamento de imagens Landsat, índices de vegetação, propriedades térmicas, componentes de radiação e estratificação de pastagens em um fluxo reproduzível. A revisão prévia do código, os testes automatizados e a comparação independente da reprojeção do MDE não identificaram falha responsável pelas lacunas espaciais examinadas. A nova execução foi concluída com os parâmetros do projeto salvo.")
    p(f"Na área de {br(area_roi)} ha, as pastagens de referência ocupam {br(n_pasture*0.09)} ha. A classe moderada é predominante, com {br(class_counts['moderado']*0.09)} ha e {br(100*class_counts['moderado']/n_pasture)}% da área de pastagem. Os indicadores espectrais apresentam diferenças entre datas e entre estratos de vigor, cujo significado deve ser limitado às observações e às condições de processamento disponíveis.")
    p(f"O NDVI médio da ROI atingiu seu maior valor em {dt(peak)}, enquanto o maior saldo médio de radiação foi observado em {dt(radmax)}. Esses resultados não estabelecem uma relação causal entre vegetação e energia, porque os produtos utilizam entradas, máscaras e suportes espaciais distintos.")
    p("A principal restrição espacial dos produtos dependentes de altitude é a extensão do MDE, que cobre aproximadamente metade da ROI e proporções muito diferentes das classes de vigor. A estimativa quantitativa de albedo e radiação para toda a área requer ampliar o modelo de elevação. Para fortalecer a análise temporal, recomenda-se utilizar máscaras comuns entre datas, temperatura do ar correspondente às aquisições e validação com dados de campo.")
    p("Os resultados constituem uma base técnica para caracterização espectral, térmica e radiativa da área e para orientar verificações posteriores. A estimativa de evapotranspiração permanece como etapa adicional de desenvolvimento, condicionada à implementação e validação dos demais componentes do balanço de energia.")
    h("Rastreabilidade dos arquivos")
    p(f"Pasta da execução: RES/execucoes/{run.name}. As subpastas roi e pastagens contêm os dados numéricos e as exportações. O arquivo configuracao.evapo.json registra os parâmetros utilizados, e processamento.log documenta o processamento. A nova execução também está referenciada no projeto salvo em RES.")
    p("Fontes locais principais: README.md; src/evapo/calculos/indices.py, albedo.py, reflectancia.py e energia.py; src/evapo/analises/processamento.py e pastagens.py; manifestos e CSVs da execução. A auditoria de alinhamento está registrada em auditoria_mde.json, produzida antes da reexecução.")
    page()

    h("Referências")
    refs = [
        "[1] USGS. Using the USGS Landsat Level-1 Data Product. Calibração de radiância, reflectância TOA e temperatura de brilho. https://www.usgs.gov/landsat-missions/using-usgs-landsat-level-1-data-product",
        "[2] USGS. What are the band designations for the Landsat satellites? Resoluções das bandas ópticas e térmicas. https://www.usgs.gov/faqs/what-are-band-designations-landsat-satellites",
        "[3] HUETE, A. R. A soil-adjusted vegetation index (SAVI). Remote Sensing of Environment, v. 25, n. 3, p. 295 a 309, 1988. DOI: 10.1016/0034-4257(88)90106-X. Formulação consultada também em USGS: https://www.usgs.gov/landsat-missions/landsat-soil-adjusted-vegetation-index",
        "[4] SILVA, B. B. da et al. Procedures for calculation of the albedo with OLI-Landsat 8 images: Application to the Brazilian semi-arid. Revista Brasileira de Engenharia Agrícola e Ambiental, v. 20, n. 1, p. 3 a 8, 2016. Tabela 5. https://doi.org/10.1590/1807-1929/agriambi.v20n1p3-8",
        "[5] MAPBIOMAS BRASIL. Condição de vigor da pastagem. Classificação e referência anual. https://brasil.mapbiomas.org/iniciativas-e-produtos/cobertura-e-uso-da-terra/pastagem/condicao-de-vigor/",
        "[6] WATERS, R.; ALLEN, R.; BASTIAANSSEN, W.; TASUMI, M.; TREZZA, R. SEBAL: Surface Energy Balance Algorithms for Land. Advanced Training and Users Manual, versão 1.0, 2002. Referência metodológica registrada no projeto. https://posmet.ufv.br/wp-content/uploads/2017/04/MET-479-Waters-et-al-SEBAL.pdf",
        "[7] ISAYA NDOSSI, M.; AVDAN, U. Application of Open Source Coding Technologies in the Production of Land Surface Temperature (LST) Maps from Landsat: A PyQGIS Plugin. Remote Sensing, v. 8, n. 5, artigo 413, 2016. https://doi.org/10.3390/rs8050413",
        "[8] TRABALHO EVAPO. Código-fonte, documentação e projeto salvo, versão de software 0.1.0, metodologia 2. Execução de 13/10/2026. Fontes locais descritas na seção de rastreabilidade.",
    ]
    for ref in refs:
        p(ref)
    b("note", "As fontes institucionais e os artigos identificam os fundamentos metodológicos. Os valores apresentados neste relatório foram obtidos exclusivamente dos arquivos numéricos da nova execução.")

    # Guarda o conteúdo estruturado para revisão, sem depender da interpretação do Word.
    for block in blocks:
        serialized = json.dumps(block, ensure_ascii=False)
        if "\u2013" in serialized or "\u2014" in serialized:
            raise ValueError("O relatório contém travessão ou meia-risca.")
    content_path = out.with_suffix(".conteudo.json")
    content_path.write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    build_docx(blocks, out, title="Relatório técnico do projeto Trabalho Evapo")
    print(json.dumps({"docx": str(out), "conteudo": str(content_path), "blocos": len(blocks),
                      "figuras": len(list(figs.glob('*.png'))), "datas": dates,
                      "execucao": str(run), "tamanho_bytes": out.stat().st_size}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
