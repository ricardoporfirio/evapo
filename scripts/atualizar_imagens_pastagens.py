"""Atualiza figuras e relatórios de análises de pastagem já salvas.

Uso: uv run python scripts/atualizar_imagens_pastagens.py CAMINHO_PASTAGENS [...]
Acrescente --dry-run para validar as fontes sem escrever arquivos. Os índices,
rasters, CSVs originais e manifestos são preservados. A atualização reaproveita
as figuras e estatísticas da análise geral da mesma execução.
"""

import argparse
import csv
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import matplotlib

matplotlib.use("Agg")

import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom

from evapo.analises.pastagens import mostrar_mascara_pastagem
from evapo.calculos.vigor import CLASSES_VIGOR
from evapo.dados.area import usar_imagem_inteira
from evapo.relatorios.pastagens import (
    salvar_relatorio_classe,
    salvar_relatorio_data,
    salvar_relatorio_pastagens,
)
from evapo.relatorios.pdf import gerar_pdf_da_pasta


ESTATISTICAS = {
    "pixels_totais", "pixels_validos", "pixels_ausentes", "cobertura_percentual",
    "media", "mediana", "desvio_padrao", "variancia", "minimo", "maximo",
    "p05", "q1", "q3", "p95", "amplitude", "intervalo_interquartil",
}
INTEIROS = {
    "pixels_totais", "pixels_validos", "pixels_ausentes", "pixels_grade",
    "pixels_fora_roi", "codigo_vigor", "pixels",
}
NUMERICOS = ESTATISTICAS | INTEIROS | {
    "area_classe_ha_grade", "area_valida_ha_grade", "area_ha_grade",
}
PARAMETROS = (
    "L", "L_iaf", "mde", "temperatura_ar_c", "metodologia_versao",
    "modelo_albedo", "pesos_albedo_toa", "modelos_energia", "modelo_solar",
)


@dataclass
class DataPlanejada:
    cena: dict
    resumo: dict
    registros_produtos: list
    registros_classes: list
    pastagem: np.ndarray
    cobertura_conhecida: np.ndarray
    roi: np.ndarray


@dataclass
class Atualizacao:
    pasta: Path
    fonte: Path
    manifesto: dict
    registros: list
    datas: list
    copias: list
    destinos: set


def _componente(nome):
    if not isinstance(nome, str) or nome in ("", ".", "..") or any(
        caractere in nome for caractere in '/\\:'
    ):
        raise ValueError(f"Nome de data, classe ou produto inválido: {nome!r}.")
    return nome


def _arquivo_local(pasta, *componentes):
    caminho = pasta.joinpath(*componentes)
    if not caminho.resolve().is_relative_to(pasta.resolve()):
        raise ValueError(f"O arquivo deve permanecer dentro da análise: {caminho}.")
    return caminho


def _sha256(caminho):
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def _ler_csv(caminho, campos):
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")
        if not campos.issubset(leitor.fieldnames or []):
            raise ValueError(f"CSV sem os campos necessários: {caminho}.")
        registros = list(leitor)
    if not registros:
        raise ValueError(f"CSV sem registros: {caminho}.")
    for registro in registros:
        for campo in ("data", "produto", "vigor"):
            if campo in registro:
                _componente(registro[campo])
        for campo in NUMERICOS & registro.keys():
            valor = float(registro[campo])
            if campo in INTEIROS:
                if not np.isfinite(valor) or not valor.is_integer() or valor < 0:
                    raise ValueError(f"Contagem inválida em {caminho}: {campo}.")
                valor = int(valor)
            registro[campo] = valor
    return registros


def _grades(manifesto, chave):
    resultado = {}
    for grade in manifesto.get(chave, []):
        data = _componente(grade["data"])
        if data in resultado:
            raise ValueError(f"Data repetida no manifesto: {data}.")
        resultado[data] = grade
    return resultado


def _validar_configuracao(manifesto, geral):
    if "roi" not in manifesto or "roi" not in geral:
        raise ValueError("Os dois manifestos precisam declarar a ROI.")
    if manifesto["roi"] != geral["roi"]:
        raise ValueError("As análises de pastagem e geral têm ROIs diferentes.")
    configuracao = manifesto["configuracao"]
    if not {"metodo", "limites_ndvi", "ano_camada"}.issubset(configuracao):
        raise ValueError("O manifesto de pastagens não declara seu método completo.")
    for campo in PARAMETROS:
        anterior = configuracao.get(campo, manifesto.get(campo))
        referencia = geral.get(campo)
        if anterior != referencia:
            raise ValueError(f"Parâmetro incompatível entre as análises: {campo}.")


def _validar_grade(grade, geral, data):
    for campo in ("crs", "transform", "janela"):
        if campo not in grade or campo not in geral or grade[campo] != geral[campo]:
            raise ValueError(f"Grade incompatível em {data}: {campo}.")
    for campo in ("shape", "bounds", "satelite"):
        if grade.get(campo) != geral.get(campo):
            raise ValueError(f"Grade incompatível em {data}: {campo}.")


def _ler_mascara(caminho, grade, roi):
    with rasterio.open(caminho) as arquivo:
        janela = grade["janela"]
        tamanho = (int(janela["height"]), int(janela["width"]))
        if (
            arquivo.count != 1 or arquivo.shape != tamanho
            or arquivo.crs != rasterio.CRS.from_user_input(grade["crs"])
            or arquivo.transform != Affine(*grade["transform"])
        ):
            raise ValueError(f"Máscara em grade diferente do manifesto: {caminho}.")
        dados = arquivo.read(1, masked=True)
        conhecida = ~np.ma.getmaskarray(dados)
        if not np.isin(dados.data[conhecida], [0, 1]).all():
            raise ValueError(f"A máscara deve ser binária (0/1 e NoData): {caminho}.")
        if usar_imagem_inteira(roi):
            mascara_roi = np.ones(tamanho, dtype=bool)
        else:
            geometria = transform_geom("EPSG:4326", arquivo.crs, roi["geometry"])
            mascara_roi = geometry_mask(
                [geometria], out_shape=tamanho, transform=arquivo.transform,
                invert=True, all_touched=False,
            )
    conhecida &= mascara_roi
    pastagem = conhecida & (dados.data == 1)
    return pastagem, conhecida, mascara_roi


def planejar_atualizacao(pasta):
    """Valida todas as fontes e planeja os arquivos antes de qualquer escrita."""
    pasta = Path(pasta).resolve()
    manifesto = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))
    nome_geral = "imagem_completa" if usar_imagem_inteira(manifesto.get("roi")) else "roi"
    fonte = pasta.parent / nome_geral
    if fonte.resolve() == pasta:
        raise ValueError("Informe a pasta de pastagens, não a análise geral.")
    geral = json.loads((fonte / "manifesto_roi.json").read_text(encoding="utf-8"))
    _validar_configuracao(manifesto, geral)
    registros = _ler_csv(
        pasta / "estatisticas_por_vigor.csv", ESTATISTICAS | {"data", "produto", "vigor"}
    )
    coberturas = _ler_csv(
        pasta / "cobertura_por_vigor.csv", {"data", "grupo", "pixels", "area_ha_grade"}
    )
    grades, grades_gerais = _grades(manifesto, "grades"), _grades(geral, "cenas")
    datas, copias, destinos = [], [], set()
    for data in sorted({r["data"] for r in registros}):
        if data not in grades or data not in grades_gerais:
            raise ValueError(f"Data ausente de um dos manifestos: {data}.")
        grade = grades[data]
        _validar_grade(grade, grades_gerais[data], data)
        pasta_data = _arquivo_local(pasta, data)
        origem_data = _arquivo_local(fonte, data)
        registros_data = [r for r in registros if r["data"] == data]
        origem_csv = origem_data / "estatisticas.csv"
        produtos = _ler_csv(origem_csv, ESTATISTICAS | {"data", "produto"})
        esperados = {r["produto"] for r in registros_data}
        if (
            {r["data"] for r in produtos} != {data}
            or {r["produto"] for r in produtos} != esperados
            or len(produtos) != len(esperados)
            or any(r.get("vigor") for r in produtos)
        ):
            raise ValueError(f"CSV geral incompatível com os produtos de {data}.")
        for produto in sorted(esperados):
            for sufixo in ("mapa.png", "histograma.png", "histograma.json"):
                nome = f"{produto}_{sufixo}"
                origem = _arquivo_local(fonte, data, nome)
                if sufixo.endswith("json"):
                    if not origem.is_file():
                        continue
                    json.loads(origem.read_text(encoding="utf-8"))
                else:
                    with Image.open(origem) as imagem:
                        imagem.verify()
                destino = _arquivo_local(pasta, data, nome)
                copias.append((origem, destino))
                destinos.add(destino)
        destino_csv = pasta_data / "estatisticas_produtos.csv"
        copias.append((origem_csv, destino_csv))
        destinos.add(destino_csv)
        pastagem, conhecida, mascara_roi = _ler_mascara(
            pasta_data / "pastagem_mascara.tif", grade, manifesto["roi"]
        )
        resumo = {r["grupo"]: r["pixels"] for r in coberturas if r["data"] == data}
        if not resumo or resumo.get("Pastagem") != int(pastagem.sum()):
            raise ValueError(f"Cobertura de pastagem incompatível com a máscara em {data}.")
        area = manifesto["configuracao"].get("area_analise", "ROI")
        if resumo.get(area) != int(mascara_roi.sum()):
            raise ValueError(f"Área da ROI incompatível com a cobertura salva em {data}.")
        for chave, _, _ in CLASSES_VIGOR.values():
            pasta_classe = _arquivo_local(pasta, data, chave)
            if not pasta_classe.is_dir() or not any(r["vigor"] == chave for r in registros_data):
                raise ValueError(f"Classe de vigor ausente: {pasta_classe}.")
            destinos.add(pasta_classe / "relatorio.html")
        destinos.update((pasta_data / "pastagem_mascara.png", pasta_data / "relatorio.html"))
        datas.append(DataPlanejada(
            {"data": data, "satelite": grade.get("satelite", produtos[0].get("satelite", ""))},
            resumo, produtos, registros_data, pastagem, conhecida, mascara_roi,
        ))
    destinos.update((pasta / "relatorio.html", pasta / "relatorio.pdf"))
    for destino in destinos:
        _arquivo_local(pasta, *destino.relative_to(pasta).parts)
        if destino.exists() and not destino.is_file():
            raise ValueError(f"Destino não é um arquivo: {destino}.")
    return Atualizacao(pasta, fonte, manifesto, registros, datas, copias, destinos)


def executar_atualizacao(plano):
    """Preserva originais em uma pasta irmã e publica somente figuras e relatórios."""
    agora = datetime.now(timezone.utc)
    backup = plano.pasta.parent / (
        f"backup_figuras_{plano.pasta.name}_{agora:%Y%m%dT%H%M%SZ}_{uuid4().hex[:8]}"
    )
    backup.mkdir(exist_ok=False)
    preservar = {p for p in plano.destinos if p.is_file()}
    preservar.update(p for p in plano.pasta.rglob("*") if p.is_file() and p.suffix.lower() in {".html", ".pdf"})
    preservar.add(plano.pasta / "manifesto.json")
    for original in sorted(preservar):
        copia = backup / original.relative_to(plano.pasta)
        copia.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, copia)
    (backup / "atualizacao.json").write_text(json.dumps({
        "analise": str(plano.pasta), "fonte": str(plano.fonte),
        "data_utc": agora.isoformat(),
        "originais_preservados": [str(p.relative_to(plano.pasta)) for p in sorted(preservar)],
        "sha256_originais": {str(p.relative_to(plano.pasta)): _sha256(p) for p in sorted(preservar)},
        "sha256_fontes": {str(p.relative_to(plano.fonte)): _sha256(p) for p, _ in plano.copias},
        "destinos": [str(p.relative_to(plano.pasta)) for p in sorted(plano.destinos)],
        "metodologia_versao_original": plano.manifesto.get(
            "metodologia_versao", plano.manifesto["configuracao"].get("metodologia_versao")
        ),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for origem, destino in plano.copias:
            shutil.copy2(origem, destino)
        configuracao = plano.manifesto["configuracao"]
        for data in plano.datas:
            pasta_data = plano.pasta / data.cena["data"]
            mostrar_mascara_pastagem(
                data.pastagem, data.cobertura_conhecida, data.roi,
                data.cena["data"], pasta_data / "pastagem_mascara.png",
            )
            salvar_relatorio_data(
                data.cena, data.resumo, configuracao, pasta_data, data.registros_produtos,
            )
            for chave, nome, _ in CLASSES_VIGOR.values():
                registros_classe = [r for r in data.registros_classes if r["vigor"] == chave]
                salvar_relatorio_classe(data.cena, nome, registros_classe, pasta_data / chave)
        salvar_relatorio_pastagens(
            [d.cena for d in plano.datas], plano.registros, configuracao, plano.pasta,
        )
        gerar_pdf_da_pasta(plano.pasta, plano.pasta / "relatorio.pdf")
    except Exception as erro:
        raise RuntimeError(f"Atualização interrompida; originais preservados em {backup}.") from erro
    return backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analises", type=Path, nargs="+", help="Pastas pastagens a atualizar, explicitamente.")
    parser.add_argument("--dry-run", action="store_true", help="Valida todas as fontes, sem escrever arquivos.")
    args = parser.parse_args(argv)
    if len({p.resolve() for p in args.analises}) != len(args.analises):
        parser.error("Informe cada análise apenas uma vez.")
    try:
        planos = [planejar_atualizacao(pasta) for pasta in args.analises]
        for plano in planos:
            produtos = sum(len(data.registros_produtos) for data in plano.datas)
            if args.dry_run:
                print(f"Validado: {plano.pasta} | {len(plano.datas)} datas, {produtos} mapas de produtos; nenhuma escrita.")
            else:
                backup = executar_atualizacao(plano)
                print(f"Atualizado: {plano.pasta} | {len(plano.datas)} datas, {produtos} mapas, {produtos} histogramas e {len(plano.datas)} máscaras; HTML/PDF regenerados.")
                print(f"Backup dos originais: {backup}")
    except (OSError, ValueError, KeyError, RuntimeError) as erro:
        parser.exit(1, f"Erro: {erro}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
