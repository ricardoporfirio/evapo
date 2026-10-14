"""Aplicativo de desktop: entradas, ROI, processamento e inspeção dos pixels."""

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import matplotlib

matplotlib.use("TkAgg")
import numpy as np
import rasterio
from matplotlib.patches import Polygon
from matplotlib.ticker import MaxNLocator
from matplotlib.widgets import EllipseSelector, PolygonSelector, RectangleSelector
from rasterio.warp import transform_geom

from evapo.interface.acoes_projeto import AcoesProjeto
from evapo.dados.area import usar_imagem_inteira
from evapo.calculos.energia import validar_temperatura_ar
from evapo.calculos.aceleracao import descricao_aceleracao
from evapo.calculos.estatisticas import intervalo_dados
from evapo.calculos.produtos import PRODUTOS, DEPENDENCIAS_MDE, DEPENDENCIAS_AR
from evapo.mapa.cache_vistas import CacheVistas
from evapo.interface.layout import montar_interface
from evapo.mapa.leitura import consultar_pixel, ler_vista, localizar_extremo
from evapo.dados.metadados import descobrir_cenas
from evapo.mapa.navegacao import NavegacaoMapa
from evapo.dados.projetos import gravar_documento
from evapo.mapa.roi import carregar_roi, gravar_selecao, salvar_imagem_inteira, salvar_roi
from evapo.dados.selecao import identificar_cena

ESCALAS = {rotulo: (*limites, cores) for rotulo, limites, cores, _ in PRODUTOS.values()}
logger = logging.getLogger(__name__)


class SistemaEvapo(AcoesProjeto):
    def __init__(self, janela, projeto):
        self.janela = janela
        self.projeto = Path(projeto)
        self.entrada = None
        self.saida = self.projeto / "saida"
        self.mde = None
        self.temperatura_ar = tk.StringVar(value="")
        self.l_savi = tk.StringVar(value="0.5")
        self.roi = None
        self.cenas = []
        self.marcadas = []
        self.indice = 0
        self.crs = None
        self.contorno = None
        self.camada = None
        self.barra = None
        self.marcador = None
        self.geracao = 0
        self.fila = queue.Queue()
        self.processo = None
        self.processando = False
        self.relatorio_processado = None
        self.carregando = False
        self.cache_vistas = CacheVistas()
        self.leitura_em_andamento = False
        self.leitura_pendente = None
        self.timer_desenho = None
        self.produto_exibido = None
        self.vista_exibida = None
        self.mapa_ativo = False
        janela.title("Evapo — análise Landsat")
        janela.geometry("1400x920")
        janela.minsize(1080, 740)
        self.produto = tk.StringVar(value="NDVI")
        self.ferramenta = tk.StringVar(value="Consultar")
        self.pastagens = tk.BooleanVar(value=False)
        self.ano = tk.StringVar(value="2025")
        self.status = tk.StringVar(value="Abra a pasta das imagens para começar.")
        self.area = tk.StringVar(value="Imagem inteira")
        self.resumo_analise = tk.StringVar()
        self.estado_processamento = tk.StringVar(value="Pronto para processar")
        self.execucao_selecionada = tk.StringVar(value="Sem execuções")
        self.preparar_projeto()
        montar_interface(self, ESCALAS)
        self.navegacao = NavegacaoMapa(
            self.eixo, self.ativar_seletor, self.agendar_desenho,
            ao_terminar=lambda: self.agendar_vista(self.eixo),
        )
        self.seletores = {
            "Retângulo": RectangleSelector(
                self.eixo, self.desenhar_caixa, button=[1], useblit=False
            ),
            "Círculo": EllipseSelector(
                self.eixo, self.desenhar_circulo, button=[1], useblit=False
            ),
            "Polígono": PolygonSelector(self.eixo, self.definir_roi, useblit=False),
        }
        self.mudar_ferramenta()
        self.canvas.mpl_connect("button_release_event", self.clique_pixel)
        self.eixo.callbacks.connect("xlim_changed", self.agendar_vista)
        self.eixo.callbacks.connect("ylim_changed", self.agendar_vista)
        self.timer_vista = None
        self.janela.protocol("WM_DELETE_WINDOW", self.fechar)
        self.janela.after(80, self.receber_resultados)
        self.timer_inicial = self.janela.after(150, self.iniciar_sessao)
        for variavel in (self.produto, self.pastagens, self.ano, self.temperatura_ar, self.l_savi):
            variavel.trace_add("write", self.registrar_alteracao)
        self.temperatura_ar.trace_add("write", self.atualizar_temperatura_ar)
        self.l_savi.trace_add("write", self.atualizar_temperatura_ar)
        for atalho, acao in (
            ("<Control-n>", self.novo_projeto),
            ("<Control-o>", self.abrir_projeto),
            ("<Control-s>", self.salvar_projeto),
            ("<Control-Shift-S>", lambda: self.salvar_projeto(como=True)),
            ("<Control-z>", self.desfazer),
            ("<Control-y>", self.refazer),
        ):

            def executar_atalho(evento, comando=acao):
                comando()
                return "break"

            janela.bind(atalho, executar_atalho)

    def atualizar_temperatura_ar(self, *args):
        if not self.aplicando_projeto:
            self.atualizar_vista()

    def valor_l_savi(self):
        campo = getattr(self, "l_savi", None)
        try:
            valor = float(campo.get().replace(",", ".")) if campo is not None else 0.5
        except (TypeError, ValueError):
            raise ValueError("L do SAVI deve ser um número entre 0 e 1.") from None
        if not np.isfinite(valor) or not 0 <= valor <= 1:
            raise ValueError("L do SAVI deve ser um número entre 0 e 1.")
        return valor

    def atualizar_resumo(self):
        quantidade = sum(marcada.get() for marcada in self.marcadas)
        area = "Imagem inteira" if usar_imagem_inteira(self.roi) else "ROI desenhada"
        self.ano_pastagens.configure(
            state="normal" if self.pastagens.get() else "disabled"
        )
        self.area.set(area)
        self.resumo_analise.set(
            f"{quantidade} imagens selecionadas\nÁrea: {area}\n"
            + (
                f"Elevação: {Path(self.mde).name}"
                if self.mde
                else "Sem MDE: albedo da superfície e radiações dependentes de altitude ficam pendentes"
            )
            + (
                f"\nPastagens: MapBiomas {self.ano.get()}"
                "\nCobertura e vigor por classe. Requer internet na primeira análise."
                if self.pastagens.get()
                else ""
            )
            + (
                f"\nTemperatura do ar: {self.temperatura_ar.get()} °C (todas as datas)"
                if self.temperatura_ar.get().strip()
                else "\nSem temperatura do ar: onda longa incidente e saldo de radiação ficam pendentes"
            )
            + f"\nL do SAVI: {self.l_savi.get()}"
            + f"\nCálculo automático: {descricao_aceleracao(inicializar=False)}"
            + f"\nDestino: {self.saida}"
        )
        if not self.processando:
            self.botao_processar.configure(state="normal" if quantidade else "disabled")

    def mudar_pagina(self):
        if self.paginas.get() == "Mapa":
            self.lateral.grid()
            self.paginas.grid_configure(column=1, columnspan=1, padx=(4, 14))
        else:
            self.lateral.grid_remove()
            self.paginas.grid_configure(column=0, columnspan=2, padx=14)
        self.painel_resultados.definir_visibilidade(self.paginas.get() == "Resultados")

    def tarefa(self, funcao, retorno):
        def executar():
            try:
                self.fila.put((retorno, funcao(), None))
            except Exception as erro:
                logger.exception("Erro na leitura do mapa")
                self.fila.put((retorno, None, str(erro)))

        threading.Thread(target=executar, daemon=True).start()

    def receber_resultados(self):
        while not self.fila.empty():
            retorno, resultado, erro = self.fila.get()
            if erro:
                self.status.set(erro)
                self.carregando = False
                messagebox.showerror("Evapo", erro)
            else:
                retorno(resultado)
        self.janela.after(80, self.receber_resultados)

    def abrir_entrada(self):
        pasta = filedialog.askdirectory(
            title="Pasta que contém as cenas Landsat",
            initialdir=self.entrada or self.projeto / "entrada",
        )
        if pasta:
            self.entrada = Path(pasta)
            self.imagens_projeto = None
            self.carregar_entrada()
            self.registrar_alteracao()

    def carregar_entrada(self):
        self.geracao += 1
        if self.timer_vista is not None:
            self.janela.after_cancel(self.timer_vista)
            self.timer_vista = None
        self.leitura_pendente = None
        self.mapa_ativo = False
        self.cenas = []
        self.marcadas = []
        self.crs = None
        self.indice = 0
        self.ultimo_pixel = None
        self.info_pixel.configure(state="normal")
        self.info_pixel.delete("1.0", "end")
        self.info_pixel.insert("end", "Selecione Consultar e clique no mapa.")
        self.info_pixel.configure(state="disabled")
        for filho in self.lista_datas.winfo_children():
            filho.destroy()
        self.cache_vistas = CacheVistas()
        self.vista_exibida = None
        for nome in ("contorno", "camada", "marcador"):
            artista = getattr(self, nome)
            if artista is not None:
                artista.remove()
                setattr(self, nome, None)
        self.eixo_cores.set_visible(False)
        self.eixo.set_title("Escolha uma data para carregar o mapa")
        self.canvas.draw_idle()
        if self.entrada is None:
            self.eixo.set_title("Abra uma pasta de imagens para começar")
            self.data_visivel.configure(text="Sem imagens abertas")
            self.atualizar_resumo()
            return
        try:
            self.cenas = descobrir_cenas(self.entrada)
            escolhidas = self.imagens_projeto
            for filho in self.lista_datas.winfo_children():
                filho.destroy()
            self.marcadas = []
            for indice, cena in enumerate(self.cenas):
                marcada = tk.BooleanVar(
                    value=escolhidas is None or identificar_cena(cena) in escolhidas
                )
                self.marcadas.append(marcada)
                linha = ctk.CTkFrame(self.lista_datas, fg_color="transparent")
                linha.pack(fill="x")
                ctk.CTkCheckBox(
                    linha,
                    text="",
                    variable=marcada,
                    width=28,
                    checkbox_width=20,
                    checkbox_height=20,
                    command=self.registrar_alteracao,
                ).pack(side="left")
                ctk.CTkButton(
                    linha,
                    height=36,
                    fg_color="#e5edf3",
                    text_color="#203744",
                    hover_color="#cbdde7",
                    text=f"{cena['data']} · {cena['satelite'].replace('LANDSAT_', 'L')}",
                    command=lambda i=indice: self.mostrar_data(i),
                ).pack(side="left", fill="x", expand=True)
            self.mostrar_data(0, restaurar=True, carregar=False)
            self.atualizar_resumo()
        except (OSError, ValueError) as erro:
            self.cenas = []
            self.marcadas = []
            for filho in self.lista_datas.winfo_children():
                filho.destroy()
            for nome in ("contorno", "camada", "marcador"):
                artista = getattr(self, nome)
                if artista is not None:
                    artista.remove()
                    setattr(self, nome, None)
            self.eixo_cores.set_visible(False)
            self.data_visivel.configure(text="Sem imagens")
            self.canvas.draw_idle()
            messagebox.showerror("Entradas", str(erro))

    def abrir_saida(self):
        pasta = filedialog.askdirectory(
            title="Pasta de resultados", initialdir=self.saida
        )
        if pasta:
            self.saida = Path(pasta)
            self.relatorio_processado = None
            self.status.set(f"Resultados em: {self.saida}")
            self.atualizar_resumo()
            self.registrar_alteracao()

    def abrir_mde(self):
        caminho = filedialog.askopenfilename(
            title="Modelo de elevação MDE/SRTM — selecione o raster .img ou .tif",
            filetypes=[
                ("Modelo de elevação (IMG ou GeoTIFF)", "*.img *.IMG *.tif *.TIF *.tiff *.TIFF"),
                ("ERDAS Imagine", "*.img *.IMG"),
                ("GeoTIFF", "*.tif *.TIF *.tiff *.TIFF"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if caminho:
            try:
                with rasterio.open(caminho) as modelo:
                    if modelo.count != 1 or modelo.crs is None:
                        raise ValueError("O MDE precisa ter uma banda de altitude em metros e CRS definido.")
            except (rasterio.errors.RasterioError, OSError, ValueError) as erro:
                messagebox.showerror(
                    "Modelo de elevação",
                    f"Selecione o raster de altitude .img ou .tif extraído do ZIP.\n\n{erro}",
                )
                return
            self.mde = caminho
            self.registrar_alteracao()
            self.atualizar_resumo()
            self.atualizar_vista()

    def abrir_roi(self):
        caminho = filedialog.askopenfilename(
            title="ROI salva", filetypes=[("GeoJSON", "*.geojson")]
        )
        if caminho:
            try:
                self.roi = carregar_roi(caminho)
                self.registrar_alteracao()
                self.desenhar_contorno()
                self.atualizar_vista()
            except (OSError, ValueError) as erro:
                messagebox.showerror("ROI", str(erro))

    def imagem_inteira(self):
        self.roi = None
        self.registrar_alteracao()
        for seletor in self.seletores.values():
            seletor.clear()
        self.desenhar_contorno()
        self.atualizar_vista()

    def salvar_selecao(self, caminho=None):
        escolhidas = [
            identificar_cena(c)
            for c, marcada in zip(self.cenas, self.marcadas)
            if marcada.get()
        ]
        if not escolhidas:
            messagebox.showerror("Seleção", "Marque pelo menos uma imagem.")
            return False
        caminho = caminho or self.saida / "roi.geojson"
        if usar_imagem_inteira(self.roi):
            salvar_imagem_inteira(caminho, imagens_selecionadas=escolhidas)
        else:
            selecao = deepcopy(self.roi)
            selecao.setdefault("properties", {})["imagens_selecionadas"] = escolhidas
            gravar_selecao(selecao, caminho)
        self.status.set(f"Seleção salva: {len(escolhidas)} imagens.")
        return True

    def mostrar_data(self, indice, restaurar=False, carregar=True):
        if not self.cenas:
            return
        self.ultimo_pixel = None
        self.indice = indice
        self.mapa_ativo = carregar
        if carregar:
            self.paginas.set("Mapa")
            self.mudar_pagina()
        cena = self.cenas[indice]
        self.data_visivel.configure(
            text=f"{indice + 1}/{len(self.cenas)} · {cena['data']}"
            if carregar else "Escolha uma data"
        )
        with rasterio.open(cena["caminho"]) as imagem:
            mudou_crs = self.crs != imagem.crs
            self.crs = imagem.crs
            self.limites_totais = imagem.bounds
            self.resolucao_nativa = max(imagem.res)
        if restaurar or mudou_crs or self.camada is None:
            if not usar_imagem_inteira(self.roi):
                from rasterio.features import bounds

                geometria = transform_geom("EPSG:4326", self.crs, self.roi["geometry"])
                esquerda, inferior, direita, superior = bounds(geometria)
                self.carregando = True
                self.eixo.set_xlim(esquerda, direita)
                self.eixo.set_ylim(inferior, superior)
                self.carregando = False
                self.atualizar_vista()
            else:
                self.ver_tudo()
        else:
            self.atualizar_vista()
        self.desenhar_contorno()

    def trocar_data(self, passo):
        if self.cenas:
            self.mostrar_data(max(0, min(len(self.cenas) - 1, self.indice + passo)))

    def ver_tudo(self):
        if not self.cenas:
            return
        self.carregando = True
        self.eixo.set_xlim(self.limites_totais.left, self.limites_totais.right)
        self.eixo.set_ylim(self.limites_totais.bottom, self.limites_totais.top)
        self.carregando = False
        self.atualizar_vista()

    def agendar_vista(self, eixo):
        if self.carregando or not self.cenas:
            return
        # Uma leitura da posição anterior não pode substituir a vista em movimento.
        self.geracao += 1
        self.leitura_pendente = None
        if self.timer_vista:
            self.janela.after_cancel(self.timer_vista)
        self.timer_vista = self.janela.after(220, self.atualizar_vista)

    def agendar_desenho(self):
        # Agrupa eventos rápidos do mouse, em vez de renderizar cada evento.
        if self.timer_desenho is None:
            self.timer_desenho = self.janela.after(16, self.desenhar_mapa)

    def desenhar_mapa(self):
        self.timer_desenho = None
        self.canvas.draw_idle()

    def atualizar_vista(self):
        if self.timer_vista is not None:
            self.janela.after_cancel(self.timer_vista)
        self.timer_vista = None
        if not self.cenas or not self.mapa_ativo:
            return
        if self.navegacao.inicio_do_movimento is not None:
            return
        produto_id = next((k for k, v in PRODUTOS.items() if v[0] == self.produto.get()), None)
        if produto_id in DEPENDENCIAS_MDE and not self.mde:
            self.status.set(
                "Escolha um modelo de elevação para este produto."
            )
            return
        try:
            temperatura_ar = validar_temperatura_ar(self.temperatura_ar.get())
            L = self.valor_l_savi()
        except ValueError as erro:
            self.status.set(str(erro))
            return
        if produto_id in DEPENDENCIAS_AR and temperatura_ar is None:
            self.status.set("Informe a temperatura do ar para este produto.")
            return
        self.geracao += 1
        geracao = self.geracao
        cena, roi, mde = self.cenas[self.indice], self.roi, self.mde
        x, y = self.eixo.get_xlim(), self.eixo.get_ylim()
        limites = (min(x), min(y), max(x), max(y))
        if (
            limites[2] <= self.limites_totais.left
            or limites[0] >= self.limites_totais.right
            or limites[3] <= self.limites_totais.bottom
            or limites[1] >= self.limites_totais.top
        ):
            self.status.set("Fora da imagem. Use Ver tudo para retornar.")
            return
        bordas = self.limites_totais
        limites = (
            max(limites[0], bordas.left),
            max(limites[1], bordas.bottom),
            min(limites[2], bordas.right),
            min(limites[3], bordas.top),
        )
        chave = (
            str(cena["caminho"]),
            str((roi or {}).get("geometry")),
            mde,
            temperatura_ar,
            L,
        )
        resolucao = max(
            self.resolucao_nativa,
            max(limites[2] - limites[0], limites[3] - limites[1]) / 800,
        )
        existente = self.cache_vistas.buscar(chave, limites, resolucao, self.produto.get())
        if existente is not None:
            self.leitura_pendente = None
            self.exibir(existente, geracao)
            return
        # Uma borda extra permite mover a vista sem reler o arquivo imediatamente.
        margem_x = (limites[2] - limites[0]) * 0.2
        margem_y = (limites[3] - limites[1]) * 0.2
        leitura = (
            limites[0] - margem_x,
            limites[1] - margem_y,
            limites[2] + margem_x,
            limites[3] + margem_y,
        )
        self.leitura_pendente = (cena, leitura, roi, mde, chave, geracao, temperatura_ar,
                                self.produto.get(), L)
        self.iniciar_leitura()

    def iniciar_leitura(self):
        if self.leitura_em_andamento or self.leitura_pendente is None:
            return
        if self.navegacao.inicio_do_movimento is not None:
            return
        pedido = self.leitura_pendente
        self.leitura_pendente = None
        self.leitura_em_andamento = True
        self.status.set("Carregando detalhe do mapa…")

        def executar():
            cena, limites, roi, mde, chave, geracao, temperatura_ar, produto, L = pedido
            try:
                resultado = ler_vista(cena, limites, roi, mde, tamanho=1200,
                                     temperatura_ar=temperatura_ar, produto=produto, L=L)
                resposta = (chave, geracao, resultado, None)
            except Exception as erro:
                logger.exception("Erro na leitura da vista")
                resposta = (chave, geracao, None, str(erro))
            self.fila.put((self.finalizar_leitura, resposta, None))

        threading.Thread(target=executar, daemon=True).start()

    def finalizar_leitura(self, resposta):
        chave, geracao, resultado, erro = resposta
        self.leitura_em_andamento = False
        if resultado is not None:
            # Uma leitura ultrapassada ainda pode servir ao destino do arrasto.
            self.cache_vistas.guardar(chave, resultado)
            self.exibir(resultado, geracao)
            if hasattr(self, "resumo_analise"):
                self.atualizar_resumo()
            if self.leitura_pendente is not None:
                self.atualizar_vista()
        elif geracao == self.geracao:
            self.status.set(erro)
        self.iniciar_leitura()

    def exibir(self, resultado, geracao):
        if geracao != self.geracao:
            return
        if (self.camada is not None and self.vista_exibida is resultado
                and self.produto_exibido == self.produto.get()):
            self.status.set("Vista pronta. Clique para consultar o pixel nativo.")
            return
        produtos, limites, _qa, _saturacao = resultado
        self.carregando = True
        x, y = self.eixo.get_xlim(), self.eixo.get_ylim()
        esquerda, inferior, direita, superior = limites
        nome = self.produto.get()
        if nome not in produtos:
            self.carregando = False
            self.status.set("Produto indisponível nesta cena: confira B10, MDE e temperatura do ar.")
            return
        opcoes = {}
        if nome != "RGB":
            minimo, maximo, cores = ESCALAS[nome]
            minimo, maximo = intervalo_dados(produtos[nome], (minimo, maximo))
            opcoes = {
                "vmin": minimo,
                "vmax": maximo,
                "cmap": matplotlib.colormaps[cores].with_extremes(bad="#e5e7eb"),
            }
        extensao = (esquerda, direita, inferior, superior)
        dados = produtos[nome]
        if nome == "RGB":
            # Cores de tela em bytes evitam converter toda a imagem RGBA a cada
            # arrasto. Os arrays científicos e as consultas permanecem intactos.
            dados = np.round(np.clip(dados, 0, 1) * 255).astype("uint8")
        if self.camada is None:
            self.camada = self.eixo.imshow(
                dados, extent=extensao, interpolation="nearest",
                interpolation_stage="data", **opcoes
            )
        else:
            self.camada.set_data(dados)
            self.camada.set_extent(extensao)
            if nome != "RGB":
                if self.produto_exibido != nome:
                    self.camada.set_cmap(opcoes["cmap"])
                if self.camada.get_clim() != (opcoes["vmin"], opcoes["vmax"]):
                    self.camada.set_clim(opcoes["vmin"], opcoes["vmax"])
        # A escala fica em um eixo fixo; navegar não cria novos eixos ou layouts.
        if nome != "RGB":
            self.eixo_cores.set_visible(True)
            if self.barra is None:
                self.barra = self.figura.colorbar(self.camada, cax=self.eixo_cores)
            elif self.produto_exibido != nome:
                self.barra.update_normal(self.camada)
            unidade = next(v[3] for v in PRODUTOS.values() if v[0] == nome)
            self.barra.set_label(unidade)
        else:
            self.eixo_cores.set_visible(False)
        self.produto_exibido = nome
        self.vista_exibida = resultado
        self.eixo.set_xlim(x)
        self.eixo.set_ylim(y)
        self.eixo.set_title(
            f"{nome} — {self.cenas[self.indice]['data']} · cinza = sem dados"
        )
        self.eixo.ticklabel_format(style="plain", useOffset=False)
        self.eixo.xaxis.set_major_locator(MaxNLocator(nbins=5))
        self.eixo.yaxis.set_major_locator(MaxNLocator(nbins=5))
        self.eixo.tick_params(labelsize=9)
        self.canvas.draw_idle()
        self.carregando = False
        self.area.set(
            "Imagem inteira" if usar_imagem_inteira(self.roi) else "ROI desenhada"
        )
        self.status.set(
            f"Vista pronta. {descricao_aceleracao(inicializar=False)}. "
            "Clique para consultar o pixel nativo; use Mínimo/Máximo para localizar extremos."
        )

    def mudar_ferramenta(self):
        self.navegacao.escolher_modo(
            "mover" if self.ferramenta.get() == "Mover" else "desenhar"
        )

    def ativar_seletor(self, modo):
        if not hasattr(self, "seletores"):
            return
        for nome, seletor in self.seletores.items():
            ativo = modo == "desenhar" and self.ferramenta.get() == nome
            seletor.set_active(ativo)
            seletor.set_visible(ativo)

    def desenhar_caixa(self, inicial, final):
        if None in (inicial.xdata, inicial.ydata, final.xdata, final.ydata):
            return
        x1, x2 = sorted((inicial.xdata, final.xdata))
        y1, y2 = sorted((inicial.ydata, final.ydata))
        self.definir_roi([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])

    def desenhar_circulo(self, inicial, final):
        if None in (inicial.xdata, inicial.ydata, final.xdata, final.ydata):
            return
        x, y = (inicial.xdata + final.xdata) / 2, (inicial.ydata + final.ydata) / 2
        raio = (
            min(abs(final.xdata - inicial.xdata), abs(final.ydata - inicial.ydata)) / 2
        )
        angulos = np.linspace(0, 2 * np.pi, 128, endpoint=False)
        self.definir_roi(
            np.column_stack(
                [x + raio * np.cos(angulos), y + raio * np.sin(angulos)]
            ).tolist()
        )

    def definir_roi(self, vertices):
        if not self.mapa_ativo:
            self.status.set("Escolha uma data antes de desenhar a área no mapa.")
            return
        try:
            self.roi = salvar_roi(
                vertices,
                self.crs,
                None,
                forma=self.ferramenta.get(),
            )
            self.registrar_alteracao()
            self.desenhar_contorno()
            self.atualizar_vista()
        except ValueError as erro:
            messagebox.showerror("ROI", str(erro))

    def desenhar_contorno(self):
        self.atualizar_resumo()
        if self.contorno is not None:
            self.contorno.remove()
            self.contorno = None
        if not usar_imagem_inteira(self.roi) and self.crs:
            geometria = transform_geom("EPSG:4326", self.crs, self.roi["geometry"])
            self.contorno = Polygon(
                geometria["coordinates"][0],
                fill=False,
                edgecolor="#2563eb",
                linewidth=2,
                zorder=10,
            )
            self.eixo.add_patch(self.contorno)
        self.canvas.draw_idle()

    def clique_pixel(self, evento):
        if (
            evento.inaxes != self.eixo
            or evento.xdata is None
            or self.ferramenta.get() != "Consultar"
            or not self.cenas
            or not self.mapa_ativo
        ):
            return
        cena, roi, mde = self.cenas[self.indice], self.roi, self.mde
        x, y = evento.xdata, evento.ydata
        try:
            temperatura_ar = validar_temperatura_ar(self.temperatura_ar.get())
            L = self.valor_l_savi()
        except ValueError as erro:
            self.status.set(str(erro))
            return
        self.tarefa(
            lambda: consultar_pixel(cena, x, y, roi, mde, temperatura_ar, L=L),
            lambda info: self.exibir_pixel(info, x, y),
        )

    def exibir_pixel(self, info, x, y):
        if info is None:
            return
        self.ultimo_pixel = (x, y)
        linhas = [
            f"Linha {info['linha']} · coluna {info['coluna']} (base 0)",
            f"X {x:.2f} · Y {y:.2f}",
        ]
        for nome, valor in info["valores"].items():
            unidade = next((v[3] for v in PRODUTOS.values() if v[0] == nome), "adimensional")
            sufixo = f" {unidade}" if unidade != "adimensional" else ""
            linhas.append(
                f"{nome}: {valor:.6f}{sufixo}" if np.isfinite(valor) else f"{nome}: sem dados"
            )
        linhas += [
            f"QA: {info['qa']} · saturação: {info['saturacao']}",
            "Água (QA): sim" if info["qa"] & 128 else "Água (QA): não",
        ]
        self.info_pixel.configure(state="normal")
        self.info_pixel.delete("1.0", "end")
        self.info_pixel.insert("end", "\n".join(linhas))
        self.info_pixel.configure(state="disabled")
        if self.marcador is not None:
            self.marcador.remove()
        self.marcador = self.eixo.scatter(
            [x],
            [y],
            s=100,
            facecolors="none",
            edgecolors="#2563eb",
            linewidths=2,
            zorder=12,
        )
        self.canvas.draw_idle()

    def ir_extremo(self, minimo):
        if not self.cenas or not self.mapa_ativo or self.produto.get() == "RGB":
            return
        cena, nome, roi, mde = (
            self.cenas[self.indice],
            self.produto.get(),
            self.roi,
            self.mde,
        )
        if nome == "Albedo superfície" and not mde:
            messagebox.showinfo("MDE", "Escolha o modelo de elevação primeiro.")
            return
        try:
            temperatura_ar = validar_temperatura_ar(self.temperatura_ar.get())
            L = self.valor_l_savi()
        except ValueError as erro:
            messagebox.showinfo("Parâmetros da análise", str(erro))
            return
        self.status.set("Procurando o extremo nos pixels nativos…")

        def localizar(resultado):
            x, y, _valor = resultado
            with rasterio.open(cena["caminho"]) as imagem:
                raio = max(imagem.res) * 12
            self.carregando = True
            self.eixo.set_xlim(x - raio, x + raio)
            self.eixo.set_ylim(y - raio, y + raio)
            self.carregando = False
            self.atualizar_vista()
            self.tarefa(
                lambda: consultar_pixel(cena, x, y, roi, mde, temperatura_ar, L=L),
                lambda info: self.exibir_pixel(info, x, y),
            )

        self.tarefa(
            lambda: localizar_extremo(cena, nome, minimo, roi, mde, temperatura_ar, L=L), localizar
        )

    def processar(self):
        if self.processando:
            return
        if not any(marcada.get() for marcada in self.marcadas):
            messagebox.showinfo("Processamento", "Marque pelo menos uma imagem.")
            return
        try:
            temperatura_ar = validar_temperatura_ar(self.temperatura_ar.get())
            L = self.valor_l_savi()
        except ValueError as erro:
            messagebox.showerror("Processamento", str(erro))
            return
        self.registrar_alteracao()
        try:
            self.execucao_atual = self.doc.iniciar_execucao(self.saida)
            destino = Path(self.execucao_atual["pasta"])
            self.salvar_selecao(destino / "roi.geojson")
            self.execucao_selecionada.set(self.execucao_atual["nome"])
            self.alterado = True
            self.recuperar_automaticamente()
            self.atualizar_titulo()
        except OSError as erro:
            messagebox.showerror("Processamento", str(erro))
            return
        comando = [
            sys.executable,
            "-m",
            "evapo",
            "--entrada",
            str(self.entrada),
            "--saida",
            str(destino),
            "--sem-interface",
            "--L",
            str(L),
        ]
        if self.mde:
            comando += ["--mde", self.mde]
        if temperatura_ar is not None:
            comando += ["--temperatura-ar", str(temperatura_ar)]
        if self.pastagens.get():
            comando += ["--baixar-mapbiomas", self.ano.get()]
        self.relatorio_processado = (
            destino
            / (
                ("pastagens_imagem_completa" if usar_imagem_inteira(self.roi) else "pastagens")
                if self.pastagens.get()
                else ("imagem_completa" if usar_imagem_inteira(self.roi) else "roi")
            )
            / "relatorio.html"
        )
        self.botao_processar.configure(state="disabled")
        self.processando = True
        self.progresso.start()
        self.estado_processamento.set("Processando imagens…")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.status.set("Processando. Você pode continuar explorando o mapa.")

        def executar():
            try:
                ambiente = dict(os.environ, PYTHONIOENCODING="utf-8")
                self.processo = subprocess.Popen(
                    comando,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    env=ambiente,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                for linha in self.processo.stdout:
                    self.fila.put((self.escrever_log, linha, None))
                codigo = self.processo.wait()
            except Exception as erro:
                logger.exception("Erro no processamento")
                self.fila.put((self.escrever_log, str(erro), None))
                codigo = 1
            self.fila.put((self.terminou_processamento, codigo, None))

        threading.Thread(target=executar, daemon=True).start()

    def escrever_log(self, texto):
        if texto.startswith(("Dispositivo de cálculo:", "Dispositivo ao concluir:")):
            self.estado_processamento.set(texto.strip())
        self.log.configure(state="normal")
        self.log.insert("end", texto)
        self.log.see("end")
        self.log.configure(state="disabled")

    def terminou_processamento(self, codigo):
        self.processo = None
        self.processando = False
        if self.execucao_atual:
            self.execucao_atual["status"] = "concluido" if codigo == 0 else "falhou"
            destino = Path(self.execucao_atual["pasta"])
            gravar_documento(destino / "configuracao.evapo.json", self.doc.documento())
            (destino / "notas.txt").write_text(
                self.execucao_atual["estado"].get("notas", ""), encoding="utf-8"
            )
            self.recuperar_automaticamente()
        self.progresso.stop()
        self.progresso.set(0)
        self.botao_processar.configure(state="normal")
        self.estado_processamento.set(
            "Concluído" if codigo == 0 else "Falha: consulte as mensagens na aba Mapa"
        )
        self.status.set(
            "Processamento concluído. Resultados disponíveis nesta janela."
            if codigo == 0
            else "Falha no processamento. Confira as mensagens acima."
        )
        if codigo == 0:
            self.abrir_relatorio()

    def abrir_resultados(self):
        self.saida.mkdir(parents=True, exist_ok=True)
        os.startfile(self.saida)

    def abrir_relatorio(self):
        nome = self.execucao_selecionada.get()
        if self.doc.execucoes and not any(
            e["nome"] == nome for e in self.doc.execucoes
        ):
            nome = self.doc.execucoes[-1]["nome"]
            self.execucao_selecionada.set(nome)
        if any(e["nome"] == nome for e in self.doc.execucoes):
            self.escolher_execucao(nome)
            return
        pasta = "imagem_completa" if usar_imagem_inteira(self.roi) else "roi"
        caminho = self.relatorio_processado or self.saida / pasta / "relatorio.html"
        try:
            self.painel_resultados.atualizar(caminho.parent.parent, caminho.parent)
            self.paginas.set("Resultados")
            self.mudar_pagina()
        except (OSError, ValueError) as erro:
            messagebox.showerror(
                "Resultados", f"Não foi possível ler os resultados: {erro}"
            )

    def fechar(self):
        if self.processando and self.processo is None:
            messagebox.showinfo(
                "Processamento", "Aguarde o processamento iniciar antes de fechar."
            )
            return
        if self.processo is not None and not messagebox.askyesno(
            "Processamento em andamento", "Encerrar o processamento e fechar?"
        ):
            return
        self.registrar_alteracao()
        if self.alterado:
            resposta = messagebox.askyesnocancel(
                "Salvar projeto",
                "Salvar o projeto antes de fechar?\nA recuperação automática também mantém a última sessão.",
            )
            if resposta is None or (resposta and not self.salvar_projeto()):
                return
        if self.processo is not None:
            self.processo.terminate()
            if self.execucao_atual:
                self.execucao_atual["status"] = "interrompido"
        self.recuperar_automaticamente()
        self.painel_resultados.parar()
        self.janela.destroy()


def main():
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    janela = ctk.CTk()
    SistemaEvapo(janela, Path.cwd())
    janela.mainloop()


if __name__ == "__main__":
    main()
