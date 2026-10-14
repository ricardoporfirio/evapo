"""Relatório interpretativo em PDF, a partir dos resultados já calculados."""

import csv
import html
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import matplotlib
from PIL import Image as ImagemPIL
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, KeepTogether, LongTable, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, TableStyle,
)

from evapo.relatorios.interpretacao import (
    REFERENCIAS, interpretar_pastagens, interpretar_registro,
    interpretar_temporal, teorias_produtos,
)

AZUL = colors.HexColor("#1e5b78")
TEXTO = colors.HexColor("#203744")
CLARO = colors.HexColor("#eef4f7")


def _numero(valor):
    if isinstance(valor, bool):
        return None
    if isinstance(valor, str):
        valor = valor.strip().replace(",", ".")
    try:
        numero = float(valor)
        return numero if math.isfinite(numero) else None
    except (TypeError, ValueError):
        return None


def _formatar(valor, casas=4):
    numero = _numero(valor)
    return f"{numero:.{casas}f}".replace(".", ",") if numero is not None else "Sem dados"


def _data(valor):
    try:
        return date.fromisoformat(str(valor)).strftime("%d/%m/%Y")
    except ValueError:
        return str(valor)


def _ler_csv(caminho):
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        return list(csv.DictReader(arquivo, delimiter=";"))


def _estilos():
    fontes = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    for nome, arquivo in (
        ("Evapo", "DejaVuSans.ttf"),
        ("Evapo-Bold", "DejaVuSans-Bold.ttf"),
        ("Evapo-Italic", "DejaVuSans-Oblique.ttf"),
    ):
        if nome not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(nome, str(fontes / arquivo)))
    pdfmetrics.registerFontFamily(
        "Evapo", normal="Evapo", bold="Evapo-Bold", italic="Evapo-Italic",
        boldItalic="Evapo-Bold",
    )
    estilos = getSampleStyleSheet()
    estilos.add(ParagraphStyle(
        "TextoEvapo", fontName="Evapo", fontSize=9, leading=14,
        textColor=TEXTO, spaceAfter=8,
    ))
    estilos.add(ParagraphStyle(
        "TituloEvapo", parent=estilos["TextoEvapo"], fontName="Evapo-Bold",
        fontSize=23, leading=30, textColor=AZUL, spaceAfter=16,
    ))
    estilos.add(ParagraphStyle(
        "SecaoEvapo", parent=estilos["TextoEvapo"], fontName="Evapo-Bold",
        fontSize=14, leading=20, textColor=AZUL, spaceBefore=14,
        spaceAfter=10, keepWithNext=True,
    ))
    estilos.add(ParagraphStyle(
        "SubtituloEvapo", parent=estilos["SecaoEvapo"], fontSize=10, leading=15,
    ))
    estilos.add(ParagraphStyle(
        "TabelaEvapo", parent=estilos["TextoEvapo"], fontSize=7, leading=10,
        spaceAfter=0,
    ))
    estilos.add(ParagraphStyle(
        "LegendaEvapo", parent=estilos["TextoEvapo"], fontSize=7.5,
        leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#526b79"),
    ))
    return estilos


class DocumentoPDF:
    def __init__(self):
        self.estilos = _estilos()
        self.conteudo = []
        self.largura = A4[0] - 3.6 * cm

    def texto(self, texto, estilo="TextoEvapo"):
        self.conteudo.append(self.paragrafo(texto, estilo))

    def paragrafo(self, texto, estilo="TextoEvapo"):
        return Paragraph(html.escape(str(texto)).replace("\n", "<br/>"), self.estilos[estilo])

    def secao(self, titulo):
        self.texto(titulo, "SecaoEvapo")

    def tabela(self, cabecalho, linhas, larguras=None):
        dados = [
            [self.paragrafo(c, "TabelaEvapo") for c in cabecalho],
            *[[self.paragrafo(c, "TabelaEvapo") for c in linha] for linha in linhas],
        ]
        tabela = LongTable(dados, colWidths=larguras, repeatRows=1, hAlign="LEFT")
        tabela.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), CLARO),
            ("TEXTCOLOR", (0, 0), (-1, 0), AZUL),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.7, AZUL),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#dce5eb")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        self.conteudo.extend([tabela, Spacer(1, 10)])

    def figura(self, caminho, legenda):
        if not caminho.is_file():
            self.texto(f"Figura não disponível: {legenda}.")
            return
        with ImagemPIL.open(caminho) as imagem:
            largura, altura = imagem.size
        fator = min(self.largura / largura, 8.8 * cm / altura)
        figura = Image(str(caminho), width=largura * fator, height=altura * fator)
        self.conteudo.append(KeepTogether([
            figura, self.paragrafo(legenda, "LegendaEvapo"), Spacer(1, 8),
        ]))

    def salvar(self, destino, titulo):
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(f".{destino.stem}_{uuid4().hex}.pdf.tmp")

        def rodape(canvas, documento):
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor("#dce5eb"))
            canvas.line(1.8 * cm, 1.4 * cm, A4[0] - 1.8 * cm, 1.4 * cm)
            canvas.setFont("Evapo", 7)
            canvas.setFillColor(TEXTO)
            canvas.drawString(1.8 * cm, 1 * cm, "EVAPO · Análise Landsat e interpretação teórica")
            canvas.drawRightString(A4[0] - 1.8 * cm, 1 * cm, f"Página {documento.page}")
            canvas.restoreState()

        try:
            documento = SimpleDocTemplate(
                str(temporario), pagesize=A4, rightMargin=1.8 * cm,
                leftMargin=1.8 * cm, topMargin=1.8 * cm, bottomMargin=2 * cm,
                title=titulo, author="Evapo", subject="Resultados Landsat, teoria e interpretação",
            )
            documento.build(self.conteudo, onFirstPage=rodape, onLaterPages=rodape)
            temporario.replace(destino)
        finally:
            temporario.unlink(missing_ok=True)
        return destino


def _pasta_registro(pasta, registro):
    """Aceita somente os nomes locais produzidos pelo processamento."""
    componentes = [str(registro["data"])]
    if registro.get("vigor"):
        componentes.append(str(registro["vigor"]))
    componentes.append(str(registro["produto"]))
    if any(c in ("", ".", "..") or "/" in c or "\\" in c for c in componentes):
        raise ValueError("O CSV contém um nome de data, classe ou produto inválido.")
    return pasta.joinpath(*componentes[:-1]), componentes[-1]


def _datas_compativeis_manifestos(manifesto_pastagens, pasta_geral):
    """Autoriza figuras externas apenas com área, cálculo e grade equivalentes."""
    arquivo = pasta_geral / "manifesto_roi.json"
    if not arquivo.is_file():
        return set()
    try:
        manifesto_geral = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(manifesto_geral, dict) or not isinstance(manifesto_pastagens, dict):
        return set()
    configuracao = manifesto_pastagens.get("configuracao")
    if not isinstance(configuracao, dict):
        return set()
    if "roi" not in manifesto_pastagens or "roi" not in manifesto_geral:
        return set()
    if manifesto_pastagens["roi"] != manifesto_geral["roi"]:
        return set()
    parametros_pastagens = {**manifesto_pastagens, **configuracao}
    if "L" not in parametros_pastagens or "L" not in manifesto_geral:
        return set()
    parametros = (
        "L", "mde", "temperatura_ar_c", "metodologia_versao", "L_iaf",
        "modelo_albedo", "pesos_albedo_toa", "modelos_energia", "modelo_solar",
    )
    if any(parametros_pastagens.get(c) != manifesto_geral.get(c) for c in parametros):
        return set()
    grades_pastagens = manifesto_pastagens.get("grades", [])
    grades_geral = manifesto_geral.get("cenas", [])
    if not isinstance(grades_pastagens, list) or not isinstance(grades_geral, list):
        return set()
    if any(not isinstance(g, dict) or not g.get("data") for g in grades_pastagens + grades_geral):
        return set()
    por_data_pastagens = {g["data"]: g for g in grades_pastagens}
    por_data_geral = {g["data"]: g for g in grades_geral}
    if len(por_data_pastagens) != len(grades_pastagens) or len(por_data_geral) != len(grades_geral):
        return set()
    compativeis = set()
    for dia in por_data_pastagens.keys() & por_data_geral.keys():
        pastagem, geral = por_data_pastagens[dia], por_data_geral[dia]
        transformacao = pastagem.get("transform")
        if not pastagem.get("crs") or not isinstance(transformacao, list) or len(transformacao) < 6:
            continue
        if any(_numero(v) is None for v in transformacao):
            continue
        # CRS e transformação sem dimensões não comprovam a mesma extensão.
        janela = pastagem.get("janela") or {}
        forma = pastagem.get("shape")
        forma_valida = isinstance(forma, list) and len(forma) == 2 and all(
            (_numero(v) or 0) > 0 for v in forma
        )
        janela_valida = isinstance(janela, dict) and all(
            (_numero(janela.get(c)) or 0) > 0 for c in ("width", "height")
        )
        if not forma_valida and not janela_valida:
            continue
        campos_grade = (
            "crs", "transform", "shape", "janela", "bounds", "width", "height",
            "satelite", "solar", *parametros[3:],
        )
        if all(pastagem.get(c) == geral.get(c) for c in campos_grade):
            compativeis.add(dia)
    return compativeis


def _figuras_produtos_pastagens(pasta, registros, imagem_inteira, manifesto):
    """Localiza exportações completas, inclusive nas análises gerais antigas."""
    chaves = sorted({(r["data"], r["produto"]) for r in registros})
    pasta_geral = pasta.parent / ("imagem_completa" if imagem_inteira else "roi")
    datas_compativeis = _datas_compativeis_manifestos(manifesto, pasta_geral)
    fontes = [pasta]
    if pasta_geral != pasta and datas_compativeis:
        fontes.append(pasta_geral)
    estatisticas = {}
    for fonte in fontes:
        por_produto = {}
        for nome_csv in ("estatisticas_todas_cenas_roi.csv", "estatisticas_produtos.csv"):
            arquivo = fonte / nome_csv
            if arquivo.is_file():
                for registro in _ler_csv(arquivo):
                    if not {"data", "produto", "pixels_validos"}.issubset(registro) or registro.get("vigor"):
                        continue
                    if fonte != pasta and registro["data"] not in datas_compativeis:
                        continue
                    _pasta_registro(fonte, registro)
                    por_produto[(registro["data"], registro["produto"])] = registro
        for dia in sorted({dia for dia, _ in chaves}):
            if fonte != pasta and dia not in datas_compativeis:
                continue
            # estatisticas.csv na análise de pastagens contém classes de vigor.
            nomes_csv = ("estatisticas_produtos.csv",) if fonte == pasta else (
                "estatisticas.csv", "estatisticas_produtos.csv",
            )
            for nome_csv in nomes_csv:
                arquivo = fonte / dia / nome_csv
                if arquivo.is_file():
                    for registro in _ler_csv(arquivo):
                        registro = {"data": dia, **registro}
                        if not {"produto", "pixels_validos"}.issubset(registro) or registro.get("vigor"):
                            continue
                        _pasta_registro(fonte, registro)
                        por_produto[(registro["data"], registro["produto"])] = registro
        estatisticas[fonte] = por_produto
    figuras = []
    for dia, produto in chaves:
        fontes_data = [f for f in fontes if f == pasta or dia in datas_compativeis]
        fonte = next(
            (f for f in fontes_data if (f / dia / f"{produto}_mapa.png").is_file()),
            next((f for f in fontes_data if (f / dia / f"{produto}_histograma.png").is_file()), pasta),
        )
        figuras.append((dia, produto, fonte / dia, estatisticas[fonte].get((dia, produto))))
    return figuras


def gerar_pdf_da_pasta(pasta, destino, projeto=None):
    """Gera PDF com CSV, manifesto e PNG existentes, sem abrir imagens Landsat."""
    pasta = Path(pasta)
    pastagens = (pasta / "estatisticas_por_vigor.csv").is_file()
    arquivo_csv = pasta / (
        "estatisticas_por_vigor.csv" if pastagens else "estatisticas_todas_cenas_roi.csv"
    )
    if not arquivo_csv.is_file():
        raise ValueError("Selecione uma análise com estatísticas salvas para gerar o PDF.")
    registros = _ler_csv(arquivo_csv)
    if not registros or any(not {"data", "produto", "pixels_validos"}.issubset(r) for r in registros):
        raise ValueError("A análise não contém registros estatísticos válidos para o PDF.")
    for registro in registros:
        _pasta_registro(pasta, registro)
    arquivo_manifesto = pasta / ("manifesto.json" if pastagens else "manifesto_roi.json")
    manifesto = json.loads(arquivo_manifesto.read_text(encoding="utf-8")) if arquivo_manifesto.is_file() else {}
    configuracao = manifesto.get("configuracao", {}) if pastagens else manifesto
    metodologia_versao = manifesto.get("metodologia_versao", configuracao.get("metodologia_versao"))
    teorias = teorias_produtos(metodologia_versao)
    resolucao = str(configuracao.get("resolucao", ""))
    area_manifesto = str(configuracao.get("area_analise", ""))
    imagem_inteira = (
        "imagem inteira" in resolucao.lower() or "imagem inteira" in area_manifesto.lower()
        or pasta.name in ("imagem_completa", "pastagens_imagem_completa")
        or any("imagem inteira" in str(r.get("base_area", "")).lower() for r in registros)
    )
    area = "Imagem inteira" if imagem_inteira else "Área de interesse (ROI)"
    titulo = f"Relatório interpretativo Landsat — {'Pastagens · ' if pastagens else ''}{area}"
    documento = DocumentoPDF()
    documento.texto("EVAPO", "SubtituloEvapo")
    documento.texto(titulo, "TituloEvapo")
    if projeto and projeto.get("nome"):
        documento.texto(f"Projeto: {projeto['nome']}")
    datas = sorted({r["data"] for r in registros})
    documento.texto(f"Período: {_data(datas[0])} a {_data(datas[-1])} · {len(datas)} datas analisadas")
    agora = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-3)))
    documento.texto(f"Emissão: {agora:%d/%m/%Y às %H:%M} (UTC−3)")
    documento.texto(
        "Este relatório associa as estatísticas calculadas à teoria do sensoriamento remoto. "
        "As interpretações descrevem padrões compatíveis com os índices; mudanças observadas "
        "não estabelecem, isoladamente, suas causas. As figuras são as exportações da análise salva."
    )
    documento.secao("1. Síntese interpretativa e comparação temporal")
    for texto in interpretar_temporal(registros, imagem_inteira=imagem_inteira):
        documento.texto(texto)
    documento.texto(
        "O aumento ou a redução de um índice não comprova sozinho degradação, produtividade, "
        "disponibilidade hídrica ou alteração da evapotranspiração. A interpretação conjunta "
        "deve considerar o uso do solo, a época do ano, a qualidade das observações e dados de campo."
    )
    if pastagens:
        for texto in interpretar_pastagens(configuracao):
            documento.texto(texto)

    documento.secao("2. Dados e método de cálculo")
    if metodologia_versao == 2:
        documento.texto(
            "Metodologia da execução: versão 2. Albedo TOA com pesos OLI B2 a B7 de Silva et al. (2016); "
            "IAF com SAVI interno L = 0,1; emissividades espectral B10 e de banda larga calculadas separadamente."
        )
    else:
        documento.texto(
            "A versão metodológica corrigida não está identificada neste manifesto. "
            "As fórmulas anteriores documentadas são apresentadas como referência histórica; "
            "não comprovam os parâmetros efetivos desta execução. Os CSV e rasters salvos "
            "não são recalculados ao gerar o PDF. Reprocesse as cenas para aplicar a metodologia 2."
        )
    documento.texto(
        "A análise usa os empilhamentos Landsat B1 a B7 e os coeficientes radiométricos MTL. "
        "A reflectância é calculada no topo da atmosfera (TOA): "
        "rho = (MULT × DN + ADD) / sen(elevação solar). "
        "NDVI e SAVI deste projeto usam essa reflectância TOA; não são produtos oficiais "
        "de reflectância de superfície Level-2."
    )
    documento.texto(
        "As estatísticas são calculadas sobre os pixels finitos da grade nativa, após as "
        "máscaras de qualidade, saturação e área. Na ROI, considera-se o centro do pixel "
        "dentro do desenho. Cobertura válida é a fração da área analisada com observações "
        "válidas para o produto, não a fração de vegetação. Desvio padrão e variância são "
        "populacionais; os percentis descrevem a distribuição espacial e não intervalos de confiança."
    )
    if imagem_inteira:
        documento.texto(
            "Cada data abrange a imagem inteira correspondente. Diferenças de extensão e de "
            "pixels disponíveis podem alterar a população comparada entre datas."
        )
    valor_l = _numero(configuracao.get("L"))
    documento.texto(f"Parâmetro L do SAVI exibido: {_formatar(valor_l, 2) if valor_l is not None else 'não informado no manifesto'}.")
    if metodologia_versao == 2:
        documento.texto(
            "O IAF usa SAVI calculado internamente com L = 0,1, independente do L do SAVI exibido. "
            "A relação foi calibrada no sul de Idaho e sua transferência para pastagens brasileiras "
            "precisa de validação local antes de uma leitura quantitativa."
        )
    else:
        documento.texto(
            "A relação empírica SAVI–IAF do manual SEBAL apresenta calibração com L = 0,1. "
            "Na formulação anterior o IAF usava o SAVI com o L da execução; esse parâmetro "
            "deve ser confrontado com a calibração original. "
            "O IAF é uma estimativa empírica e precisa de validação local antes de uma leitura quantitativa."
        )
    documento.texto(
        f"Modelo de elevação: {Path(configuracao['mde']).name if configuracao.get('mde') else 'não informado no manifesto'}."
    )
    if not any(r["produto"] == "albedo_superficie" for r in registros):
        documento.texto(
            "Albedo da superfície não consta dos resultados. A correção exige um MDE; "
            "o albedo TOA disponível não deve ser interpretado como albedo de superfície."
        )
    if configuracao.get("modelos_energia"):
        documento.texto(f"Modelos térmicos e radiativos: {configuracao['modelos_energia']}.")
        temperatura_ar = _numero(configuracao.get("temperatura_ar_c"))
        documento.texto(
            f"Temperatura do ar: {_formatar(temperatura_ar, 2)} °C, aplicada a todas as datas."
            if temperatura_ar is not None else
            "Temperatura do ar não informada: onda longa incidente e saldo de radiação pendentes."
        )
    if not arquivo_manifesto.is_file():
        documento.texto(
            "Manifesto da execução não disponível. Parâmetros que não constam do CSV "
            "não foram presumidos para este relatório."
        )
    grades = manifesto.get("grades", []) if pastagens else manifesto.get("cenas", [])
    por_data = {g.get("data"): g for g in grades}
    cenas = []
    for dia in datas:
        registro = next(r for r in registros if r["data"] == dia)
        grade = por_data.get(dia, {})
        transformacao = grade.get("transform", [])
        pixel = (
            f"{math.hypot(transformacao[0], transformacao[3]):g} × "
            f"{math.hypot(transformacao[1], transformacao[4]):g}"
            if len(transformacao) >= 6 else "Não informado"
        )
        cenas.append([_data(dia), str(registro.get("satelite", "Não informado")).replace("_", " "), grade.get("crs", "Não informado"), pixel])
    documento.tabela(["Aquisição", "Satélite", "CRS da grade", "Pixel (unidades do CRS)"], cenas,
                      [documento.largura * p for p in (0.17, 0.23, 0.28, 0.32)])
    solares = []
    for dia in datas:
        solar = por_data.get(dia, {}).get("solar") or {}
        if not solar:
            continue
        solares.append([
            _data(dia), _formatar(solar.get("distancia_ua"), 6),
            _formatar(solar.get("fator_inverso_quadrado"), 6),
            solar.get("fonte", "Não informada"),
        ])
    if solares:
        documento.texto("Distância Terra-Sol e fator orbital por cena", "SubtituloEvapo")
        documento.texto(
            "d é distância em UA; dr = 1/d² é adimensional. O MTL tem prioridade. "
            "A planilha fornecida permite conferência e consulta por dia do ano quando a distância "
            "não consta do MTL. Apesar do nome da aba dr, sua coluna D contém d em UA. "
            "Não se aplica esse fator novamente à reflectância obtida dos coeficientes MTL."
        )
        documento.tabela(
            ["Aquisição", "d (UA)", "dr = 1/d²", "Fonte"], solares,
            [documento.largura * p for p in (0.18, 0.20, 0.20, 0.42)],
        )

    documento.conteudo.append(PageBreak())
    documento.secao("3. Fundamentação teórica dos produtos")
    produtos = sorted({r["produto"] for r in registros})
    for produto in produtos:
        teoria = teorias.get(produto)
        if teoria is None:
            documento.texto(f"{produto}: fundamentação específica não cadastrada.")
            continue
        documento.texto(teoria["titulo"], "SubtituloEvapo")
        documento.texto(f"Unidade: {teoria['unidade']}. Fórmula: {teoria['formula']}")
        documento.texto(teoria["interpretacao"])
        documento.texto(teoria["limites"])
    if metodologia_versao == 2:
        documento.texto(
            "O albedo TOA utiliza B2 a B7: 0,300 B2 + 0,277 B3 + 0,233 B4 + "
            "0,143 B5 + 0,036 B6 + 0,012 B7 [SILVA2016]. Os pesos arredondados somam 1,001 "
            "e são usados sem renormalização. Os arquivos ERDAS originais permanecem como "
            "referência histórica; seus antigos pesos B1 a B7 não definem esta execução."
        )

    documento.secao("4. Resultados comparativos")
    grupos = defaultdict(list)
    for registro in registros:
        grupos[(registro["produto"], registro.get("vigor", ""))].append(registro)
    for (produto, vigor), grupo in sorted(grupos.items()):
        nome = teorias.get(produto, {}).get("titulo", produto)
        documento.texto(f"{nome}{' · vigor ' + vigor if vigor else ''}", "SubtituloEvapo")
        linhas = [
            [_data(r["data"]), _formatar(r["pixels_validos"], 0), _formatar(r.get("cobertura_percentual"), 2),
             _formatar(r.get("media")), _formatar(r.get("mediana")), _formatar(r.get("desvio_padrao")),
             _formatar(r.get("minimo")), _formatar(r.get("maximo"))]
            for r in sorted(grupo, key=lambda r: r["data"])
        ]
        documento.tabela(
            ["Data", "Pixels válidos", "Cobertura %", "Média", "Mediana", "Desvio padrão", "Mínimo", "Máximo"],
            linhas, [documento.largura * p for p in (0.15, 0.12, 0.12, 0.12, 0.12, 0.13, 0.12, 0.12)],
        )
    cobertura_csv = pasta / "cobertura_por_vigor.csv"
    if pastagens and cobertura_csv.is_file():
        documento.texto("Distribuição das áreas de pastagem", "SubtituloEvapo")
        documento.texto(
            "As áreas em hectares são medidas na grade projetada, sem correção da distorção "
            "cartográfica. Os grupos de ROI, pastagem e vigor se sobrepõem e não devem ser somados."
        )
        documento.tabela(
            ["Data", "Grupo", "Pixels", "Área na grade (ha)"],
            [[_data(r["data"]), r["grupo"], _formatar(r["pixels"], 0), _formatar(r["area_ha_grade"], 2)]
             for r in _ler_csv(cobertura_csv)],
            [documento.largura * p for p in (0.18, 0.44, 0.16, 0.22)],
        )

    documento.secao("5. Interpretação por data e produto")
    for registro in sorted(registros, key=lambda r: (r["data"], r.get("vigor", ""), r["produto"])):
        nome = teorias.get(registro["produto"], {}).get("titulo", registro["produto"])
        documento.texto(
            f"{_data(registro['data'])} · {nome}" +
            (f" · vigor {registro['vigor']}" if registro.get("vigor") else ""),
            "SubtituloEvapo",
        )
        for texto in interpretar_registro(registro, metodologia_versao=metodologia_versao):
            documento.texto(texto)

    documento.secao("6. Referências e rastreabilidade")
    for referencia in REFERENCIAS:
        documento.texto(f"[{referencia['id']}] {referencia['titulo']}")
        # O URL é escapado; nenhuma marcação das entradas é executada no PDF.
        if referencia["url"].startswith("https://"):
            url = html.escape(referencia["url"], quote=True)
            documento.conteudo.append(Paragraph(
                f'<link href="{url}" color="#1e5b78">{url}</link>', documento.estilos["TextoEvapo"]
            ))
        else:
            documento.texto(f"Arquivo local do projeto: {referencia['url']}")
    documento.texto(
        "Documentos locais do estudo: Aula3_Modelagem_08_09_26.pdf; "
        "Aula4_15_09_26.pdf; Aula5_22_09_26.pdf; Aula6_29_09_26.pdf; modelo_albedo_toa.gmd; modelo_albedo_superficie_srtm.gmd. "
        "Planilha solar: entrada/Planilha_Distancia_relativa_terra_sol.xlsx. "
        "Os arquivos de entrada, o manifesto e os CSV permitem auditar os parâmetros da execução."
    )
    documento.texto(f"Estatísticas de origem: {arquivo_csv.name}. Manifesto: {arquivo_manifesto.name}.")
    if pastagens:
        documento.texto(
            "As legendas das figuras usam estatisticas_produtos.csv da área completa. "
            "Para análises antigas, também são consultados os CSV e PNG existentes na pasta "
            "irmã da análise geral (ROI ou imagem inteira), sem recalcular os resultados. "
            "Figuras externas exigem ROI, parâmetros e grades equivalentes nos dois manifestos."
        )
    if projeto and projeto.get("estado", {}).get("notas", "").strip():
        documento.texto("Notas do projeto no momento da exportação", "SubtituloEvapo")
        documento.texto(projeto["estado"]["notas"])
        documento.texto(
            "As notas acima refletem o documento enviado à exportação e podem ser posteriores "
            "à execução. Os resultados numéricos do PDF vêm exclusivamente da análise salva."
        )

    documento.conteudo.append(PageBreak())
    documento.secao("Anexo A. Mapas e histogramas da análise salva")
    documento.texto(
        "A escala de cores segue os intervalos dos produtos; cinza representa ausência ou "
        "exclusão de dados. Os histogramas mostram distribuição espacial, sem identificação "
        "da causa dos padrões. As imagens deste anexo não substituem o CSV em resolução nativa."
    )
    if pastagens:
        documento.texto(
            f"Os mapas e histogramas dos produtos abrangem todos os pixels válidos da {area.lower()}. "
            "A máscara de pastagem e as classes de vigor são apresentadas como figuras adicionais. "
            "As tabelas e interpretações por vigor permanecem restritas a cada classe."
        )
    for dia in datas:
        if pastagens:
            documento.figura(
                pasta / dia / "pastagem_mascara.png",
                f"Máscara binária de pastagem — {_data(dia)}",
            )
            caminho = pasta / dia / "vigor_mapa.png"
            legenda = f"Classes de vigor — {_data(dia)}"
        else:
            caminho = pasta / dia / "rgb_mapa.png"
            legenda = f"Composição RGB B4/B3/B2 — {_data(dia)}"
        documento.figura(caminho, legenda)
    if pastagens:
        figuras = _figuras_produtos_pastagens(pasta, registros, imagem_inteira, manifesto)
    else:
        figuras = [
            (r["data"], r["produto"], _pasta_registro(pasta, r)[0], r)
            for r in sorted(registros, key=lambda r: (r["data"], r["produto"]))
        ]
    for dia, produto, pasta_figuras, registro in figuras:
        documento.conteudo.append(PageBreak())
        nome = teorias.get(produto, {}).get("titulo", produto)
        legenda = f"{_data(dia)} · {nome}"
        documento.texto(legenda, "SubtituloEvapo")
        documento.figura(pasta_figuras / f"{produto}_mapa.png", f"Mapa · {legenda}")
        documento.figura(pasta_figuras / f"{produto}_histograma.png", f"Histograma · {legenda}")
        if registro is None:
            documento.texto(
                "Estatísticas da área completa não disponíveis para esta data e produto. "
                "Consulte as tabelas por vigor para os resultados de cada classe."
            )
        else:
            if pastagens:
                documento.texto(f"Estatísticas da área completa: {registro.get('base_area') or area}.")
            documento.texto(
                f"Pixels válidos: {_formatar(registro['pixels_validos'], 0)}; "
                f"cobertura: {_formatar(registro.get('cobertura_percentual'), 2)}%; "
                f"média: {_formatar(registro.get('media'))}; "
                f"mediana: {_formatar(registro.get('mediana'))}."
            )
    return documento.salvar(destino, titulo)
