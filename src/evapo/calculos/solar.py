"""Distância Terra–Sol d (UA), fator dr=1/d² e consulta à planilha de aula.

A coluna D da aba ``dr`` contém d, apesar do rótulo. Não se aplica dr
novamente às reflectâncias obtidas pelos coeficientes MTL do Landsat 8/9.
"""

from datetime import date
from functools import lru_cache
import math
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

NOME_PLANILHA_SOLAR = "Planilha_Distancia_relativa_terra_sol.xlsx"
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _data_aquisicao(valor):
    try:
        return date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        raise ValueError("Data de aquisição inválida para a distância Terra–Sol.") from None


def _validar_distancia(valor):
    try:
        distancia = float(valor)
    except (TypeError, ValueError):
        raise ValueError("Distância Terra–Sol deve ser um número positivo em UA.") from None
    if not math.isfinite(distancia) or distancia <= 0:
        raise ValueError("Distância Terra–Sol deve ser finita e positiva em UA.")
    return distancia


def distancia_terra_sol_data(data):
    """Aproximação orbital da planilha; DOY respeita o ano da aquisição.

    A fórmula também atende 31/12 de ano bissexto (DOY 366), que não está
    tabelado na planilha fornecida. O cosseno recebe radianos.
    """
    dia_ano = _data_aquisicao(data).timetuple().tm_yday
    return 1 - 0.01674 * math.cos(math.radians(0.9856 * (dia_ano - 4)))


@lru_cache(maxsize=8)
def _ler_planilha(caminho, modificacao_ns):
    """Lê valores numéricos salvos no XLSX; não executa fórmulas ou macros."""
    del modificacao_ns  # Faz parte da chave para invalidar o cache após edição.
    try:
        with ZipFile(caminho) as arquivo:
            relacoes = {
                r.attrib["Id"]: r.attrib["Target"]
                for r in ET.fromstring(arquivo.read("xl/_rels/workbook.xml.rels"))
            }
            folhas = {}
            livro = ET.fromstring(arquivo.read("xl/workbook.xml"))
            for folha in livro.findall("m:sheets/m:sheet", _NS):
                destino = relacoes[folha.attrib[f"{{{_REL}}}id"]]
                membro = destino.lstrip("/") if destino.startswith("/") else str(PurePosixPath("xl") / destino)
                folhas[folha.attrib["name"].casefold()] = membro

            def linhas_numericas(nome):
                raiz = ET.fromstring(arquivo.read(folhas[nome]))
                for linha in raiz.findall("m:sheetData/m:row", _NS):
                    valores = {}
                    for celula in linha.findall("m:c", _NS):
                        if celula.get("t", "n") != "n":
                            continue
                        valor = celula.find("m:v", _NS)
                        if valor is None or valor.text is None:
                            continue
                        coluna = "".join(c for c in celula.attrib["r"] if c.isalpha())
                        valores[coluna] = float(valor.text)
                    yield valores

            distancias = {}
            for linha in linhas_numericas("dr"):
                dia, distancia = linha.get("A"), linha.get("D")
                if dia is not None and dia.is_integer() and 1 <= dia <= 366 and distancia is not None:
                    distancias[int(dia)] = _validar_distancia(distancia)
            if not distancias:
                raise ValueError("A aba dr não contém distâncias numéricas salvas.")
            esun = {}
            if "esun" in folhas:
                for linha in linhas_numericas("esun"):
                    banda, irradiancia = linha.get("B"), linha.get("C")
                    if banda is not None and banda.is_integer() and 1 <= banda <= 7 and irradiancia is not None:
                        esun[int(banda)] = _validar_distancia(irradiancia)
            return distancias, esun
    except (BadZipFile, ET.ParseError, KeyError, ValueError) as erro:
        raise ValueError(f"Planilha solar inválida ({caminho}): {erro}") from erro


def informacoes_solares(mtl, caminho_planilha=None, data=None):
    """Prioriza MTL, consulta d da planilha e registra a fonte e a comparação."""
    atributos = mtl["IMAGE_ATTRIBUTES"]
    valor_data = atributos.get("DATE_ACQUIRED", data)
    dia_ano = _data_aquisicao(valor_data).timetuple().tm_yday if valor_data is not None else None
    distancia_planilha = None
    esun = {}
    caminho = Path(caminho_planilha) if caminho_planilha is not None else None
    if caminho is not None:
        distancias, esun = _ler_planilha(str(caminho.resolve()), caminho.stat().st_mtime_ns)
        distancia_planilha = distancias.get(dia_ano)

    if "EARTH_SUN_DISTANCE" in atributos:
        distancia = _validar_distancia(atributos["EARTH_SUN_DISTANCE"])
        fonte = "MTL: EARTH_SUN_DISTANCE (UA)"
    elif distancia_planilha is not None:
        distancia = distancia_planilha
        fonte = "Planilha: aba dr, coluna D (d em UA)"
    elif valor_data is not None:
        distancia = distancia_terra_sol_data(valor_data)
        fonte = "Aproximação orbital diária: d = 1 - 0,01674*cos(0,9856*(DOY-4))"
    else:
        raise ValueError("Distância Terra–Sol ausente: informe EARTH_SUN_DISTANCE ou DATE_ACQUIRED.")

    resultado = {
        "distancia_ua": distancia,
        "fator_inverso_quadrado": 1 / distancia**2,
        "fonte": fonte,
        "dia_ano": dia_ano,
    }
    if caminho is not None:
        resultado.update(
            planilha=str(caminho.resolve()),
            distancia_planilha_ua=distancia_planilha,
            diferenca_planilha_ua=distancia - distancia_planilha if distancia_planilha is not None else None,
        )
        if all(b in esun for b in range(2, 8)):
            total = sum(esun[b] for b in range(2, 8))
            resultado["pesos_esun_conferencia_b2_b7"] = {str(b): esun[b] / total for b in range(2, 8)}
    return resultado


def fator_distancia_terra_sol(mtl):
    """Fator de irradiância dr=1/d²; nunca confundir d com dr."""
    if "EARTH_SUN_DISTANCE" in mtl["IMAGE_ATTRIBUTES"]:
        distancia = _validar_distancia(mtl["IMAGE_ATTRIBUTES"]["EARTH_SUN_DISTANCE"])
    elif mtl.get("EVAPO_SOLAR"):
        distancia = _validar_distancia(mtl["EVAPO_SOLAR"]["distancia_ua"])
    else:
        distancia = informacoes_solares(mtl)["distancia_ua"]
    return 1 / distancia**2
