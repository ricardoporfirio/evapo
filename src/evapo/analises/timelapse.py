"""Alinha as datas na mesma ROI e gera frames PNG, GIFs e um HTML interativo."""

import base64
import io
import html
import json
from contextlib import ExitStack
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.features import bounds as geometry_bounds
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom

from evapo.calculos.albedo import calcular_albedo_toa, calcular_transmissividade, corrigir_albedo_superficie
from evapo.calculos.energia import calcular_radiacoes, produtos_termicos_cena, ler_raster_alinhado, validar_temperatura_ar
from evapo.calculos.produtos import PRODUTOS, unidade_produto
from evapo.calculos.estatisticas import estatisticas_descritivas
from evapo.calculos.indices import calcular_iaf, calcular_ndvi, calcular_savi
from evapo.calculos.reflectancia import calcular_reflectancias


def preparar_frames(cenas, roi, tamanho=900, L=0.5, caminho_mde=None, temperatura_ar=None):
    """Amostra todas as cenas na mesma grade geográfica dentro da ROI."""
    temperatura_ar = validar_temperatura_ar(temperatura_ar)
    with ExitStack() as ctx:
        fontes = [ctx.enter_context(rasterio.open(c["caminho"])) for c in cenas]
        if any(s.crs != fontes[0].crs or s.crs is None or s.count != 7 for s in fontes):
            raise ValueError("As cenas devem ter sete bandas e o mesmo CRS definido.")
        # Sem ROI, abrange toda a extensão de todas as cenas; não corta à interseção.
        left = min(s.bounds.left for s in fontes)
        right = max(s.bounds.right for s in fontes)
        bottom = min(s.bounds.bottom for s in fontes)
        top = max(s.bounds.top for s in fontes)
        geometria = None
        if roi is not None:
            geometria = transform_geom("EPSG:4326", fontes[0].crs, roi["geometry"])
            left, bottom, right, top = geometry_bounds(geometria)
        if tamanho < 1:
            raise ValueError("O tamanho da visualização deve ser positivo.")
        resolucao_nativa = min(
            max(abs(s.transform.a), abs(s.transform.e)) for s in fontes
        )
        pixel = max(max(right - left, top - bottom) / tamanho, resolucao_nativa)
        width, height = (
            int(np.ceil((right - left) / pixel)),
            int(np.ceil((top - bottom) / pixel)),
        )
        transform = from_bounds(left, bottom, right, top, width, height)
        mask_roi = (
            None
            if geometria is None
            else geometry_mask([geometria], (height, width), transform, invert=True)
        )
        frames = []
        resumo = []
        for cena, src in zip(cenas, fontes):
            print(f"Preparando {cena['data']} — {cena['satelite']}", flush=True)
            pasta = cena["caminho"].parent
            qa_src = ctx.enter_context(
                rasterio.open(next(pasta.glob("*_QA_PIXEL.TIF")))
            )
            sat_src = ctx.enter_context(
                rasterio.open(next(pasta.glob("*_QA_RADSAT.TIF")))
            )
            for aux in (qa_src, sat_src):
                if (
                    aux.shape != src.shape
                    or aux.transform != src.transform
                    or aux.crs != src.crs
                ):
                    raise ValueError(f"QA não alinhada em {pasta}")
            opts = {
                "crs": src.crs,
                "transform": transform,
                "width": width,
                "height": height,
                "resampling": Resampling.nearest,
            }
            # Preserva os valores de preenchimento originais: DN=0 e bit 0 da QA.
            # DN=0 mantém pixels sem cobertura ausentes mesmo na borda da ROI.
            with (
                WarpedVRT(src, **opts) as vrt,
                WarpedVRT(qa_src, **opts) as qv,
                WarpedVRT(sat_src, **opts) as sv,
            ):
                dn = vrt.read(masked=True)
                qa, sat = qv.read(1), sv.read(1)
            rho = calcular_reflectancias(dn, qa, sat, cena["mtl"], mascara_roi=mask_roi)
            ndvi = calcular_ndvi(rho[4], rho[5])
            savi = calcular_savi(rho[4], rho[5], L=L)
            iaf = calcular_iaf(savi)
            iaf[(qa & ((1 << 7) | (1 << 5))) != 0] = np.nan
            rgb = np.stack([rho[b] for b in (4, 3, 2)], axis=-1)
            rgb = np.clip(rgb / 0.3, 0, 1) ** 0.8
            rgb[~np.isfinite(rgb).all(axis=-1)] = [0.90, 0.91, 0.92]
            produtos = {
                "rgb": rgb,
                "albedo_toa": calcular_albedo_toa(rho),
                "ndvi": ndvi,
                "savi": savi,
                "iaf": iaf,
            }
            produtos.update(produtos_termicos_cena(cena, ndvi, qa, sat, src.crs, transform, mask_roi))
            if caminho_mde is not None:
                altitude = ler_raster_alinhado(caminho_mde, src.crs, transform, (height, width))
                tau = calcular_transmissividade(altitude)
                valido = ((qa & 31) == 0) & ((sat & (1 << 11)) == 0)
                valido &= (~np.ma.getmaskarray(dn) & (dn.data != 0)).any(axis=0)
                if mask_roi is not None:
                    valido &= mask_roi
                tau[~valido] = np.nan
                produtos["transmissividade"] = tau
                produtos["albedo_superficie"] = corrigir_albedo_superficie(produtos["albedo_toa"], tau)
                produtos.update(calcular_radiacoes(
                    tau, cena["mtl"], temperatura_ar, produtos["emissividade"],
                    produtos.get("temperatura_superficie"), produtos["albedo_superficie"],
                ))
            frames.append(produtos)
            for nome in produtos:
                if nome == "rgb":
                    continue
                resumo.append(
                    dict(
                        data=cena["data"],
                        satelite=cena["satelite"],
                        produto=nome,
                        unidade=unidade_produto(nome),
                        base="grade comum de visualizacao; nao representa estatistica integral",
                        **estatisticas_descritivas(
                            produtos[nome],
                            PRODUTOS[nome][1],
                            mascara_roi=mask_roi
                            if mask_roi is not None
                            else np.ones(produtos[nome].shape, dtype=bool),
                        ),
                    )
                )
        return (
            frames,
            resumo,
            {
                "crs": str(fontes[0].crs),
                "bounds": [left, bottom, right, top],
                "width": width,
                "height": height,
                "roi": roi,
                "temperatura_ar_c": temperatura_ar,
                "mde": str(caminho_mde) if caminho_mde else None,
            },
        )


def montar_timelapse(cenas, frames, destino, grade, segundos=1.5):
    """GIFs por produto e HTML local com seleção de produto, datas e playback."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    specs = {"rgb": ("Composição RGB — B4/B3/B2", None, None)}
    specs.update({nome: (rotulo, cores, limites) for nome, (rotulo, limites, cores, _) in PRODUTOS.items()
                  if any(nome in frame for frame in frames)})
    imagens_html = {}
    for produto, (titulo, cmap, limites) in specs.items():
        imagens, urls = [], []
        for cena, frame in zip(cenas, frames):
            fig, ax = plt.subplots(figsize=(7, 7), dpi=100, layout="constrained")
            kwargs = {
                "interpolation": "nearest",
                "extent": grade["bounds"][::2] + grade["bounds"][1::2],
            }
            # extent = esquerda, direita, inferior, superior.
            if cmap:
                cores = plt.get_cmap(cmap).copy()
                cores.set_bad("#e5e7eb")
                im = ax.imshow(
                    frame.get(produto, np.full(frame["ndvi"].shape, np.nan)),
                    cmap=cores,
                    vmin=limites[0],
                    vmax=limites[1],
                    **kwargs,
                )
                fig.colorbar(
                    im,
                    ax=ax,
                    shrink=0.8,
                    label=unidade_produto(produto),
                )
            else:
                ax.imshow(frame[produto], **kwargs)
            data = date.fromisoformat(cena["data"]).strftime("%d/%m/%Y")
            sufixo = " — ROI" if grade.get("roi") else ""
            ax.set_title(
                f"{titulo}{sufixo}\n{data} | {cena['satelite'].replace('_', ' ')}"
            )
            ax.set_axis_off()
            fig.text(
                0.5,
                0.015,
                "ROI comum • QA aplicada • intervalos irregulares"
                if grade.get("roi")
                else "Grade comum • QA aplicada • datas com intervalos irregulares",
                ha="center",
                fontsize=8,
            )
            buf = io.BytesIO()
            fig.savefig(buf, format="png")
            plt.close(fig)
            png = buf.getvalue()
            (destino / f"{produto}_{cena['data']}.png").write_bytes(png)
            urls.append("data:image/png;base64," + base64.b64encode(png).decode())
            imagens.append(Image.open(io.BytesIO(png)).convert("RGB"))
        imagens[0].save(
            destino / f"timelapse_{produto}.gif",
            save_all=True,
            append_images=imagens[1:],
            duration=int(segundos * 1000),
            loop=0,
            disposal=2,
        )
        imagens_html[produto] = urls
    payload = json.dumps(
        {"imagens": imagens_html, "datas": [c["data"] for c in cenas]},
        ensure_ascii=False,
    )
    pagina = """<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sequência temporal Landsat</title>
<style>body{font:16px system-ui;background:#f4f6f8;color:#183041;max-width:960px;margin:30px auto;padding:0 20px}main{background:white;border-radius:14px;padding:24px}img{display:block;max-width:100%;margin:auto}nav{display:flex;gap:12px;align-items:center;flex-wrap:wrap}button,select{padding:10px;font:inherit}input{flex:1;min-width:170px}p{line-height:1.5}</style>
<main><h1>Sequência temporal Landsat</h1><p>Cenas na mesma grade espacial, com máscaras QA e escalas de cores fixas. Cada cena permanece o mesmo tempo na tela; os intervalos reais entre aquisições são diferentes. Cinza indica pixels excluídos. RGB usa reflectância 0–0,30 e gamma 0,8 fixos.</p>
<nav><select id="produto"><option value="rgb">Imagem RGB</option><option value="albedo_toa">Albedo TOA</option><option value="ndvi">NDVI</option><option value="savi">SAVI</option><option value="iaf">IAF</option></select><button id="play">Reproduzir</button><input id="quadro" type="range" min="0" value="0" aria-label="Data"><output id="data"></output></nav><img id="imagem" alt="Cena Landsat na data selecionada">
<p>Visualização em grade reduzida por vizinho mais próximo. Mudanças de cobertura de nuvens, estação e condições atmosféricas também afetam a comparação. O albedo da superfície depende do MDE e não está incluído.</p></main><script>const dados=__DADOS__;const produto=document.getElementById('produto'),quadro=document.getElementById('quadro'),imagem=document.getElementById('imagem'),data=document.getElementById('data'),play=document.getElementById('play');let timer=null;quadro.max=dados.datas.length-1;function render(){let i=Number(quadro.value);imagem.src=dados.imagens[produto.value][i];data.textContent=dados.datas[i].split('-').reverse().join('/')}function parar(){clearInterval(timer);timer=null;play.textContent='Reproduzir'}quadro.oninput=()=>{parar();render()};produto.onchange=render;play.onclick=()=>{if(timer){parar();return}play.textContent='Pausar';timer=setInterval(()=>{quadro.value=(Number(quadro.value)+1)%dados.datas.length;render()},1500)};render();</script></html>"""
    opcoes = "".join(f'<option value="{nome}">{html.escape(spec[0])}</option>' for nome, spec in specs.items())
    inicio = pagina.index('<select id="produto">') + len('<select id="produto">')
    fim = pagina.index('</select>', inicio)
    pagina = pagina[:inicio] + opcoes + pagina[fim:]
    pagina = pagina.replace(
        "O albedo da superfície depende do MDE e não está incluído.",
        "Os produtos disponíveis dependem de B10, MDE e temperatura do ar informados."
    )
    arquivo = destino / "timelapse_interativo.html"
    arquivo.write_text(pagina.replace("__DADOS__", payload), encoding="utf-8")
    (destino / "manifesto.json").write_text(
        json.dumps(
            {
                "grade": grade,
                "cenas": [
                    {
                        "data": c["data"],
                        "satelite": c["satelite"],
                        "caminho": str(c["caminho"]),
                    }
                    for c in cenas
                ],
                "rgb": {"reflectancia_maxima": 0.3, "gamma": 0.8},
                "metodo": "vizinho mais proximo; ROI comum; QA por cena"
                if grade.get("roi")
                else "vizinho mais proximo; extensao total das cenas; QA por cena",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return arquivo
