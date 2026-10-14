"""Explora tabelas, figuras e animações salvas dentro do aplicativo."""

import csv
import json
import math
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import customtkinter as ctk
import numpy as np
from PIL import Image
from evapo.calculos.produtos import PRODUTOS
from evapo.dados.rasters_resultados import ler_previa, consultar_pixel, caminho_produto, histograma_produto
from evapo.calculos.estatisticas import ampliar_intervalo, intervalo_dados
from matplotlib.figure import Figure
from matplotlib import colormaps
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

AZUL = "#1e5b78"
TEXTO = "#203744"
SUAVE = "#607583"
ROTULOS_VIGOR = {"baixo": "Baixo", "moderado": "Moderado", "alto": "Alto"}
PRODUTOS_VISUAIS = {**PRODUTOS, "mascara_pastagem": ("Máscara de pastagem · vigor", (0, 4), "viridis", "classe")}
CLASSES_MASCARA = {0: "Fora da pastagem", 1: "Baixo vigor", 2: "Médio vigor", 3: "Alto vigor", 4: "Pastagem sem vigor classificado"}
CORES_MASCARA = ["#eeeeee", "#fa6970", "#f7b47e", "#44b160", "#9ca3af"]


def rotulo_produto(nome):
    nomes = {
        "mascara_pastagem": "Máscara de pastagem",
        "albedo_toa": "Albedo no topo da atmosfera",
        "albedo_superficie": "Albedo da superfície",
        "emissividade": "Emissividade da superfície",
        "emissividade_atmosferica": "Emissividade da atmosfera",
        "temperatura_superficie": "Temperatura da superfície",
    }
    if nome in nomes:
        return nomes[nome]
    return PRODUTOS.get(nome, (nome.replace("_", " ").capitalize(),))[0]


def numero(valor):
    try:
        resultado = float(str(valor).replace(",", "."))
        return resultado if math.isfinite(resultado) else None
    except (ValueError, TypeError):
        return None


def formatar_numero(valor, casas=4):
    valor = numero(valor)
    if valor is None:
        return "—"
    return f"{valor:,.{casas}f}".translate(str.maketrans({",": ".", ".": ","}))


def formatar_data(valor):
    partes = valor.split("-")
    return "/".join(reversed(partes)) if len(partes) == 3 else valor


class PainelResultados(ctk.CTkFrame):
    def __init__(self, pai):
        super().__init__(pai, fg_color="white", corner_radius=12)
        self.pastas = {}
        self.mascaras = {}
        self.aplicar_mascara = tk.BooleanVar(value=False)
        self.registros = []
        self.filtrados = []
        self.animacao = None
        self.timer = None
        self.quadro = 0
        self.registro_figura = None
        self.figura_exibida = None
        self.escopo_exibido = None
        self.visivel = False
        self.imagens_carregadas = {}
        self.timer_figuras = None
        self.ordenacao = (None, False)
        self.janela_figura = None
        self.canvas_mapa = None
        self.canvas_histograma = None
        self.eixo_mapa = None
        self.marcador_pixel = None
        self.ultimo_pixel = None
        self.consulta_pixel = tk.StringVar(value="Selecione um produto para visualizar.")
        self.imagem_vazia = ctk.CTkImage(
            light_image=Image.new("RGB", (1, 1), "white"), size=(1, 1)
        )
        self.analise = tk.StringVar()
        self.data = tk.StringVar(value="Todas")
        self.produto = tk.StringVar(value="Todos")
        self.vigor = tk.StringVar(value="Todos")
        self.resumo = tk.StringVar(
            value="Processe as imagens para ver os resultados aqui."
        )
        controles = ctk.CTkFrame(self, fg_color="#f2f6f9", corner_radius=10)
        controles.pack(fill="x", padx=12, pady=(12, 0))
        for coluna, (texto, peso) in enumerate((("Análise", 2), ("Data", 1), ("Produto", 2), ("Classe de vigor", 1))):
            controles.grid_columnconfigure(coluna, weight=peso, uniform="filtros")
            ctk.CTkLabel(controles, text=texto, anchor="w", text_color=SUAVE,
                         font=("Segoe UI", 12)).grid(row=0, column=coluna, sticky="ew", padx=10, pady=(8, 0))
        self.escolha_analise = ctk.CTkOptionMenu(
            controles,
            variable=self.analise,
            values=["Sem resultados"],
            command=self.carregar,
            fg_color=AZUL, button_color=AZUL, dynamic_resizing=False,
        )
        self.escolha_analise.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.escolha_data = ctk.CTkOptionMenu(
            controles,
            variable=self.data,
            values=["Todas"],
            command=self.filtrar,
            width=135,
            fg_color=AZUL, button_color=AZUL, dynamic_resizing=False,
        )
        self.escolha_data.grid(row=1, column=1, sticky="ew", padx=10, pady=(0, 10))
        self.escolha_produto = ctk.CTkOptionMenu(
            controles,
            variable=self.produto,
            values=["Todos"],
            command=self.filtrar,
            width=135,
            fg_color=AZUL, button_color=AZUL, dynamic_resizing=False,
        )
        self.escolha_produto.grid(row=1, column=2, sticky="ew", padx=10, pady=(0, 10))
        self.escolha_vigor = ctk.CTkOptionMenu(
            controles,
            variable=self.vigor,
            values=["Todos"],
            command=self.filtrar,
            width=110,
            fg_color=AZUL, button_color=AZUL, dynamic_resizing=False,
        )
        self.escolha_vigor.grid(row=1, column=3, sticky="ew", padx=10, pady=(0, 10))
        faixa = ctk.CTkFrame(self, fg_color="transparent")
        faixa.pack(fill="x", padx=16, pady=(4, 0))
        ctk.CTkLabel(faixa, textvariable=self.resumo, anchor="w", text_color=SUAVE).pack(side="left")
        ctk.CTkButton(faixa, text="Ver todos na tabela", command=self.ver_todos, width=135,
                      fg_color="#e5edf3", text_color=TEXTO, hover_color="#d4e2ec").pack(side="right")
        self.abas = ctk.CTkTabview(self, fg_color="white", command=self.mudar_aba, anchor="nw",
                                   segmented_button_selected_color=AZUL)
        self.abas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        visualizacao = self.abas.add("Visualização")
        visualizacao.grid_columnconfigure(0, weight=1)
        visualizacao.grid_rowconfigure(0, weight=1)
        self.janela_tabela = ctk.CTkToplevel(self)
        self.janela_tabela.withdraw()
        self.janela_tabela.title("Estatísticas da análise")
        self.janela_tabela.geometry("1100x680")
        self.janela_tabela.minsize(640, 420)
        self.janela_tabela.transient(self.winfo_toplevel())
        self.janela_tabela.protocol("WM_DELETE_WINDOW", self.fechar_tabela)
        self.janela_tabela.bind("<Escape>", lambda e: self.fechar_tabela())
        tabela = ctk.CTkFrame(self.janela_tabela, fg_color="white")
        tabela.pack(fill="both", expand=True, padx=12, pady=12)
        rodape = ctk.CTkFrame(self.janela_tabela, fg_color="transparent")
        rodape.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkLabel(rodape, text="Selecione uma linha para consultar suas estatísticas.",
                     text_color=SUAVE).pack(side="left")
        ctk.CTkButton(rodape, text="Ver resultado selecionado", command=self.ver_linha,
                      fg_color=AZUL).pack(side="right")
        ctk.CTkButton(faixa, text="Tabela de estatísticas", width=155,
                      command=self.abrir_tabela, fg_color=AZUL).pack(side="right", padx=8)
        temporal = self.abas.add("Time lapse")
        colunas = (
            "data",
            "vigor",
            "produto",
            "unidade", "pixels_validos",
            "cobertura_percentual",
            "media",
            "minimo",
            "maximo",
        )
        tabela.grid_columnconfigure(0, weight=1)
        tabela.grid_rowconfigure(0, weight=2, minsize=100)
        tabela.grid_rowconfigure(1, weight=3, minsize=190)
        lista = ctk.CTkFrame(tabela, fg_color="transparent")
        lista.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        lista.grid_columnconfigure(0, weight=1)
        lista.grid_rowconfigure(0, weight=1)
        estilo = ttk.Style()
        estilo.configure("Evapo.Treeview", rowheight=29, font=("Segoe UI", 10),
                          background="white", fieldbackground="white", foreground=TEXTO, borderwidth=0)
        estilo.configure("Evapo.Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=(6, 7))
        estilo.map("Evapo.Treeview", background=[("selected", AZUL)], foreground=[("selected", "white")])
        self.tabela = ttk.Treeview(
            lista, columns=colunas, show="headings", style="Evapo.Treeview", height=6, selectmode="browse"
        )
        nomes = (
            "Data",
            "Vigor",
            "Produto",
            "Unidade",
            "Pixels válidos",
            "Cobertura (%)",
            "Média",
            "Mínimo",
            "Máximo",
        )
        self.nomes_colunas = dict(zip(colunas, nomes))
        for chave, nome in zip(colunas, nomes):
            self.tabela.heading(chave, text=nome, command=lambda c=chave: self.ordenar(c))
            self.tabela.column(
                chave,
                width={"produto": 240, "unidade": 105, "pixels_validos": 110,
                       "cobertura_percentual": 110}.get(chave, 90),
                minwidth=160 if chave == "produto" else 65,
                stretch=chave == "produto",
                anchor="w" if chave in ("data", "vigor", "produto", "unidade") else "e",
            )
        self.tabela.tag_configure("alternada", background="#f1f5f8")
        self.tabela.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(lista, orient="vertical", command=self.tabela.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(
            lista, orient="horizontal", command=self.tabela.xview
        )
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tabela.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        self.tabela.bind("<<TreeviewSelect>>", self.selecionar_linha)
        self.tabela.bind("<Double-1>", lambda evento: self.ver_linha())
        self.tabela.bind("<Return>", lambda evento: self.ver_linha())
        consulta = ctk.CTkFrame(tabela, fg_color="transparent")
        consulta.grid(row=1, column=0, sticky="nsew")
        consulta.grid_columnconfigure(0, weight=1)
        consulta.grid_rowconfigure(0, weight=1)
        detalhes = ctk.CTkFrame(consulta, width=255, fg_color="#f2f6f9", corner_radius=10)
        detalhes.grid(row=0, column=0, sticky="nsew")
        detalhes.grid_columnconfigure(0, weight=1)
        detalhes.grid_rowconfigure(2, weight=1)
        self.titulo_selecao = tk.StringVar(value="Selecione um resultado")
        ctk.CTkLabel(detalhes, textvariable=self.titulo_selecao, font=("Segoe UI", 13, "bold"),
                     text_color=TEXTO, wraplength=230, justify="left", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        cards = ctk.CTkFrame(detalhes, fg_color="transparent")
        cards.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        self.metricas = {}
        for i, (chave, nome) in enumerate((("media", "Média"), ("cobertura_percentual", "Cobertura válida"), ("minimo", "Mínimo"), ("maximo", "Máximo"))):
            cards.grid_columnconfigure(i, weight=1, uniform="metricas")
            card = ctk.CTkFrame(cards, fg_color="white", corner_radius=8)
            card.grid(row=0, column=i, sticky="ew", padx=3, pady=3)
            ctk.CTkLabel(card, text=nome, text_color=SUAVE, font=("Segoe UI", 11)).pack(anchor="w", padx=8)
            self.metricas[chave] = tk.StringVar(value="—")
            ctk.CTkLabel(card, textvariable=self.metricas[chave], text_color=AZUL,
                         font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=8, pady=(0, 4))
        self.detalhes = ctk.CTkTextbox(
            detalhes, width=235, height=90, state="disabled", wrap="word", fg_color="transparent",
            text_color=TEXTO, font=("Segoe UI", 12),
        )
        self.detalhes.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self.figuras = ctk.CTkFrame(visualizacao, fg_color="#f2f6f9", corner_radius=10)
        self.figuras.grid(row=0, column=0, sticky="nsew")
        self.figuras.grid_columnconfigure(0, weight=1)
        self.figuras.grid_rowconfigure(1, weight=1)
        cabecalho_figuras = ctk.CTkFrame(self.figuras, fg_color="transparent")
        cabecalho_figuras.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        ctk.CTkLabel(cabecalho_figuras, textvariable=self.titulo_selecao, text_color=TEXTO,
                     font=("Segoe UI", 13, "bold")).pack(side="left")
        self.botao_ampliar = ctk.CTkButton(cabecalho_figuras, text="Ampliar", command=self.ampliar_figura,
                                          width=76, height=30, fg_color="#e5edf3", text_color=TEXTO, state="disabled")
        self.botao_ampliar.pack(side="right", padx=(6, 0))
        self.check_mascara = ctk.CTkCheckBox(
            cabecalho_figuras, text="Aplicar máscara de pastagem", variable=self.aplicar_mascara,
            command=self.alternar_mascara, text_color=TEXTO, fg_color=AZUL,
            checkbox_width=18, checkbox_height=18, state="disabled")
        self.check_mascara.pack(side="right", padx=12)
        self.botao_figuras = ctk.CTkButton(cabecalho_figuras, text="Ver mapa e histograma", command=self.carregar_figuras,
                                          fg_color=AZUL, width=166, height=30, state="disabled")
        self.paineis_figuras = ctk.CTkFrame(self.figuras, fg_color="white")
        self.paineis_figuras.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        self.paineis_figuras.grid_columnconfigure(0, weight=3, uniform="figuras")
        self.paineis_figuras.grid_columnconfigure(1, weight=2, uniform="figuras")
        self.paineis_figuras.grid_rowconfigure(0, weight=1)
        mapa = ctk.CTkFrame(self.paineis_figuras, fg_color="white")
        histograma = ctk.CTkFrame(self.paineis_figuras, fg_color="white")
        self.painel_mapa, self.painel_histograma = mapa, histograma
        mapa.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        histograma.grid(row=0, column=1, sticky="nsew")
        for painel in (mapa, histograma):
            painel.grid_columnconfigure(0, weight=1)
            painel.grid_rowconfigure(0, weight=1)
        consulta = ctk.CTkFrame(self.figuras, fg_color="transparent")
        consulta.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.botao_dados_pixel = ctk.CTkButton(
            consulta, text="Dados do pixel", command=self.abrir_dados_pixel,
            width=115, height=26, fg_color=AZUL, state="disabled")
        self.botao_dados_pixel.pack(side="right", padx=(8, 0))
        ctk.CTkLabel(consulta, textvariable=self.consulta_pixel, anchor="w",
                     wraplength=780, justify="left", text_color=TEXTO).pack(side="left", fill="x", expand=True)
        self.imagem_mapa = ctk.CTkLabel(
            mapa,
            text="Escolha a análise, a data e o produto para visualizar.",
            text_color="#203744",
        )
        self.imagem_mapa.grid(row=0, column=0, sticky="nsew")
        self.imagem_histograma = ctk.CTkLabel(histograma, text="", text_color="#203744")
        self.imagem_histograma.grid(row=0, column=0, sticky="nsew")
        self.figuras.bind("<Configure>", self.agendar_redimensionamento, add="+")
        ctk.CTkLabel(
            temporal, text="Animação dos produtos exportados, sem abrir o navegador.",
            text_color="#203744",
        ).pack(pady=8)
        self.produto_temporal = tk.StringVar(value="ndvi")
        self.escolha_temporal = ctk.CTkOptionMenu(
            temporal,
            variable=self.produto_temporal,
            values=["RGB", *[rotulo_produto(p) for p in PRODUTOS]],
            command=self.abrir_animacao,
            fg_color=AZUL, button_color=AZUL, width=240,
        )
        self.escolha_temporal.pack(pady=6)
        self.botao_play = ctk.CTkButton(
            temporal, text="Reproduzir", command=self.reproduzir
        )
        self.botao_play.pack(pady=6)
        self.imagem_temporal = ctk.CTkLabel(temporal, text="Sem animação carregada.",
                                         text_color="#203744")
        self.imagem_temporal.pack(fill="both", expand=True)

    def atualizar(self, saida, preferida=None):
        nomes = {
            "roi": "ROI",
            "imagem_completa": "Imagem inteira",
            "pastagens": "Pastagens · ROI",
            "pastagens_imagem_completa": "Pastagens · imagem inteira",
        }
        self.pastas = {}
        for pasta, nome in nomes.items():
            caminho = Path(saida) / pasta
            if (caminho / "estatisticas_todas_cenas_roi.csv").exists() or (
                caminho / "estatisticas_por_vigor.csv"
            ).exists():
                self.pastas[nome] = caminho
        self.escolha_analise.configure(values=list(self.pastas) or ["Sem resultados"])
        if self.pastas:
            escolhida = next(
                (
                    n
                    for n, p in self.pastas.items()
                    if preferida and p == Path(preferida)
                ),
                next(iter(self.pastas)),
            )
            self.analise.set(escolhida)
            self.carregar()
        else:
            self.analise.set("Sem resultados")
            self.mascaras = {}
            self.check_mascara.configure(state="disabled")
            self.registros = []
            self.data.set("Todas")
            self.produto.set("Todos")
            self.vigor.set("Todos")
            self.escolha_temporal.configure(values=["Sem animações"], state="disabled")
            self.produto_temporal.set("Sem animações")
            self.botao_play.configure(state="disabled")
            self.filtrar()
            self.limpar_animacao()
            self.resumo.set(
                "Nenhum resultado salvo nesta pasta. Use Processar imagens marcadas."
            )

    def carregar(self, valor=None):
        self.limpar_animacao()
        self.registro_figura = None
        self.figura_exibida = None
        self.imagens_carregadas.clear()
        self.botao_ampliar.configure(state="disabled")
        pasta = self.pastas.get(self.analise.get())
        if pasta is None:
            return
        csv_path = (
            pasta / "estatisticas_por_vigor.csv"
            if (pasta / "estatisticas_por_vigor.csv").exists()
            else pasta / "estatisticas_todas_cenas_roi.csv"
        )
        with csv_path.open(encoding="utf-8-sig", newline="") as arquivo:
            self.registros = list(csv.DictReader(arquivo, delimiter=";"))
        self.mascaras = {}
        pasta_pastagens = pasta.parent / ("pastagens_imagem_completa" if "imagem_completa" in pasta.name else "pastagens")
        for data in {r["data"] for r in self.registros}:
            for base in (pasta, pasta_pastagens):
                caminho = base / data / "classes_vigor.tif"
                if caminho.is_file():
                    self.mascaras[data] = caminho
                    break
        self.aplicar_mascara.set(False)
        self.data.set("Todas")
        self.produto.set("Todos")
        self.vigor.set("Todos")
        self.escolha_data.configure(
            values=[formatar_data(d) for d in sorted({r["data"] for r in self.registros})] or ["Sem datas"]
        )
        self.escolha_produto.configure(
            values=sorted({rotulo_produto(r["produto"]) for r in self.registros}
                          | ({rotulo_produto("mascara_pastagem")} if self.mascaras else set())) or ["Sem produtos"]
        )
        classes = {r["vigor"] for r in self.registros if r.get("vigor")}
        self.tabela.configure(displaycolumns=[c for c in self.tabela["columns"] if c != "vigor" or classes])
        self.escolha_vigor.configure(
            values=["Todos", *[ROTULOS_VIGOR.get(v, v) for v in ("baixo", "moderado", "alto") if v in classes]] if classes else ["Toda a área"],
            state="normal" if classes else "disabled",
        )
        animacoes = sorted(p.stem.removeprefix("timelapse_") for p in (pasta / "timelapse").glob("timelapse_*.gif"))
        self.escolha_temporal.configure(
            values=["RGB" if p == "rgb" else rotulo_produto(p) for p in animacoes] or ["Sem animações"],
            state="normal" if animacoes else "disabled",
        )
        self.botao_play.configure(state="normal" if animacoes else "disabled")
        selecionada = "ndvi" if "ndvi" in animacoes else (animacoes[0] if animacoes else "Sem animações")
        self.produto_temporal.set("RGB" if selecionada == "rgb" else rotulo_produto(selecionada))
        self.filtrar()
        if self.visivel and self.abas.get() == "Visualização":
            self.sincronizar_selecao()
            self.filtrar()

    def limpar_filtros(self):
        self.data.set("Todas")
        self.produto.set("Todos")
        self.vigor.set("Todos")
        self.filtrar()

    def filtrar(self, valor=None):
        self.filtrados = [
            r
            for r in self.registros
            if (self.data.get() == "Todas" or self.data.get() in (r["data"], formatar_data(r["data"])))
            and (self.produto.get() == "Todos" or self.produto.get() in (r["produto"], rotulo_produto(r["produto"])))
            and (self.vigor.get() == "Todos" or self.vigor.get() in (r.get("vigor"), ROTULOS_VIGOR.get(r.get("vigor"))))
        ]
        if self.produto.get() in ("mascara_pastagem", rotulo_produto("mascara_pastagem")):
            self.filtrados = []
            for data in sorted(self.mascaras):
                if self.data.get() != "Todas" and self.data.get() not in (data, formatar_data(data)):
                    continue
                self.filtrados.append({"data": data, "produto": "mascara_pastagem", "unidade": "classe",
                                       "satelite": next((r.get("satelite", "") for r in self.registros if r["data"] == data), "")})
        self.ordenacao = (None, False)
        self.preencher_tabela()
        datas = len({r["data"] for r in self.filtrados})
        self.resumo.set(f"{len(self.filtrados)} de {len(self.registros)} resultados · {datas} {'data' if datas == 1 else 'datas'} · análise salva")

    def ordenar(self, coluna):
        anterior, descendente = self.ordenacao
        descendente = not descendente if anterior == coluna else False
        numerica = coluna not in ("data", "produto", "vigor", "unidade")
        chave = lambda r: numero(r.get(coluna)) if numerica else str(r.get(coluna, ""))
        validos = [r for r in self.filtrados if chave(r) is not None]
        ausentes = [r for r in self.filtrados if chave(r) is None]
        self.filtrados = sorted(validos, key=chave, reverse=descendente) + ausentes
        self.ordenacao = (coluna, descendente)
        self.preencher_tabela()

    def preencher_tabela(self):
        selecionado = self.registro_figura
        coluna, descendente = self.ordenacao
        for chave, nome in self.nomes_colunas.items():
            self.tabela.heading(chave, text=nome + ((" ↓" if descendente else " ↑") if chave == coluna else ""))
        self.tabela.delete(*self.tabela.get_children())
        for indice, registro in enumerate(self.filtrados):
            valores = []
            for chave in self.tabela["columns"]:
                valor = registro.get(chave)
                if chave == "data":
                    valor = formatar_data(valor or "")
                elif chave == "produto":
                    valor = rotulo_produto(valor or "")
                elif chave == "vigor":
                    valor = ROTULOS_VIGOR.get(valor, valor or "—")
                elif chave == "unidade":
                    valor = valor or PRODUTOS.get(registro["produto"], (None, None, None, "—"))[3]
                else:
                    casas = 0 if chave == "pixels_validos" else (2 if chave == "cobertura_percentual" else 4)
                    valor = formatar_numero(valor, casas)
                valores.append(valor)
            self.tabela.insert("", "end", iid=str(indice), values=valores,
                               tags=("alternada",) if indice % 2 else ())
        if self.filtrados:
            indice = self.filtrados.index(selecionado) if selecionado in self.filtrados else 0
            self.tabela.selection_set(str(indice))
            self.tabela.see(str(indice))
            self.selecionar_linha()
        else:
            self.limpar_canvas()
            self.ultimo_pixel = None
            self.consulta_pixel.set("Nenhum resultado para esta seleção.")
            self.registro_figura = None
            self.figura_exibida = None
            self.imagens_carregadas.clear()
            self.botao_figuras.configure(state="disabled")
            self.botao_ampliar.configure(state="disabled")
            self.titulo_selecao.set("Nenhum resultado")
            for metrica in self.metricas.values():
                metrica.set("—")
            self.detalhes.configure(state="normal")
            self.detalhes.delete("1.0", "end")
            self.detalhes.configure(state="disabled")
            self.imagem_mapa.configure(
                image=self.imagem_vazia, text="Nenhum resultado para esta seleção."
            )
            self.imagem_histograma.configure(image=self.imagem_vazia, text="")

    def selecionar_linha(self, evento=None):
        selecao = self.tabela.selection()
        if not selecao:
            return
        registro = self.filtrados[int(selecao[0])]
        mascara = self.mascaras.get(registro["data"])
        categoria = registro["produto"] == "mascara_pastagem"
        pasta = self.pastas.get(self.analise.get())
        raster = pasta / registro["data"] / "rasters" / f"{registro['produto']}.tif" if pasta else None
        self.check_mascara.configure(state="normal" if mascara and raster and raster.is_file() and not categoria else "disabled")
        self.escolha_vigor.configure(state="normal" if registro.get("vigor") and self.aplicar_mascara.get() and not categoria else "disabled")
        produto = registro["produto"]
        unidade = registro.get("unidade") or PRODUTOS.get(produto, (None, None, None, "adimensional"))[3]
        classe = ROTULOS_VIGOR.get(registro.get("vigor"), "") if self.aplicar_mascara.get() else ""
        self.titulo_selecao.set(
            f"{rotulo_produto(produto)} · {formatar_data(registro['data'])}" + (f" · {classe}" if classe else "")
        )
        for chave, variavel in self.metricas.items():
            variavel.set(formatar_numero(registro.get(chave), 2 if chave == "cobertura_percentual" else 4)
                         + ("%" if chave == "cobertura_percentual" and numero(registro.get(chave)) is not None else ""))
        linhas = [f"Unidade: {unidade}"]
        if registro.get("satelite"):
            linhas.append(f"Satélite: {registro['satelite'].replace('_', ' ')}")
        for chave, nome, casas in (
            ("pixels_validos", "Pixels válidos", 0), ("pixels_totais", "Pixels da área", 0),
            ("area_classe_ha_grade", "Área da classe (ha)", 2), ("area_valida_ha_grade", "Área válida (ha)", 2),
            ("mediana", "Mediana", 5), ("desvio_padrao", "Desvio padrão", 5),
            ("minimo", "Mínimo", 5), ("maximo", "Máximo", 5),
            ("amplitude", "Amplitude", 5), ("variancia", "Variância", 5),
            ("q1", "1º quartil", 5), ("q3", "3º quartil", 5),
            ("p05", "Percentil 5", 5), ("p95", "Percentil 95", 5),
            ("intervalo_interquartil", "Intervalo interquartil", 5),
        ):
            if chave in registro:
                linhas.append(f"{nome}: {formatar_numero(registro[chave], casas)}")
        self.detalhes.configure(state="normal")
        self.detalhes.delete("1.0", "end")
        self.detalhes.insert("end", "\n".join(linhas))
        self.detalhes.configure(state="disabled")
        self.botao_figuras.configure(state="normal")
        if registro != self.registro_figura:
            self.registro_figura = registro
            self.figura_exibida = None
            self.imagens_carregadas.clear()
            self.botao_ampliar.configure(state="disabled")
            self.imagem_mapa.configure(
                image=self.imagem_vazia,
                text="Escolha a data e o produto para visualizar.",
            )
            self.imagem_histograma.configure(image=self.imagem_vazia, text="")
            self.limpar_canvas()
            self.ultimo_pixel = None
            if self.visivel and self.abas.get() == "Visualização":
                self.carregar_figuras()
        elif self.visivel and self.abas.get() == "Visualização":
            self.carregar_figuras()

    def carregar_figuras(self):
        registro = self.registro_figura
        escopo = (self.aplicar_mascara.get(), self.vigor.get())
        if registro is None or (self.figura_exibida == registro and self.escopo_exibido == escopo):
            return
        self.imagens_carregadas.clear()
        pasta = self.pastas[self.analise.get()] / registro["data"]
        if registro.get("vigor") and self.aplicar_mascara.get():
            pasta /= registro["vigor"]
        for widget, sufixo in (
            (self.imagem_mapa, "mapa"),
            (self.imagem_histograma, "histograma"),
        ):
            caminho = pasta / f"{registro['produto']}_{sufixo}.png"
            if caminho.exists():
                with Image.open(caminho) as origem:
                    imagem = origem.copy()
                self.imagens_carregadas[sufixo] = imagem
            else:
                widget.configure(
                    image=self.imagem_vazia, text="Figura não disponível nesta análise."
                )
        self.mostrar_mapa_interativo(registro)
        self.mostrar_histograma_interativo(pasta, registro)
        self.figura_exibida = registro.copy()
        self.escopo_exibido = escopo
        if self.canvas_mapa:
            self.canvas_mapa.draw()
            self.imagens_carregadas["mapa"] = Image.fromarray(np.asarray(self.canvas_mapa.buffer_rgba()).copy())
        self.botao_ampliar.configure(state="normal" if self.imagens_carregadas else "disabled")
        self.ajustar_figuras()

    def alternar_mascara(self):
        self.figura_exibida = None
        self.imagens_carregadas.clear()
        self.ultimo_pixel = None
        self.selecionar_linha()
        self.carregar_figuras()

    def escopo_visual(self, registro):
        categoria = registro["produto"] == "mascara_pastagem"
        mascara = self.mascaras.get(registro["data"]) if categoria or self.aplicar_mascara.get() else None
        vigor = registro.get("vigor") if self.aplicar_mascara.get() and self.vigor.get() != "Todos" and not categoria else None
        return mascara, vigor

    def abrir_tabela(self):
        pai = self.winfo_toplevel()
        largura = max(640, min(1100, pai.winfo_width() - 40))
        altura = max(420, min(680, pai.winfo_height() - 40))
        x = max(0, pai.winfo_rootx() + (pai.winfo_width() - largura) // 2)
        y = max(0, pai.winfo_rooty() + (pai.winfo_height() - altura) // 2)
        self.janela_tabela.geometry(f"{largura}x{altura}+{x}+{y}")
        self.janela_tabela.deiconify()
        self.janela_tabela.lift()
        self.janela_tabela.grab_set()

    def fechar_tabela(self):
        aberta = self.janela_tabela.state() != "withdrawn"
        self.janela_tabela.grab_release()
        self.janela_tabela.withdraw()
        if aberta and self.visivel:
            self.sincronizar_selecao()
            self.filtrar()

    def ver_todos(self):
        self.limpar_filtros()
        self.abrir_tabela()

    def ver_linha(self):
        self.selecionar_linha()
        self.fechar_tabela()
        self.sincronizar_selecao()
        self.carregar_figuras()

    def sincronizar_selecao(self):
        registro = self.registro_figura
        if registro:
            self.data.set(formatar_data(registro["data"]))
            self.produto.set(rotulo_produto(registro["produto"]))
            self.vigor.set(ROTULOS_VIGOR.get(registro.get("vigor"), "Todos"))

    def limpar_canvas(self):
        self.botao_dados_pixel.configure(state="disabled")
        if self.canvas_mapa:
            self.cancelar_desenho(self.canvas_mapa)
            self.canvas_mapa.get_tk_widget().destroy()
            self.canvas_mapa.figure.clear()
            self.canvas_mapa = None
        if self.canvas_histograma:
            self.cancelar_desenho(self.canvas_histograma)
            self.canvas_histograma.get_tk_widget().destroy()
            self.canvas_histograma.figure.clear()
            self.canvas_histograma = None
        self.eixo_mapa = None
        self.marcador_pixel = None
        self.imagem_mapa.grid()
        self.imagem_histograma.grid()

    @staticmethod
    def cancelar_desenho(canvas):
        # Desenhos agendados não podem sobreviver à troca de produto.
        for nome in ("_idle_draw_id", "_event_loop_id"):
            timer = getattr(canvas, nome, None)
            if timer:
                canvas.get_tk_widget().after_cancel(timer)
                setattr(canvas, nome, None)

    def mostrar_histograma_interativo(self, pasta, registro):
        caminho = pasta / f"{registro['produto']}_histograma.json"
        base = self.pastas[self.analise.get()] / registro["data"]
        mascara, vigor = self.escopo_visual(registro)
        nativo = caminho_produto(base, registro["produto"], mascara).is_file()
        if not caminho.exists() and not nativo:
            return
        try:
            categoria = registro["produto"] == "mascara_pastagem"
            usar_salvo = caminho.exists() and not categoria and (
                not nativo or (vigor and vigor == registro.get("vigor"))
                or (not mascara and not vigor and not registro.get("vigor")))
            dados = (histograma_produto(base, registro["produto"], PRODUTOS_VISUAIS[registro["produto"]][1],
                                       vigor=vigor, caminho_mascara=mascara) if not usar_salvo
                     else json.loads(caminho.read_text(encoding="utf-8")))
            figura = Figure(figsize=(4, 4), dpi=100, layout="constrained")
            eixo = figura.add_subplot(111)
            if categoria:
                eixo.bar([1, 2, 3], dados["frequencias"][1:4], color=CORES_MASCARA[1:4])
                eixo.set_xticks([1, 2, 3], ["Baixo", "Médio", "Alto"])
                eixo.text(0.02, 0.98, f"Sem vigor classificado: {dados['frequencias'][4]:,}".replace(",", "."),
                          transform=eixo.transAxes, va="top", fontsize=9)
            else:
                eixo.stairs(dados["frequencias"], dados["bordas"], fill=True, color="#497eab", alpha=0.8)
            for chave, cor, estilo, titulo in (("media", "#b22222", "--", "Média"),
                                             ("mediana", "#293847", ":", "Mediana")):
                valor = None if categoria else numero(registro.get(chave) if usar_salvo else dados.get(chave))
                if valor is not None:
                    eixo.axvline(valor, color=cor, linestyle=estilo,
                                 label=f"{titulo}: {formatar_numero(valor)}")
            q1, q3 = (numero(registro.get("q1")), numero(registro.get("q3"))) if usar_salvo else (None, None)
            if q1 is not None and q3 is not None:
                eixo.axvspan(q1, q3, alpha=0.15, color="#ef9b20")
            if eixo.get_legend_handles_labels()[0]:
                eixo.legend(fontsize=9)
            eixo.set(title="Pastagens por vigor" if categoria else "Distribuição dos pixels exibidos",
                     xlabel="" if categoria else PRODUTOS_VISUAIS[registro["produto"]][3],
                     ylabel="Número de pixels", xlim=(0.5, 3.5) if categoria else (dados["bordas"][0], dados["bordas"][-1]))
            eixo.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
            eixo.grid(axis="y", alpha=0.2)
            self.imagem_histograma.grid_remove()
            self.canvas_histograma = FigureCanvasTkAgg(figura, master=self.painel_histograma)
            self.canvas_histograma.get_tk_widget().grid(row=0, column=0, sticky="nsew")
            self.canvas_histograma.draw_idle()
        except (OSError, ValueError, KeyError):
            return  # A figura PNG continua disponível em execuções incompletas.

    def mostrar_mapa_interativo(self, registro):
        self.limpar_canvas()
        self.ultimo_pixel = None
        pasta = self.pastas[self.analise.get()] / registro["data"]
        mascara, vigor = self.escopo_visual(registro)
        caminho = caminho_produto(pasta, registro["produto"], mascara)
        if not caminho.exists():
            self.consulta_pixel.set("Execução antiga: reprocesse para habilitar a consulta dos pixels. As figuras salvas estão disponíveis.")
            return
        try:
            dados, limites, crs = ler_previa(pasta, registro["produto"], vigor, caminho_mascara=mascara)
        except (OSError, ValueError) as erro:
            self.consulta_pixel.set(f"Não foi possível abrir os pixels salvos: {erro}")
            return
        _, escala, cores, unidade = PRODUTOS_VISUAIS[registro["produto"]]
        if registro["produto"] != "mascara_pastagem":
            escala = intervalo_dados(dados, escala)
            escala = ampliar_intervalo(
                escala, numero(registro.get("minimo")), numero(registro.get("maximo"))
            )
        figura = Figure(figsize=(6, 5), dpi=100, layout="constrained")
        eixo = figura.add_subplot(111)
        eixo.set_facecolor("#e6e8ea")
        categoria = registro["produto"] == "mascara_pastagem"
        from matplotlib.colors import ListedColormap, BoundaryNorm
        from matplotlib.patches import Patch
        mapa_cores = (ListedColormap(CORES_MASCARA).with_extremes(bad="#ffffff") if categoria
                      else colormaps[cores].with_extremes(bad="#e6e8ea"))
        parametros = {"norm": BoundaryNorm(np.arange(-0.5, 5.5), 5)} if categoria else {"vmin": escala[0], "vmax": escala[1]}
        imagem = eixo.imshow(dados, extent=(limites.left, limites.right, limites.bottom, limites.top),
                            cmap=mapa_cores,
                            **parametros, interpolation="nearest")
        eixo.set_title(rotulo_produto(registro["produto"]), fontsize=11)
        eixo.set_axis_off()
        if categoria:
            eixo.legend(handles=[Patch(color=CORES_MASCARA[i], label=CLASSES_MASCARA[i]) for i in (1, 2, 3, 0, 4)],
                        loc="upper center", bbox_to_anchor=(0.5, 0), ncol=2, fontsize=8)
        else:
            figura.colorbar(imagem, ax=eixo, shrink=0.8, pad=0.025, label=unidade)
        self.imagem_mapa.grid_remove()
        self.eixo_mapa = eixo
        self.canvas_mapa = FigureCanvasTkAgg(figura, master=self.painel_mapa)
        self.canvas_mapa.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.canvas_mapa.mpl_connect("button_press_event", self.clicar_pixel)
        self.canvas_mapa.draw_idle()
        escopo = "Vigor: 1 = baixo · 2 = médio · 3 = alto. Cinza indica área fora das pastagens ou sem vigor classificado." if categoria else (
            "Pastagens com vigor classificado" + (f" · vigor {vigor}" if vigor else " · baixo, moderado e alto") if mascara or vigor else "Área completa")
        self.consulta_pixel.set(f"{escopo} · Clique no mapa para consultar o pixel processado.")

    def clicar_pixel(self, evento):
        if evento.inaxes is not self.eixo_mapa or evento.xdata is None or evento.ydata is None:
            return
        registro = self.registro_figura
        pasta = self.pastas[self.analise.get()] / registro["data"]
        mascara, vigor = self.escopo_visual(registro)
        try:
            pixel = consultar_pixel(pasta, registro["produto"], evento.xdata, evento.ydata, vigor, caminho_mascara=mascara)
        except (OSError, ValueError) as erro:
            self.ultimo_pixel = None
            self.botao_dados_pixel.configure(state="disabled")
            self.consulta_pixel.set(f"Não foi possível consultar o pixel: {erro}")
            return
        self.ultimo_pixel = pixel
        self.botao_dados_pixel.configure(state="normal" if pixel else "disabled")
        if self.marcador_pixel:
            self.marcador_pixel.remove()
            self.marcador_pixel = None
        if pixel is None:
            self.consulta_pixel.set("Pixel fora da área ou da classe de vigor selecionada.")
        else:
            valor = pixel["valores"].get(registro["produto"])
            unidade = PRODUTOS_VISUAIS[registro["produto"]][3]
            self.consulta_pixel.set(
                f"{rotulo_produto(registro['produto'])}: "
                + (CLASSES_MASCARA.get(valor, "Sem dado") if registro['produto'] == 'mascara_pastagem' else f"{formatar_numero(valor, 6)} {unidade}")
                + f" · linha {pixel['linha'] + 1}, coluna {pixel['coluna'] + 1}"
                + (" · sem dado válido neste pixel" if valor is None else ""))
            self.marcador_pixel, = self.eixo_mapa.plot(*pixel["centro"], marker="+", color="#008aff", markersize=15, markeredgewidth=2)
        self.canvas_mapa.draw_idle()

    def abrir_dados_pixel(self):
        if not self.ultimo_pixel:
            return
        pixel = self.ultimo_pixel
        janela = ctk.CTkToplevel(self)
        janela.title("Valores do pixel processado")
        janela.geometry("560x520")
        janela.transient(self.winfo_toplevel())
        janela.grab_set()
        texto = ctk.CTkTextbox(janela, wrap="word")
        texto.pack(fill="both", expand=True, padx=12, pady=12)
        x, y = pixel["centro"]
        linhas = [self.titulo_selecao.get().replace("\n", " · "),
                  f"Linha {pixel['linha'] + 1} · coluna {pixel['coluna'] + 1}",
                  f"Centro: {x:.3f}, {y:.3f} · {pixel['crs']}", ""]
        for produto, valor in pixel["valores"].items():
            texto = CLASSES_MASCARA.get(valor, "Sem dado") if produto == "mascara_pastagem" else f"{formatar_numero(valor, 6)} {PRODUTOS_VISUAIS.get(produto, ('', '', '', ''))[3]}"
            linhas.append(f"{rotulo_produto(produto)}: {texto}")
        texto.insert("1.0", "\n".join(linhas))
        texto.configure(state="disabled")
        ctk.CTkButton(janela, text="Fechar", command=janela.destroy).pack(pady=(0, 12))

    def ampliar_figura(self):
        tipo = "mapa"
        origem = self.imagens_carregadas.get(tipo)
        if origem is None:
            return
        if self.janela_figura is not None and self.janela_figura.winfo_exists():
            self.janela_figura.destroy()
        janela = ctk.CTkToplevel(self)
        self.janela_figura = janela
        janela.title(f"{tipo.capitalize()} — {self.titulo_selecao.get().replace(chr(10), ' · ')}")
        pai = self.winfo_toplevel()
        janela.geometry(f"{max(480, min(960, pai.winfo_width() - 40))}x{max(360, min(760, pai.winfo_height() - 40))}")
        janela.minsize(480, 360)
        janela.transient(self.winfo_toplevel())
        janela.grid_columnconfigure(0, weight=1)
        janela.grid_rowconfigure(0, weight=1)
        imagem = origem.copy()
        imagem.thumbnail((900, 690), Image.Resampling.LANCZOS)
        rotulo = ctk.CTkLabel(janela, text="", image=ctk.CTkImage(light_image=imagem, size=imagem.size))
        rotulo.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        ultima = [None]

        def redimensionar(evento):
            if evento.widget != janela:
                return
            tamanho = (max(64, evento.width - 24), max(64, evento.height - 24))
            if tamanho == ultima[0]:
                return
            ultima[0] = tamanho
            copia = origem.copy()
            copia.thumbnail(tamanho, Image.Resampling.LANCZOS)
            escala = janela._get_widget_scaling()
            dimensoes = (max(1, int(copia.width / escala)), max(1, int(copia.height / escala)))
            rotulo.configure(image=ctk.CTkImage(light_image=copia, size=dimensoes))

        janela.bind("<Configure>", redimensionar, add="+")

    def agendar_redimensionamento(self, evento=None):
        if self.timer_figuras:
            self.after_cancel(self.timer_figuras)
        self.timer_figuras = self.after(120, self.ajustar_figuras)

    def ajustar_figuras(self):
        if self.timer_figuras:
            self.after_cancel(self.timer_figuras)
        self.timer_figuras = None
        for sufixo, widget in (("mapa", self.imagem_mapa), ("histograma", self.imagem_histograma)):
            origem = self.imagens_carregadas.get(sufixo)
            if origem is None:
                continue
            imagem = origem.copy()
            escala = self._get_widget_scaling()
            largura = max(32, int(widget.master.winfo_width() - 16 * escala))
            altura = max(32, int(widget.master.winfo_height() - 16 * escala))
            imagem.thumbnail((largura, altura), Image.Resampling.LANCZOS)
            tamanho = (max(1, int(imagem.width / escala)), max(1, int(imagem.height / escala)))
            widget.configure(image=ctk.CTkImage(light_image=imagem, size=tamanho), text="")

    def definir_visibilidade(self, visivel):
        self.visivel = visivel
        if not visivel:
            self.limpar_animacao()
            self.fechar_tabela()
        else:
            self.mudar_aba()
            if self.abas.get() == "Visualização":
                self.sincronizar_selecao()
                self.filtrar()
                self.carregar_figuras()

    def mudar_aba(self):
        self.limpar_animacao()
        if self.visivel and self.abas.get() == "Visualização":
            self.carregar_figuras()

    def limpar_animacao(self):
        self.parar()
        if self.animacao:
            self.animacao.close()
            self.animacao = None
        self.imagem_temporal.configure(
            image=self.imagem_vazia,
            text="Escolha o produto e clique em Reproduzir para carregar a animação.",
        )

    def abrir_animacao(self, valor=None):
        self.limpar_animacao()
        if not self.visivel or self.abas.get() != "Time lapse":
            return
        pasta = self.pastas.get(self.analise.get())
        produto = self.produto_temporal.get()
        produto = next((p for p in PRODUTOS if rotulo_produto(p) == produto), produto)
        if produto == "RGB":
            produto = "rgb"
        caminho = (
            pasta / "timelapse" / f"timelapse_{produto}.gif"
            if pasta
            else None
        )
        self.quadro = 0
        if caminho and caminho.exists():
            self.animacao = Image.open(caminho)
            self.exibir_quadro()
        else:
            self.imagem_temporal.configure(
                image=self.imagem_vazia,
                text="Esta análise não possui time lapse salvo.",
            )

    def exibir_quadro(self):
        self.animacao.seek(self.quadro)
        imagem = self.animacao.convert("RGB")
        imagem.thumbnail((650, 470))
        self.imagem_temporal.configure(
            image=ctk.CTkImage(light_image=imagem, size=imagem.size), text=""
        )

    def reproduzir(self):
        if self.timer:
            self.parar()
            return
        if self.animacao is None:
            self.abrir_animacao()
        if self.animacao:
            self.botao_play.configure(text="Pausar")
            self.avancar()

    def avancar(self):
        self.quadro = (self.quadro + 1) % self.animacao.n_frames
        self.exibir_quadro()
        self.timer = self.after(1500, self.avancar)

    def parar(self):
        if self.timer:
            self.after_cancel(self.timer)
            self.timer = None
        self.botao_play.configure(text="Reproduzir")

    def destroy(self):
        self.parar()
        self.limpar_canvas()
        self.janela_tabela.destroy()
        if self.janela_figura is not None and self.janela_figura.winfo_exists():
            self.janela_figura.destroy()
        if self.timer_figuras:
            self.after_cancel(self.timer_figuras)
        if self.animacao:
            self.animacao.close()
        super().destroy()
