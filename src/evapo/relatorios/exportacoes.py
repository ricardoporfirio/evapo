"""Exporta figuras e relatórios completos sem alterar os arquivos da análise."""

import json
import shutil
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile


def _mapa_de_classe_substituido(arquivo):
    """Mapas completos substituem as antigas figuras recortadas por vigor."""
    return (
        arquivo.parent.name in ("baixo", "moderado", "alto")
        and arquivo.name.endswith("_mapa.png")
        and (arquivo.parent.parent / arquivo.name).is_file()
    )


def exportar_relatorio(pasta, destino, projeto=None):
    """O ZIP mantém PDF, imagens, CSV e links relativos dos relatórios HTML."""
    pasta, destino = Path(pasta).resolve(), Path(destino).resolve()
    if not (pasta / "relatorio.html").is_file():
        raise ValueError("Processe as imagens e selecione uma análise com relatório.")
    arquivos = [
        p
        for p in pasta.rglob("*")
        if p.is_file()
        and p.suffix.lower() in (".pdf", ".html", ".csv", ".png", ".gif", ".json", ".geojson")
        and not _mapa_de_classe_substituido(p)
    ]
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        with ZipFile(temporario, "w", compression=ZIP_DEFLATED) as pacote:
            for arquivo in arquivos:
                if arquivo not in (destino, temporario):
                    pacote.write(arquivo, arquivo.relative_to(pasta))
            if projeto:
                pacote.writestr(
                    "projeto.evapo.json",
                    json.dumps(projeto, ensure_ascii=False, indent=2),
                )
                pacote.writestr("notas.txt", projeto["estado"].get("notas", ""))
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)


def exportar_imagens(pasta, destino):
    """Cria uma subpasta nova para não substituir uma exportação anterior."""
    pasta, destino = Path(pasta).resolve(), Path(destino).resolve()
    arquivos = [
        p for p in pasta.rglob("*.png") if not _mapa_de_classe_substituido(p)
    ]
    if not arquivos:
        raise ValueError(
            "Esta análise não possui imagens PNG. Processe as imagens primeiro."
        )
    exportacao = destino / f"imagens_{pasta.name}_{uuid4().hex[:8]}"
    exportacao.mkdir(parents=True, exist_ok=False)
    for arquivo in arquivos:
        copia = exportacao / arquivo.relative_to(pasta)
        copia.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(arquivo, copia)
    return exportacao, len(arquivos)
