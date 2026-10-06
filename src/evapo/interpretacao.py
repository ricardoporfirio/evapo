"""Interpretação descritiva dos produtos Landsat, sem inferência causal.

Os textos usam as estatísticas já calculadas pelo projeto. Não consultam rede,
não classificam a vegetação por limiares universais e não estimam ET.
"""

from collections import defaultdict
from datetime import date
import math


REFERENCIAS = (
    {
        "id": "USGS-NDVI",
        "titulo": "USGS. Landsat Normalized Difference Vegetation Index.",
        "url": "https://www.usgs.gov/landsat-missions/landsat-normalized-difference-vegetation-index",
    },
    {
        "id": "HUETE1988",
        "titulo": "Huete, A. R. (1988). A soil-adjusted vegetation index (SAVI). Remote Sensing of Environment, 25(3), 295-309.",
        "url": "https://doi.org/10.1016/0034-4257(88)90106-X",
    },
    {
        "id": "SEBAL2002",
        "titulo": "Waters, R.; Allen, R.; Bastiaanssen, W.; Tasumi, M.; Trezza, R. (2002). SEBAL: Surface Energy Balance Algorithms for Land. Advanced Training and Users Manual, versão 1.0, p. 9-11, 16-20.",
        "url": "https://posmet.ufv.br/wp-content/uploads/2017/04/MET-479-Waters-et-al-SEBAL.pdf",
    },
    {
        "id": "KE2016",
        "titulo": "Ke, Y.; Im, J.; Park, S.; Gong, H. (2016). Downscaling of MODIS One Kilometer Evapotranspiration Using Landsat-8 Data and Machine Learning Approaches. Remote Sensing, 8(3), 215, tabela 4.",
        "url": "https://doi.org/10.3390/rs8030215",
    },
    {
        "id": "MAPBIOMAS-VIGOR",
        "titulo": "MapBiomas Brasil. Condição de vigor da pastagem: legenda e método da Coleção 11.",
        "url": "https://brasil.mapbiomas.org/iniciativas-e-produtos/cobertura-e-uso-da-terra/pastagem/condicao-de-vigor/",
    },
    {
        "id": "AULA3",
        "titulo": "Andrade, R. G. (2026). Aula 3: Modelagem. UFJF, Programa de Pós-Graduação em Engenharia Civil, p. 10-21. Material fornecido com o projeto.",
        "url": "modelos/Aula3_Modelagem_08_09_26.pdf",
    },
    {
        "id": "AULA4",
        "titulo": "Andrade, R. G. (2026). Aula 4: Modelagem. UFJF, Programa de Pós-Graduação em Engenharia Civil, p. 2-9. Material fornecido com o projeto.",
        "url": "modelos/Aula4_15_09_26.pdf",
    },
    {
        "id": "GMD-TOA",
        "titulo": "Modelo ERDAS de albedo TOA fornecido com o projeto: pesos B1-B7 e limites de 0 a 1.",
        "url": "modelos/modelo_albedo_toa.gmd",
    },
    {
        "id": "GMD-SUPERFICIE",
        "titulo": "Modelo ERDAS de albedo da superfície com MDE/SRTM fornecido com o projeto: correção e limites numéricos.",
        "url": "modelos/modelo_albedo_superficie_srtm.gmd",
    },
)


TEORIA_PRODUTOS = {
    "ndvi": {
        "titulo": "NDVI — Índice de Vegetação da Diferença Normalizada",
        "unidade": "adimensional",
        "formula": "NDVI = (rho_B5 - rho_B4) / (rho_B5 + rho_B4).",
        "interpretacao": "O contraste entre infravermelho próximo (B5) e vermelho (B4) descreve o sinal espectral da vegetação verde. Valores maiores são compatíveis com maior presença de vegetação verde, dependendo do solo, da estrutura do dossel e das condições de aquisição [USGS-NDVI].",
        "limites": "Neste projeto, o NDVI usa reflectância TOA calibrada pelos metadados e pela elevação solar [AULA3]. Isso difere dos índices oficiais USGS derivados de reflectância de superfície Level-2. O intervalo de -1 a 1 não define classes universais de vigor; o índice não mede diretamente biomassa, água ou produtividade.",
    },
    "savi": {
        "titulo": "SAVI — Índice de Vegetação Ajustado ao Solo",
        "unidade": "adimensional",
        "formula": "SAVI = (1 + L) * (rho_B5 - rho_B4) / (rho_B5 + rho_B4 + L).",
        "interpretacao": "O termo L reduz a influência do brilho do solo no contraste espectral, sobretudo quando o solo participa do sinal do pixel [HUETE1988]. A interpretação depende do L efetivamente usado, que deve acompanhar a comparação.",
        "limites": "O padrão do projeto é L=0,5, conforme o material local [AULA3; AULA4]. São usadas reflectâncias TOA; o ajuste de solo não é uma correção atmosférica. NDVI e SAVI têm escalas diferentes e sua diferença, isoladamente, não quantifica solo exposto.",
    },
    "iaf": {
        "titulo": "IAF — Índice de Área Foliar estimado",
        "unidade": "m² de folhas / m² de terreno",
        "formula": "IAF = -ln((0,69 - SAVI) / 0,59) / 0,91; 0 se SAVI <= 0,1; 6 se SAVI >= 0,687; limitado a [0; 6].",
        "interpretacao": "IAF representa a área de folhas por área de terreno. Aqui ele é estimado por uma relação empírica com SAVI, apresentada para o sul de Idaho com L=0,1 [SEBAL2002].",
        "limites": "O projeto aplica a relação ao SAVI configurado, cujo padrão L=0,5 acompanha as aulas [AULA3; AULA4]. Sua transferência exige validação local. Zero e seis podem decorrer dos limites do cálculo. Água e neve marcadas em QA são excluídas; IAF não é uma medição independente de SAVI.",
    },
    "albedo_toa": {
        "titulo": "Albedo TOA — estimativa no topo da atmosfera",
        "unidade": "adimensional",
        "formula": "Albedo TOA = 0,130*rho_B1 + 0,115*rho_B2 + 0,143*rho_B3 + 0,180*rho_B4 + 0,281*rho_B5 + 0,108*rho_B6 + 0,042*rho_B7.",
        "interpretacao": "A estimativa combina as sete reflectâncias TOA conforme as aulas e o modelo ERDAS local [AULA3; GMD-TOA]. Ela reúne a resposta da superfície e da atmosfera; não representa diretamente a fração refletida apenas pela superfície.",
        "limites": "O resultado é limitado a [0; 1]. Os pesos coincidem com a tabela 4 de Ke et al., aplicada naquele estudo a reflectâncias de superfície [KE2016]; aqui a entrada é TOA. Variações atmosféricas e de aquisição dificultam atribuir mudanças à cobertura do terreno.",
    },
    "albedo_superficie": {
        "titulo": "Albedo da superfície — estimativa corrigida",
        "unidade": "adimensional",
        "formula": "Albedo da superfície = (albedo_TOA - 0,03) / tau²; tau = 0,75 + 0,00002*z, com z em metros.",
        "interpretacao": "Albedo é a fração da radiação solar incidente refletida pela superfície. Mantida a mesma radiação incidente, albedo maior corresponde a uma fração menor de onda curta absorvida. A correção usa transmissividade estimada pela altitude e contribuição atmosférica fixa [SEBAL2002; AULA3; AULA4].",
        "limites": "Requer MDE válido. A aproximação não representa toda a variabilidade atmosférica. O modelo local substitui resultados <=0 por 0,00001 e >=1 por 1 [GMD-SUPERFICIE]. Albedo sozinho não determina saldo de radiação, temperatura ou evapotranspiração.",
    },
}


def teorias_produtos():
    """Retorna os textos de teoria sem expor os dicionários internos à edição."""
    return {produto: dict(textos) for produto, textos in TEORIA_PRODUTOS.items()}


def _numero(valor):
    """Lê CSV ou número finito; ausência, NaN e infinito continuam ausentes."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, str):
        valor = valor.strip().replace(",", ".")
        if not valor:
            return None
    try:
        numero = float(valor)
    except (TypeError, ValueError, OverflowError):
        return None
    return numero if math.isfinite(numero) else None


def _formatar(valor, casas=4, sinal=False):
    return format(valor, f"{'+' if sinal else ''}.{casas}f").replace(".", ",")


def _cobertura(registro):
    total = _numero(registro.get("pixels_totais"))
    validos = _numero(registro.get("pixels_validos"))
    if total == 0:
        return None
    cobertura = _numero(registro.get("cobertura_percentual"))
    if cobertura is None and total is not None and total > 0 and validos is not None:
        cobertura = 100 * validos / total
    return cobertura if cobertura is not None and 0 <= cobertura <= 100 else None


def _data(valor):
    try:
        return date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return None


def _rotulo_produto(produto):
    nomes = {"ndvi": "NDVI", "savi": "SAVI", "iaf": "IAF", "albedo_toa": "Albedo TOA", "albedo_superficie": "Albedo da superfície"}
    return nomes.get(produto, str(produto or "Produto não informado").replace("_", " "))


def _tem_media(registro):
    return (
        _numero(registro.get("media")) is not None
        and _numero(registro.get("pixels_validos")) != 0
        and _numero(registro.get("pixels_totais")) != 0
    )


def interpretar_registro(registro):
    """Descreve uma data/produto/classe a partir de estatísticas já calculadas."""
    produto = registro.get("produto", "")
    nome = _rotulo_produto(produto)
    validos = _numero(registro.get("pixels_validos"))
    total = _numero(registro.get("pixels_totais"))
    cobertura = _cobertura(registro)
    if total == 0:
        return [f"{nome}: a área ou classe está vazia nesta grade. Não há estatísticas representativas; a ausência não corresponde a valor zero do produto."]
    if validos == 0:
        return [f"{nome}: nenhum pixel válido nesta data após os filtros da área e do produto. Não é possível interpretar a condição da superfície; dados ausentes não representam valor zero nem baixo vigor."]
    textos = []
    if cobertura is None:
        textos.append(f"{nome}: cobertura válida não informada; a representatividade espacial não pode ser avaliada pela tabela disponível.")
    else:
        quantidade = f"{int(validos):,}".replace(",", ".") if validos is not None else "quantidade não informada de"
        textos.append(f"{nome}: {quantidade} pixels válidos, cobrindo {_formatar(cobertura, 2)}% da área ou classe analisada.")
        if cobertura < 100:
            textos.append("As estatísticas descrevem somente a parcela observada. Nuvens, sombras, saturação, ausência de cobertura da cena e filtros específicos podem excluir pixels; o percentual ausente não mede isoladamente a nebulosidade.")
    media = _numero(registro.get("media"))
    if media is None:
        textos.append("Média ausente: não há base numérica para interpretar o nível médio do produto.")
        return textos
    textos.append(f"Média de {_formatar(media)}" + (" m²/m²." if produto == "iaf" else "."))
    mediana = _numero(registro.get("mediana"))
    q1, q3 = _numero(registro.get("q1")), _numero(registro.get("q3"))
    if mediana is not None and q1 is not None and q3 is not None and q1 <= q3:
        textos.append(f"A mediana foi {_formatar(mediana)}; os 50% centrais dos valores ficaram entre {_formatar(q1)} e {_formatar(q3)}. Essa distribuição descreve diferenças entre pixels, sem identificar sua causa.")
    if produto in ("ndvi", "savi"):
        if media > 0:
            textos.append("O sinal médio positivo é compatível com contraste infravermelho próximo-vermelho associado à vegetação verde. Ele não define, por si só, uma classe de vigor ou a proporção de vegetação na área.")
        elif media < 0:
            textos.append("O sinal médio negativo indica contraste espectral inverso nos valores médios do índice. Água, sombras e outros materiais podem contribuir; o índice sozinho não identifica o uso do solo.")
        else:
            textos.append("A média do índice é zero. Isso expressa o balanço dos índices dos pixels observados e não comprova ausência de vegetação.")
        if produto == "savi":
            textos.append("A leitura do SAVI considera o ajuste de brilho do solo e o L configurado [HUETE1988]. A diferença para NDVI não deve ser convertida diretamente em porcentagem de solo exposto.")
    elif produto == "iaf":
        textos.append("Esse valor é uma estimativa empírica de área foliar derivada de SAVI [SEBAL2002]. A transformação é não linear: o IAF médio não equivale ao IAF calculado a partir do SAVI médio.")
        maximo = _numero(registro.get("maximo"))
        minimo = _numero(registro.get("minimo"))
        if maximo is not None and maximo >= 6:
            textos.append("O máximo alcançou o teto de 6 m²/m² do modelo. Esse limite reduz a capacidade de distinguir dosséis mais densos; a tabela não informa quantos pixels foram limitados.")
        if minimo is not None and minimo == 0:
            textos.append("Há valores no piso zero do modelo, aplicado a SAVI <=0,1. Esse piso é uma regra empírica de cálculo e não comprova ausência física de folhas.")
    elif produto == "albedo_toa":
        textos.append("O valor reúne reflectâncias no topo da atmosfera, segundo os pesos do modelo local [GMD-TOA]. Sua interpretação inclui a atmosfera e não permite atribuir a fração refletida apenas à superfície.")
    elif produto == "albedo_superficie":
        textos.append(f"A fração média refletida estimada é {_formatar(100 * media, 2)}% da radiação de onda curta incidente. A relação com energia absorvida pressupõe radiação incidente comparável; o resultado depende do MDE e da correção atmosférica simplificada [SEBAL2002].")
        minimo, maximo = _numero(registro.get("minimo")), _numero(registro.get("maximo"))
        if (minimo is not None and minimo <= 0.00001) or (maximo is not None and maximo >= 1):
            textos.append("A distribuição alcança os limites numéricos do modelo ERDAS. Esses extremos podem decorrer da limitação aplicada ao resultado da correção [GMD-SUPERFICIE].")
    return textos


def _efeito_temporal(produto, diferenca):
    if abs(diferenca) < 0.00005:
        return "As médias coincidem na precisão de quatro casas apresentada; isso não comprova igualdade pixel a pixel."
    maior = diferenca > 0
    if produto in ("ndvi", "savi"):
        return f"A mudança é compatível com {'maior' if maior else 'menor'} sinal espectral médio de vegetação verde nos pixels observados, sob as condições de aquisição e do índice."
    if produto == "iaf":
        return f"A estimativa empírica média de área foliar foi {'maior' if maior else 'menor'}; o resultado acompanha a transformação do SAVI e seus limites."
    if produto == "albedo_superficie":
        return f"A fração refletida estimada foi {'maior' if maior else 'menor'}. Para a mesma radiação incidente, isso corresponderia a {'menor' if maior else 'maior'} absorção de onda curta."
    if produto == "albedo_toa":
        return "A diferença representa o conjunto superfície-atmosfera e não identifica isoladamente uma mudança no albedo da superfície."
    return "A diferença descreve as médias observadas, sem identificar uma causa física."


def interpretar_temporal(registros, imagem_inteira=False):
    """Compara as datas com dados, separando produto e classe de vigor.

    São diferenças descritivas entre a primeira e a última observação válida,
    nunca uma regressão temporal nem uma comparação pareada de pixels.
    """
    registros = list(registros)
    if not registros:
        return ["Não há registros disponíveis para comparação temporal."]
    textos = [
        "As comparações descrevem a primeira e a última data com média válida de cada produto e classe. Não estabelecem tendência contínua, significância estatística ou causa; os intervalos entre aquisições podem ser diferentes.",
        "Cada imagem inteira usa sua própria grade nativa e pode abranger superfícies diferentes. A comparação das médias integrais não garante a mesma extensão geográfica."
        if imagem_inteira
        else "A ROI mantém a delimitação geográfica da análise, mas os pixels válidos podem mudar entre datas. Mesmo coberturas percentuais iguais não garantem comparação dos mesmos pixels.",
        "NDVI e SAVI são derivados de reflectância TOA neste projeto. Sazonalidade, manejo, fundo de solo, atmosfera e geometria de aquisição podem contribuir para diferenças; são hipóteses a verificar com dados complementares.",
        "Os produtos apresentados não fornecem evapotranspiração. O SEBAL completo requer o balanço de energia e outros dados; índices de vegetação e albedo, isoladamente, não estimam consumo de água [SEBAL2002].",
    ]
    grupos = defaultdict(list)
    for registro in registros:
        grupos[(registro.get("produto", ""), registro.get("vigor", ""))].append(registro)
    for (produto, vigor), grupo in sorted(grupos.items()):
        nome = _rotulo_produto(produto) + (f" — vigor {vigor}" if vigor else "")
        validos = sorted(
            (r for r in grupo if _tem_media(r) and _data(r.get("data")) is not None),
            key=lambda r: _data(r["data"]),
        )
        datas = [r["data"] for r in validos]
        if len(set(datas)) != len(datas):
            textos.append(f"{nome}: há mais de um registro na mesma data; a diferença temporal não foi calculada para evitar misturar conjuntos distintos.")
            continue
        if len(validos) < 2:
            textos.append(f"{nome}: {'uma única data com média válida' if validos else 'nenhuma data com média válida e data identificável'}; não há base para calcular mudança temporal.")
            continue
        primeiro, ultimo = validos[0], validos[-1]
        media_inicial = _numero(primeiro["media"])
        media_final = _numero(ultimo["media"])
        diferenca = media_final - media_inicial
        data_inicial = _data(primeiro["data"]).strftime("%d/%m/%Y")
        data_final = _data(ultimo["data"]).strftime("%d/%m/%Y")
        texto = f"{nome}: média {_formatar(media_inicial)} em {data_inicial} e {_formatar(media_final)} em {data_final}; diferença final - inicial = {_formatar(diferenca, sinal=True)}"
        texto += " m²/m². " if produto == "iaf" else ". "
        texto += _efeito_temporal(produto, diferenca)
        cobertura_inicial, cobertura_final = _cobertura(primeiro), _cobertura(ultimo)
        if cobertura_inicial is not None and cobertura_final is not None:
            texto += f" Cobertura válida: {_formatar(cobertura_inicial, 2)}% e {_formatar(cobertura_final, 2)}%, respectivamente."
        else:
            texto += " A cobertura válida de pelo menos uma das datas não foi informada."
        omitidos = len(grupo) - len(validos)
        if omitidos:
            texto += f" {omitidos} registro(s) sem média válida ou data identificável ficaram fora desta diferença; não foram substituídos por zero."
        textos.append(texto)
        mediana_inicial = _numero(primeiro.get("mediana"))
        mediana_final = _numero(ultimo.get("mediana"))
        if mediana_inicial is not None and mediana_final is not None:
            mudanca_mediana = mediana_final - mediana_inicial
            if diferenca * mudanca_mediana < 0:
                textos.append(f"{nome}: média e mediana mudaram em sentidos opostos. Isso indica alteração da distribuição dos valores observados e impede tratar a diferença média como mudança uniforme da área.")
    if any(r.get("vigor") for r in registros):
        textos.append("Cada classe de vigor tem seu próprio conjunto espacial e denominador de cobertura. Diferenças entre classes descrevem estratos; não comprovam efeito causal do vigor sobre outro produto. Se as classes vierem do NDVI da própria data, diferenças de NDVI entre elas são consequência da regra de classificação.")
    return textos


def interpretar_pastagens(configuracao):
    """Explica a referência espacial, o método de vigor e seus limites."""
    configuracao = configuracao or {}
    limites = configuracao.get("limites_ndvi")
    metodo = str(configuracao.get("metodo", ""))
    fontes = configuracao.get("fontes_raster") or {}
    fonte_vigor = fontes.get("vigor") or {}
    ano = configuracao.get("ano_camada") or fonte_vigor.get("ano")
    textos = ["As estatísticas das classes usam a interseção da área analisada, da pastagem, da classe de vigor e dos pixels válidos de cada produto. Cada classe tem seu próprio denominador; a cobertura não representa toda a ROI."]
    if limites is not None or "ndvi" in metodo.lower():
        textos.append("O vigor é classificado pelo NDVI de cada aquisição, com limites definidos para este estudo. As classes não equivalem ao produto anual de vigor do MapBiomas e não representam limiares universais.")
        if isinstance(limites, (list, tuple)) and len(limites) == 2:
            baixo, alto = (_numero(v) for v in limites)
            if baixo is not None and alto is not None and -1 < baixo < alto < 1:
                textos.append(f"Regras usadas: baixo se NDVI < {_formatar(baixo)}; moderado se {_formatar(baixo)} <= NDVI < {_formatar(alto)}; alto se NDVI >= {_formatar(alto)}.")
        textos.append("Comparar NDVI entre classes criadas com o próprio NDVI descreve a regra usada, sem validar de forma independente o vigor. A área de cada classe pode mudar entre datas, inclusive por mudanças na disponibilidade do NDVI.")
    else:
        origem = str(fonte_vigor.get("fonte", "")) + " " + str(fonte_vigor.get("url_origem", "")) + " " + str(configuracao.get("vigor", ""))
        if "mapbiomas" in origem.lower():
            textos.append("O vigor anual do MapBiomas estratifica a pastagem em baixo (1), médio/moderado (2) e alto (3), usando séries mensais MODIS e mediana de EVI [MAPBIOMAS-VIGOR]. Essas classes anuais são uma referência espacial; os produtos Landsat descrevem cada aquisição separadamente.")
        else:
            textos.append("As classes anuais fornecidas são usadas como estratos espaciais de referência, com códigos 1=baixo, 2=moderado e 3=alto. A origem e o método da camada devem ser conferidos nos metadados; não se presume que toda camada local seja MapBiomas.")
        textos.append(f"Ano da camada de referência: {ano}. Aplicá-la a cenas de outro ano não confirma permanência da pastagem nem do vigor naquele ano." if ano is not None else "O ano da camada de referência não foi informado; a compatibilidade temporal com as aquisições Landsat precisa ser verificada.")
    textos.extend([
        "Pastagem sem vigor classificado permanece como ausência de classe; ela não é atribuída a baixo vigor. Classes vazias mantêm médias ausentes e não devem ser comparadas como valores zero.",
        "Os estratos permitem descrever diferenças de sinal espectral e albedo, mas não diagnosticar degradação, fertilidade, estresse hídrico, taxa de lotação ou produtividade sem validação adicional.",
        "As áreas em hectares são estimadas pela grade projetada em metros, sem correção de distorção cartográfica. ROI, pastagem e classes são conjuntos sobrepostos e suas linhas não devem ser somadas.",
    ])
    return textos
