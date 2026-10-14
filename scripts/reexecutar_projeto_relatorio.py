"""Reexecuta um projeto salvo em pasta nova e registra a execução no projeto.

Uso: python scripts/reexecutar_projeto_relatorio.py --projeto ARQUIVO --destino PASTA
Use --verificar para conferir as entradas sem gravar arquivos nem processar.
"""

import argparse
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import traceback
from uuid import uuid4


class SaidaDupla:
    def __init__(self, terminal, arquivo):
        self.terminal = terminal
        self.arquivo = arquivo

    def write(self, texto):
        self.terminal.write(texto)
        self.arquivo.write(texto)
        self.flush()
        return len(texto)

    def flush(self):
        self.terminal.flush()
        self.arquivo.flush()


def conferir(projeto, destino):
    import rasterio
    from rasterio.features import is_valid_geom
    from evapo.calculos.energia import validar_temperatura_ar
    from evapo.dados.area import usar_imagem_inteira
    from evapo.dados.geometria import validar_poligono
    from evapo.dados.metadados import descobrir_cenas
    from evapo.dados.selecao import filtrar_cenas_selecionadas, identificar_cena

    estado = projeto.estado
    entrada = Path(estado["entrada"])
    if not entrada.is_dir():
        raise ValueError(f"Pasta de entrada ausente: {entrada}")
    if destino.exists() and not destino.is_dir():
        raise ValueError(f"O destino não é uma pasta: {destino}")
    L = float(str(estado.get("L", "0.5")).replace(",", "."))
    if not math.isfinite(L) or not 0 <= L <= 1:
        raise ValueError("O L do SAVI deve ser finito e estar entre 0 e 1.")
    temperatura = validar_temperatura_ar(estado.get("temperatura_ar"))
    selecao = deepcopy(estado.get("roi"))
    if usar_imagem_inteira(selecao):
        selecao = {"type": "Feature", "geometry": None,
                   "properties": {"imagem_inteira": True}}
    else:
        geometria = selecao.get("geometry")
        if not is_valid_geom(geometria) or geometria["type"] != "Polygon":
            raise ValueError("O projeto deve conter uma ROI poligonal GeoJSON em WGS84.")
        validar_poligono(geometria["coordinates"][0])
    imagens = estado.get("imagens")
    if imagens is not None:
        if not isinstance(imagens, list) or not imagens or len(set(imagens)) != len(imagens):
            raise ValueError("A seleção de imagens deve ser uma lista não vazia sem duplicatas.")
        selecao.setdefault("properties", {})["imagens_selecionadas"] = list(imagens)
    cenas = filtrar_cenas_selecionadas(descobrir_cenas(entrada), selecao)
    datas = [cena["data"] for cena in cenas]
    if len(set(datas)) != len(datas):
        raise ValueError("Há cenas selecionadas com a mesma data; as saídas colidiriam.")
    for cena in cenas:
        with rasterio.open(cena["caminho"]) as raster:
            if raster.crs is None or raster.count < 1:
                raise ValueError(f"Empilhamento sem CRS ou bandas: {cena['caminho']}")
    mde = Path(estado["mde"]) if estado.get("mde") else None
    if mde is not None:
        with rasterio.open(mde) as raster:
            if raster.count != 1 or raster.crs is None:
                raise ValueError("O MDE deve ter uma banda e CRS definido.")
    ano = int(estado["ano"]) if estado.get("pastagens") else None
    if ano is not None and not 2000 <= ano <= 2025:
        raise ValueError("O ano de pastagens não é aceito pela CLI atual.")
    resumo = {
        "entrada": str(entrada.resolve()), "destino_base": str(destino),
        "datas": datas, "imagens": [identificar_cena(cena) for cena in cenas],
        "L": L, "temperatura_ar_c": temperatura, "mde": str(mde) if mde else None,
        "ano_pastagens": ano, "imagem_inteira": usar_imagem_inteira(selecao),
    }
    if ano is not None and not usar_imagem_inteira(selecao):
        geometria = json.dumps(selecao["geometry"], sort_keys=True).encode()
        chave = hashlib.sha256(geometria).hexdigest()[:12]
        cache = entrada / "mapbiomas" / f"colecao11_{ano}_{chave}"
        resumo["cache_mapbiomas"] = str(cache)
        resumo["cache_completo"] = all((cache / nome).is_file() for nome in ("cobertura.tif", "vigor.tif"))
    return selecao, resumo


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projeto", required=True, type=Path)
    parser.add_argument("--destino", type=Path, help="Base para execucoes; padrão: saída salva.")
    parser.add_argument("--verificar", action="store_true")
    parser.add_argument("--sem-timelapse", action="store_true")
    parser.add_argument("--dispositivo", choices=("auto", "cpu"), default="auto")
    args = parser.parse_args(argv)
    from evapo.dados.projetos import Projeto, gravar_documento

    arquivo = args.projeto.resolve()
    projeto = Projeto.abrir(arquivo)
    original = arquivo.read_bytes()
    destino = (args.destino or Path(projeto.estado["saida"])).resolve()
    selecao, resumo = conferir(projeto, destino)
    print(json.dumps(resumo, ensure_ascii=False, indent=2), flush=True)
    if args.verificar:
        return 0

    # Só o destino muda; editar preserva o estado anterior no histórico.
    estado = deepcopy(projeto.estado)
    estado["saida"] = str(destino)
    projeto.editar(estado)
    backup = arquivo.with_name(f"{arquivo.stem}.backup-{uuid4().hex[:12]}.json")
    with backup.open("xb") as copia:
        copia.write(original)
    print(f"Backup do projeto: {backup}", flush=True)
    execucao = projeto.iniciar_execucao(destino)
    pasta = Path(execucao["pasta"])
    print(f"Nova execução: {pasta}", flush=True)
    codigo = 1
    status = "falhou"
    with (pasta / "processamento.log").open("w", encoding="utf-8") as log:
        with redirect_stdout(SaidaDupla(sys.stdout, log)), redirect_stderr(SaidaDupla(sys.stderr, log)):
            try:
                import matplotlib
                matplotlib.use("Agg")
                from evapo.cli import main as executar_cli
                from evapo.mapa.roi import gravar_selecao

                gravar_selecao(selecao, pasta / "roi.geojson")
                gravar_documento(pasta / "preflight.json", resumo)
                comando = ["--entrada", resumo["entrada"], "--saida", str(pasta),
                           "--roi", str(pasta / "roi.geojson"), "--sem-interface",
                           "--L", str(resumo["L"]), "--dispositivo", args.dispositivo]
                if resumo["mde"] is not None:
                    comando += ["--mde", resumo["mde"]]
                if resumo["temperatura_ar_c"] is not None:
                    comando += ["--temperatura-ar", str(resumo["temperatura_ar_c"])]
                if resumo["ano_pastagens"] is not None:
                    comando += ["--baixar-mapbiomas", str(resumo["ano_pastagens"])]
                if args.sem_timelapse:
                    comando.append("--sem-timelapse")
                print("Argumentos CLI: " + json.dumps(comando, ensure_ascii=False), flush=True)
                codigo = executar_cli(comando)
                status = "concluido" if codigo == 0 else "falhou"
            except KeyboardInterrupt:
                codigo, status = 130, "interrompido"
                print("Processamento interrompido.", flush=True)
            except Exception:
                traceback.print_exc()
            finally:
                execucao["status"] = status
                (pasta / "notas.txt").write_text(execucao["estado"].get("notas", ""), encoding="utf-8")
                try:
                    # Reabre mudanças feitas em paralelo e acrescenta apenas esta execução.
                    if arquivo.read_bytes() != original:
                        atual = Projeto.abrir(arquivo)
                        if atual.identificador != projeto.identificador:
                            raise ValueError("O projeto foi substituído durante o processamento.")
                        atual.execucoes = [e for e in atual.execucoes if e["nome"] != execucao["nome"]]
                        atual.execucoes.append(deepcopy(execucao))
                        projeto = atual
                        print("Edições paralelas preservadas no projeto.", flush=True)
                    gravar_documento(pasta / "configuracao.evapo.json", projeto.documento())
                    projeto.salvar(arquivo)
                except Exception:
                    # Mantém o registro completo na pasta mesmo se o projeto não puder ser salvo.
                    gravar_documento(pasta / "configuracao.evapo.json", projeto.documento())
                    traceback.print_exc()
                    codigo = 1
                print(f"Status da execução: {status}; código: {codigo}", flush=True)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
