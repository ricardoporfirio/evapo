"""Lê exclusivamente produtos já gravados pela execução indicada."""

import csv
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import rasterio


RUN = Path(r"C:\Users\Ricardo\Desktop\RES\execucoes\2026-10-13_09-37-39_dac3ee")
DESTINO = Path(__file__).with_name("evidencias_reexecucao.json")


def converter(valor):
    if valor is None or valor == "":
        return None
    if re.fullmatch(r"[+-]?\d+", valor):
        return int(valor)
    try:
        numero = float(valor)
        return numero if math.isfinite(numero) else None
    except ValueError:
        return valor


def ler_csv(caminho):
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        return [
            {chave: converter(valor) for chave, valor in linha.items()}
            for linha in csv.DictReader(arquivo, delimiter=";")
        ]


def estatisticas_raster(caminho, mascara):
    with rasterio.open(caminho) as arquivo:
        valores = arquivo.read(1, masked=True).filled(np.nan)
        validos = mascara & np.isfinite(valores)
        v = valores[validos].astype("float64")
    n = int(v.size)
    total = int(mascara.sum())
    q = np.percentile(v, [5, 25, 50, 75, 95]) if n else [None] * 5
    return {
        "pixels_totais": total,
        "pixels_validos": n,
        "pixels_ausentes": total - n,
        "cobertura_percentual": 100 * n / total,
        "area_total_ha_grade": total * 0.09,
        "area_valida_ha_grade": n * 0.09,
        "media": float(v.mean()) if n else None,
        "variancia": float(v.var()) if n else None,
        "desvio_padrao": float(v.std()) if n else None,
        "minimo": float(v.min()) if n else None,
        "maximo": float(v.max()) if n else None,
        **(dict(zip(["p05", "q1", "mediana", "q3", "p95"], map(float, q)))
           if n else {}),
    }


def main():
    principais = {
        "roi_nativa": "roi/estatisticas_todas_cenas_roi.csv",
        "pastagens_por_vigor": "pastagens/estatisticas_por_vigor.csv",
        "cobertura_por_vigor": "pastagens/cobertura_por_vigor.csv",
        "roi_grade_visualizacao": "roi/estatisticas_temporais_grade_reduzida.csv",
    }
    obrigatorios = [RUN / caminho for caminho in principais.values()]
    obrigatorios += [RUN / "roi/manifesto_roi.json", RUN / "pastagens/manifesto.json"]
    faltando = [str(p) for p in obrigatorios if not p.exists()]
    if faltando:
        raise SystemExit("Execução ainda incompleta: " + ", ".join(faltando))
    csvs = {
        str(p.relative_to(RUN)).replace("\\", "/"): ler_csv(p)
        for p in sorted(RUN.rglob("*.csv"))
    }
    metadados = {}
    for nome in [
        "configuracao.evapo.json", "preflight.json", "pastagens/manifesto.json",
        "roi/manifesto_roi.json", "roi/timelapse/manifesto.json",
    ]:
        p = RUN / nome
        if p.exists():
            metadados[nome] = json.loads(p.read_text(encoding="utf-8"))
    roi = csvs[principais["roi_nativa"]]
    vigores = csvs[principais["pastagens_por_vigor"]]
    cobertura = csvs[principais["cobertura_por_vigor"]]
    datas = sorted({r["data"] for r in roi})
    produtos = sorted({r["produto"] for r in roi})
    if len(datas) != 5 or len(produtos) != 17 or len(roi) != 85 or len(vigores) != 255:
        raise SystemExit("Quantidade de datas, produtos ou linhas inesperada.")
    ponderados, diretos = [], []
    verificacoes = []
    for data in datas:
        pasta = RUN / "pastagens" / data
        with rasterio.open(pasta / "pastagem_mascara.tif") as arquivo:
            pastagem = arquivo.read(1) == 1
        for produto in produtos:
            rows = [r for r in vigores if r["data"] == data and r["produto"] == produto]
            n = sum(r["pixels_validos"] for r in rows)
            total = sum(r["pixels_totais"] for r in rows)
            media = sum(r["pixels_validos"] * r["media"] for r in rows) / n
            variancia = sum(
                r["pixels_validos"] * (r["variancia"] + (r["media"] - media) ** 2)
                for r in rows
            ) / n
            ponderados.append({
                "data": data, "produto": produto, "unidade": rows[0]["unidade"],
                "base": "ROI e pastagens com vigor baixo, moderado ou alto; exclui 2 pixels sem vigor",
                "pixels_totais": total, "pixels_validos": n,
                "cobertura_percentual": 100 * n / total, "media": media,
                "variancia": variancia, "desvio_padrao": math.sqrt(variancia),
            })
            raster = pasta / "rasters" / f"{produto}.tif"
            estatisticas = estatisticas_raster(raster, pastagem)
            diretos.append({
                "data": data, "produto": produto, "unidade": rows[0]["unidade"],
                "base": "ROI e todas as pastagens, incluindo os 2 pixels sem vigor",
                "fonte_raster": str(raster), **estatisticas,
            })
        original = csvs[f"pastagens/{data}/estatisticas_produtos.csv"]
        roi_data = [r for r in roi if r["data"] == data]
        verificacoes.append({
            "data": data,
            "estatisticas_produtos_pastagens_iguais_roi": original == roi_data,
            "pixels_pastagem_mascara": int(pastagem.sum()),
        })
    fontes = []
    for p in sorted(RUN.rglob("*.csv")):
        fontes.append({
            "caminho": str(p), "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        })
    resultado = {
        "status": "extração da nova execução; nenhum dado da execução anterior utilizado",
        "diretorio_execucao": str(RUN), "datas": datas, "produtos": produtos,
        "numero_produtos": len(produtos), "numero_csvs": len(csvs),
        "arquivos_principais": principais, "fontes_csv": fontes,
        "csvs_inteiros": csvs, "metadados_originais": metadados,
        "cobertura_classes": cobertura,
        "pastagens_tres_vigores_agregado_ponderado": ponderados,
        "pastagens_todas_agregado_direto_raster": diretos,
        "verificacoes": verificacoes,
        "metodo_agregacao": {
            "media": "Soma de n_i vezes media_i dividida pela soma de n_i, por data e produto.",
            "variancia_populacional": "Soma de n_i vezes (variancia_i + (media_i - media_agregada)^2), dividida pela soma de n_i.",
            "percentis": "Percentis conjuntos calculados diretamente nos rasters com a máscara de todas as pastagens. Percentis das classes não foram promediados.",
        },
    }
    DESTINO.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"arquivo": str(DESTINO), "csvs": len(csvs), "datas": datas, "produtos": len(produtos), "verificacoes": verificacoes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
