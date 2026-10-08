"""Desenho interativo de ROI em janela independente e GeoJSON WGS84."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from rasterio.features import is_valid_geom
from rasterio.warp import transform_geom

from evapo.dados.geometria import validar_poligono
from evapo.mapa.navegacao import NavegacaoMapa
from evapo.mapa.previas import PreviasCenas
from evapo.dados.selecao import identificar_cena


def salvar_roi(
    vertices, crs, destino, forma="poligono", origem=None, imagens_selecionadas=None
):
    anel = validar_poligono(vertices)
    geometria = transform_geom(
        crs, "EPSG:4326", {"type": "Polygon", "coordinates": [anel]}
    )
    geometria["coordinates"] = [
        [list(ponto) for ponto in contorno] for contorno in geometria["coordinates"]
    ]
    feature = {
        "type": "Feature",
        "properties": {
            "forma": forma,
            "imagem_referencia": str(origem or ""),
            "crs_desenho": str(crs),
        },
        "geometry": geometria,
    }
    if imagens_selecionadas is not None:
        if not imagens_selecionadas:
            raise ValueError("Selecione pelo menos uma imagem para a análise.")
        feature["properties"]["imagens_selecionadas"] = imagens_selecionadas
    if destino is not None:
        gravar_selecao(feature, destino)
    return feature


def salvar_imagem_inteira(destino, origem=None, imagens_selecionadas=None):
    if imagens_selecionadas is not None and not imagens_selecionadas:
        raise ValueError("Marque pelo menos uma imagem para a análise.")
    propriedades = {"imagem_inteira": True, "imagem_referencia": str(origem or "")}
    if imagens_selecionadas is not None:
        propriedades["imagens_selecionadas"] = imagens_selecionadas
    feature = {"type": "Feature", "properties": propriedades, "geometry": None}
    gravar_selecao(feature, destino)
    return feature


def gravar_selecao(feature, destino):
    documento = {"type": "FeatureCollection", "features": [feature]}
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    # Troca atômica evita ler uma geometria parcialmente escrita.
    temporario = destino.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(documento, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporario.replace(destino)


def carregar_roi(caminho):
    doc = json.loads(Path(caminho).read_text(encoding="utf-8"))
    if doc.get("type") == "FeatureCollection":
        if len(doc["features"]) != 1:
            raise ValueError("Use um GeoJSON com uma única ROI.")
        doc = doc["features"][0]
    if (
        doc.get("type") == "Feature"
        and doc.get("geometry") is None
        and doc.get("properties", {}).get("imagem_inteira") is True
    ):
        return doc
    if (
        doc.get("type") != "Feature"
        or not is_valid_geom(doc.get("geometry"))
        or doc["geometry"]["type"] != "Polygon"
    ):
        raise ValueError("A ROI deve ser um polígono GeoJSON em WGS84 (EPSG:4326).")
    validar_poligono(doc["geometry"]["coordinates"][0])
    return doc


def selecionar_roi(caminho_img, destino="saida/roi.geojson", editar=False, cenas=None):
    """Abre o seletor Tk em processo separado e reutiliza a ROI quando ela existe."""
    destino = Path(destino).resolve()
    if destino.exists() and not editar:
        return carregar_roi(destino)
    comando = [
        sys.executable,
        "-m",
        "evapo.mapa.roi",
        "--imagem",
        str(Path(caminho_img).resolve()),
        "--saida",
        str(destino),
    ]
    if cenas is not None:
        for cena in cenas:
            comando.extend(["--cena", str(cena["caminho"].resolve())])
    resultado = subprocess.run(
        comando,
        capture_output=True,
        text=True,
        check=False,
    )
    if resultado.returncode == 2:
        raise RuntimeError(
            "Seleção da ROI cancelada. Nenhum processamento foi iniciado."
        )
    if resultado.returncode:
        raise RuntimeError(
            "Não foi possível abrir o seletor de ROI: " + resultado.stderr[-2500:]
        )
    return carregar_roi(destino)


def janela_roi(caminho_img, destino, caminhos_cenas=None):
    import matplotlib

    matplotlib.use("TkAgg", force=True)
    # Os botões de navegação abaixo substituem a barra técnica do Matplotlib.
    matplotlib.rcParams["toolbar"] = "None"
    from tkinter import messagebox

    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    from matplotlib.widgets import (
        Button,
        CheckButtons,
        EllipseSelector,
        PolygonSelector,
        RadioButtons,
        RectangleSelector,
        Slider,
    )

    caminho_img = Path(caminho_img)
    previas = PreviasCenas(caminhos_cenas or [caminho_img], caminho_img)
    indice_atual = previas.indice_inicial
    previa_inicial = previas.carregar(indice_atual)
    crs = previas.crs
    figura = plt.figure(figsize=(12, 9))
    figura.canvas.manager.set_window_title("Selecionar ROI — Trabalho Evapo")
    eixo_mapa = figura.add_axes([0.06, 0.23, 0.73, 0.68])
    camada_imagem = eixo_mapa.imshow(previa_inicial["rgb"], extent=previas.limites)
    eixo_mapa.set_aspect("equal")
    eixo_mapa.set_title("Desenhe uma ROI ou continue para usar a imagem inteira")
    eixo_mapa.set_xlabel("Easting (m)")
    eixo_mapa.set_ylabel("Northing (m)")
    eixo_mapa.ticklabel_format(style="plain", useOffset=False)
    seletor_formas = RadioButtons(
        figura.add_axes([0.81, 0.76, 0.18, 0.15]), ["Retângulo", "Círculo", "Polígono"]
    )
    botao_desenhar = Button(figura.add_axes([0.81, 0.69, 0.085, 0.05]), "Desenhar")
    botao_mover = Button(figura.add_axes([0.905, 0.69, 0.085, 0.05]), "Mover")
    botao_zoom_mais = Button(figura.add_axes([0.81, 0.63, 0.085, 0.05]), "Zoom +")
    botao_zoom_menos = Button(figura.add_axes([0.905, 0.63, 0.085, 0.05]), "Zoom −")
    botao_ver_tudo = Button(figura.add_axes([0.81, 0.57, 0.18, 0.04]), "Ver tudo")
    botao_salvar = Button(figura.add_axes([0.81, 0.23, 0.18, 0.055]), "Continuar")
    botao_limpar = Button(figura.add_axes([0.81, 0.155, 0.18, 0.045]), "Limpar desenho")
    botao_cancelar = Button(figura.add_axes([0.81, 0.09, 0.18, 0.045]), "Cancelar")
    status = figura.text(
        0.06,
        0.055,
        "Roda do mouse: zoom. Mover: arraste o mapa. Desenhar: marque a ROI.",
        fontsize=10,
    )
    estado = {"forma": "Retângulo", "vertices": None, "contorno": None, "salvou": False}
    estado["indice_cena"] = indice_atual
    roi_anterior = carregar_roi(destino) if Path(destino).is_file() else None
    escolhidas_antes = None
    if roi_anterior is not None:
        escolhidas_antes = roi_anterior.get("properties", {}).get(
            "imagens_selecionadas"
        )
    marcacoes = []
    rotulos_datas = []
    for cena in previas.cenas:
        marcacoes.append(
            escolhidas_antes is None or identificar_cena(cena) in escolhidas_antes
        )
        data = "/".join(reversed(cena["data"].split("-")))
        satelite_curto = cena["satelite"].replace("LANDSAT_", "L")
        rotulos_datas.append(f"{data} — {satelite_curto}")
    caixas_imagens = CheckButtons(
        figura.add_axes([0.81, 0.31, 0.18, 0.23]), rotulos_datas, marcacoes
    )
    for rotulo in caixas_imagens.labels:
        rotulo.set_fontsize(9)
    texto_selecao = figura.text(0.81, 0.545, "Usar na análise", fontsize=10)
    texto_data = figura.text(0.06, 0.155, "", fontsize=10)
    figura.text(
        0.06,
        0.09,
        "Sem desenho: imagem inteira. Marque à direita as datas que serão analisadas.",
        fontsize=9,
    )

    botao_anterior = Button(figura.add_axes([0.06, 0.113, 0.12, 0.033]), "Anterior")
    botao_proxima = Button(figura.add_axes([0.66, 0.113, 0.12, 0.033]), "Próxima")
    slider_datas = None

    def mostrar_data(indice):
        indice = int(indice)
        previa = previas.carregar(indice)
        cena = previas.cenas[indice]
        # Só substitui o fundo: limites de zoom e vértices permanecem em metros.
        camada_imagem.set_data(previa["rgb"])
        estado["indice_cena"] = indice
        data = "/".join(reversed(cena["data"].split("-")))
        texto_data.set_text(
            f"{indice + 1}/{len(previas.cenas)} — {data} — {cena['satelite'].replace('_', ' ')}"
            f" | Área válida na prévia inteira: {previa['percentual_visivel']:.1f}%"
            + (" | Usar" if caixas_imagens.get_status()[indice] else " | Excluída")
        )
        botao_anterior.set_active(indice > 0)
        botao_proxima.set_active(indice < len(previas.cenas) - 1)
        figura.canvas.draw_idle()

    mostrar_data(indice_atual)
    if len(previas.cenas) > 1:
        slider_datas = Slider(
            figura.add_axes([0.26, 0.115, 0.36, 0.025]),
            "Data",
            valmin=0,
            valmax=len(previas.cenas) - 1,
            valinit=indice_atual,
            valstep=1,
        )
        slider_datas.valtext.set_visible(False)
        slider_datas.on_changed(mostrar_data)

    def mudar_data(passo):
        novo_indice = estado["indice_cena"] + passo
        if 0 <= novo_indice < len(previas.cenas) and slider_datas is not None:
            slider_datas.set_val(novo_indice)

    def atualizar_selecao(rotulo=None):
        quantidade = sum(caixas_imagens.get_status())
        texto_selecao.set_text(f"Usar na análise: {quantidade}/{len(previas.cenas)}")
        mostrar_data(estado["indice_cena"])

    botao_anterior.on_clicked(lambda evento: mudar_data(-1))
    botao_proxima.on_clicked(lambda evento: mudar_data(1))
    caixas_imagens.on_clicked(atualizar_selecao)
    atualizar_selecao()

    def desenhar(vertices):
        estado["vertices"] = vertices
        if estado["contorno"] is not None:
            estado["contorno"].remove()
        estado["contorno"] = Polygon(
            vertices, closed=True, fill=False, edgecolor="#e11d48", linewidth=2.5
        )
        eixo_mapa.add_patch(estado["contorno"])
        status.set_text(
            "ROI desenhada. Confira o contorno vermelho e clique em Continuar."
        )
        figura.canvas.draw_idle()

    def caixa(evento_inicial, evento_final):
        if None in (
            evento_inicial.xdata,
            evento_inicial.ydata,
            evento_final.xdata,
            evento_final.ydata,
        ):
            return
        esquerda, direita = sorted((evento_inicial.xdata, evento_final.xdata))
        inferior, superior = sorted((evento_inicial.ydata, evento_final.ydata))
        desenhar(
            [
                (esquerda, inferior),
                (direita, inferior),
                (direita, superior),
                (esquerda, superior),
            ]
        )

    def circulo(evento_inicial, evento_final):
        if None in (
            evento_inicial.xdata,
            evento_inicial.ydata,
            evento_final.xdata,
            evento_final.ydata,
        ):
            return
        centro_x, centro_y = (
            (evento_inicial.xdata + evento_final.xdata) / 2,
            (evento_inicial.ydata + evento_final.ydata) / 2,
        )
        raio = (
            min(
                abs(evento_inicial.xdata - evento_final.xdata),
                abs(evento_inicial.ydata - evento_final.ydata),
            )
            / 2
        )
        angulos = np.linspace(0, 2 * np.pi, 128, endpoint=False)
        desenhar(
            np.column_stack(
                [centro_x + raio * np.cos(angulos), centro_y + raio * np.sin(angulos)]
            ).tolist()
        )

    seletores = {
        "Retângulo": RectangleSelector(
            eixo_mapa, caixa, useblit=False, button=[1], interactive=True
        ),
        "Círculo": EllipseSelector(
            eixo_mapa, circulo, useblit=False, button=[1], interactive=True
        ),
        "Polígono": PolygonSelector(eixo_mapa, desenhar, useblit=False),
    }
    instrucoes = {
        "Retângulo": "Arraste para desenhar. Shift: quadrado. Contorno vermelho = ROI salva.",
        "Círculo": "Arraste uma caixa. O contorno vermelho é um círculo inscrito, em metros.",
        "Polígono": "Clique nos vértices; clique no primeiro para fechar. Arraste vértices para ajustar.",
    }

    def atualizar_modo_navegacao(modo):
        pode_desenhar = modo == "desenhar"
        for nome, seletor in seletores.items():
            seletor.set_active(pode_desenhar and nome == estado["forma"])
        botao_desenhar.color = "#dbeafe" if pode_desenhar else "#eeeeee"
        botao_mover.color = "#eeeeee" if pode_desenhar else "#dbeafe"
        botao_desenhar.ax.set_facecolor(botao_desenhar.color)
        botao_mover.ax.set_facecolor(botao_mover.color)
        if pode_desenhar:
            status.set_text(
                instrucoes[estado["forma"]] + "\nRoda: zoom. Botão do meio: mover."
            )
        else:
            status.set_text(
                "Arraste o mapa com o botão esquerdo. Roda: zoom.\nClique em Desenhar para voltar a marcar a ROI."
            )
        figura.canvas.draw_idle()

    # Registra a navegação antes dos seletores: o botão do meio suspende o desenho.
    # Os seletores já criados são desconectados e reconectados depois dela.
    for seletor in seletores.values():
        seletor.disconnect_events()
    navegacao = NavegacaoMapa(eixo_mapa, atualizar_modo_navegacao)
    for seletor in seletores.values():
        seletor.connect_default_events()
    botao_desenhar.on_clicked(lambda evento: navegacao.escolher_modo("desenhar"))
    botao_mover.on_clicked(lambda evento: navegacao.escolher_modo("mover"))
    botao_zoom_mais.on_clicked(lambda evento: navegacao.aplicar_zoom(aproximar=True))
    botao_zoom_menos.on_clicked(lambda evento: navegacao.aplicar_zoom(aproximar=False))
    botao_ver_tudo.on_clicked(lambda evento: navegacao.ver_tudo())

    def mudar(nome):
        estado["forma"] = nome
        estado["vertices"] = None
        if estado["contorno"] is not None:
            estado["contorno"].remove()
            estado["contorno"] = None
        for chave, seletor in seletores.items():
            seletor.clear()
            seletor.set_active(chave == nome)
            seletor.set_visible(chave == nome)
        status.set_text(instrucoes[nome])
        navegacao.escolher_modo("desenhar")
        status.set_text(
            "Sem desenho: Continuar usa a imagem inteira.\n" + instrucoes[nome]
        )
        figura.canvas.draw_idle()

    seletor_formas.on_clicked(mudar)
    mudar("Retângulo")
    if roi_anterior is not None and roi_anterior["geometry"] is not None:
        forma_anterior = roi_anterior.get("properties", {}).get("forma", "Retângulo")
        if forma_anterior in seletores:
            seletor_formas.set_active(list(seletores).index(forma_anterior))
        geometria_anterior = transform_geom("EPSG:4326", crs, roi_anterior["geometry"])
        desenhar(geometria_anterior["coordinates"][0][:-1])

    def salvar(event):
        try:
            cena_exibida = previas.cenas[estado["indice_cena"]]
            imagens_escolhidas = [
                identificar_cena(cena)
                for cena, marcada in zip(previas.cenas, caixas_imagens.get_status())
                if marcada
            ]
            if not imagens_escolhidas:
                raise ValueError("Marque pelo menos uma imagem para a análise.")
            if estado["vertices"] is None:
                salvar_imagem_inteira(
                    destino, cena_exibida["caminho"], imagens_escolhidas
                )
            else:
                salvar_roi(
                    estado["vertices"],
                    crs,
                    destino,
                    estado["forma"],
                    cena_exibida["caminho"],
                    imagens_selecionadas=imagens_escolhidas,
                )
        except ValueError as exc:
            messagebox.showerror("ROI inválida", str(exc))
            return
        estado["salvou"] = True
        plt.close(figura)

    botao_salvar.on_clicked(salvar)
    botao_limpar.on_clicked(lambda event: mudar(estado["forma"]))
    botao_cancelar.on_clicked(lambda event: plt.close(figura))
    plt.show(block=True)
    return 0 if estado["salvou"] else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--imagem", required=True)
    parser.add_argument("--saida", default="saida/roi.geojson")
    parser.add_argument(
        "--cena",
        action="append",
        help="Empilhamento disponível no slider; pode ser repetido.",
    )
    args = parser.parse_args()
    sys.exit(janela_roi(args.imagem, args.saida, args.cena))
