"""Le MTL JSON/TXT e descobre as cenas ordenadas pela data de aquisicao."""

import json
from pathlib import Path

from evapo.calculos.solar import NOME_PLANILHA_SOLAR, informacoes_solares


def carregar_mtl(pasta):
    pasta = Path(pasta)
    arquivos = sorted(
        p for p in pasta.iterdir() if p.name.upper().endswith("_MTL.JSON")
    )
    if arquivos:
        return json.loads(arquivos[0].read_text(encoding="utf-8"))[
            "LANDSAT_METADATA_FILE"
        ]
    arquivos = sorted(p for p in pasta.iterdir() if p.name.upper().endswith("_MTL.TXT"))
    if not arquivos:
        raise FileNotFoundError(f"MTL JSON ou TXT ausente: {pasta}")
    raiz, pilha = {}, []
    atual = raiz
    for linha in arquivos[0].read_text(encoding="utf-8").splitlines():
        if "=" not in linha:
            continue
        chave, valor = (s.strip() for s in linha.split("=", 1))
        if chave == "GROUP":
            grupo = {}
            atual[valor] = grupo
            pilha.append(atual)
            atual = grupo
        elif chave == "END_GROUP":
            atual = pilha.pop()
        else:
            atual[chave] = valor.strip('"')
    return raiz["LANDSAT_METADATA_FILE"]


def descobrir_cenas(entrada):
    cenas = []
    planilha = Path(entrada) / NOME_PLANILHA_SOLAR
    for p in Path(entrada).rglob("*"):
        if (
            p.is_file()
            and p.suffix.lower() in (".tif", ".img")
            and "bandas_empilhadas" in p.stem.lower()
        ):
            mtl = carregar_mtl(p.parent)
            a = mtl["IMAGE_ATTRIBUTES"]
            mtl["EVAPO_SOLAR"] = informacoes_solares(
                mtl, caminho_planilha=planilha if planilha.is_file() else None,
            )
            cenas.append(
                {
                    "caminho": p,
                    "data": a["DATE_ACQUIRED"],
                    "satelite": a["SPACECRAFT_ID"],
                    "mtl": mtl,
                }
            )
    if not cenas:
        raise FileNotFoundError("Nenhum empilhamento encontrado em entrada.")
    return sorted(cenas, key=lambda c: c["data"])
