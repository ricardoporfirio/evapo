"""Explora tabelas, figuras e animações salvas dentro do aplicativo."""

import csv
import math
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import customtkinter as ctk
from PIL import Image


class PainelResultados(ctk.CTkFrame):
    def __init__(self, pai):
        super().__init__(pai, fg_color="white", corner_radius=12)
        self.pastas = {}
        self.registros = []
        self.filtrados = []
        self.animacao = None
        self.timer = None
        self.quadro = 0
        self.registro_figura = None
        self.figura_exibida = None
        self.visivel = False
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
        controles = ctk.CTkFrame(self, fg_color="transparent")
        controles.pack(fill="x", padx=10, pady=10)
        self.escolha_analise = ctk.CTkOptionMenu(
            controles,
            variable=self.analise,
            values=["Sem resultados"],
            command=self.carregar,
        )
        self.escolha_analise.pack(side="left", padx=4)
        self.escolha_data = ctk.CTkOptionMenu(
            controles,
            variable=self.data,
            values=["Todas"],
            command=self.filtrar,
            width=135,
        )
        self.escolha_data.pack(side="left", padx=4)
        self.escolha_produto = ctk.CTkOptionMenu(
            controles,
            variable=self.produto,
            values=["Todos"],
            command=self.filtrar,
            width=135,
        )
        self.escolha_produto.pack(side="left", padx=4)
        self.escolha_vigor = ctk.CTkOptionMenu(
            controles,
            variable=self.vigor,
            values=["Todos"],
            command=self.filtrar,
            width=110,
        )
        self.escolha_vigor.pack(side="left", padx=4)
        ctk.CTkLabel(self, textvariable=self.resumo, anchor="w", wraplength=650,
                     text_color="#203744").pack(
            fill="x", padx=16, pady=5
        )
        self.abas = ctk.CTkTabview(self, fg_color="white", command=self.mudar_aba)
        self.abas.pack(fill="both", expand=True, padx=8, pady=8)
        tabela = self.abas.add("Estatísticas")
        temporal = self.abas.add("Time lapse")
        colunas = (
            "data",
            "vigor",
            "produto",
            "pixels_validos",
            "cobertura_percentual",
            "media",
            "mediana",
            "desvio_padrao",
            "minimo",
            "maximo",
        )
        tabela.grid_columnconfigure(0, weight=1, uniform="consulta")
        tabela.grid_columnconfigure(2, weight=1, uniform="consulta")
        tabela.grid_rowconfigure(0, weight=1)
        estilo = ttk.Style()
        estilo.configure("Evapo.Treeview", rowheight=30, font=("Segoe UI", 11))
        estilo.configure("Evapo.Treeview.Heading", font=("Segoe UI", 11, "bold"))
        self.tabela = ttk.Treeview(
            tabela, columns=colunas, show="headings", style="Evapo.Treeview"
        )
        nomes = (
            "Data",
            "Vigor",
            "Produto",
            "Pixels válidos",
            "Cobertura %",
            "Média",
            "Mediana",
            "Desvio padrão",
            "Mínimo",
            "Máximo",
        )
        for chave, nome in zip(colunas, nomes):
            self.tabela.heading(chave, text=nome)
            self.tabela.column(
                chave,
                width=115 if chave == "produto" else 100,
                minwidth=85,
                stretch=False,
            )
        self.tabela.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(tabela, orient="vertical", command=self.tabela.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(
            tabela, orient="horizontal", command=self.tabela.xview
        )
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tabela.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        self.tabela.bind("<<TreeviewSelect>>", self.selecionar_linha)
        ctk.CTkLabel(
            tabela,
            text="Selecione uma linha. Abra suas figuras ao lado quando precisar.",
            wraplength=280, text_color="#203744",
        ).grid(row=2, column=0, sticky="w", pady=8)
        self.detalhes = ctk.CTkTextbox(
            tabela, height=125, state="disabled", wrap="word"
        )
        self.detalhes.grid(row=3, column=0, columnspan=2, sticky="ew")
        ctk.CTkButton(
            tabela,
            text="Carregar mapa e histograma →",
            command=self.carregar_figuras,
        ).grid(row=4, column=0, sticky="w", pady=8)
        self.figuras = ctk.CTkScrollableFrame(tabela, fg_color="white", width=320)
        self.figuras.grid(row=0, column=2, rowspan=5, sticky="nsew", padx=(12, 0))
        self.imagem_mapa = ctk.CTkLabel(
            self.figuras,
            text="Selecione uma linha e clique em\nCarregar mapa e histograma.",
            text_color="#203744",
        )
        self.imagem_mapa.pack(fill="x")
        self.imagem_histograma = ctk.CTkLabel(self.figuras, text="", text_color="#203744")
        self.imagem_histograma.pack(fill="x", pady=8)
        ctk.CTkLabel(
            temporal, text="Animação dos produtos exportados, sem abrir o navegador.",
            text_color="#203744",
        ).pack(pady=8)
        self.produto_temporal = tk.StringVar(value="ndvi")
        ctk.CTkOptionMenu(
            temporal,
            variable=self.produto_temporal,
            values=["rgb", "ndvi", "savi", "iaf", "albedo_toa", "albedo_superficie"],
            command=self.abrir_animacao,
        ).pack(pady=6)
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
            self.registros = []
            self.filtrar()
            self.limpar_animacao()
            self.resumo.set(
                "Nenhum resultado salvo nesta pasta. Use Processar imagens marcadas."
            )

    def carregar(self, valor=None):
        self.limpar_animacao()
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
        self.data.set("Todas")
        self.produto.set("Todos")
        self.vigor.set("Todos")
        self.escolha_data.configure(
            values=["Todas", *sorted({r["data"] for r in self.registros})]
        )
        self.escolha_produto.configure(
            values=["Todos", *sorted({r["produto"] for r in self.registros})]
        )
        self.escolha_vigor.configure(
            values=[
                "Todos",
                *sorted({r["vigor"] for r in self.registros if "vigor" in r}),
            ]
        )
        self.filtrar()

    def filtrar(self, valor=None):
        self.registro_figura = None
        self.figura_exibida = None
        self.filtrados = [
            r
            for r in self.registros
            if (self.data.get() == "Todas" or r["data"] == self.data.get())
            and (self.produto.get() == "Todos" or r["produto"] == self.produto.get())
            and (self.vigor.get() == "Todos" or r.get("vigor") == self.vigor.get())
        ]
        self.tabela.delete(*self.tabela.get_children())
        for indice, registro in enumerate(self.filtrados):
            valores = []
            for chave in self.tabela["columns"]:
                valor = registro.get(chave, "—")
                if chave not in ("data", "vigor", "produto", "pixels_validos"):
                    numero = float(valor)
                    valor = f"{numero:.5f}" if math.isfinite(numero) else "Sem dados"
                valores.append(valor)
            self.tabela.insert("", "end", iid=str(indice), values=valores)
        self.resumo.set(
            f"{self.analise.get()} · {len(self.filtrados)} blocos estatísticos · resultados salvos da última execução dessa análise."
        )
        if self.filtrados:
            self.tabela.selection_set("0")
            self.selecionar_linha()
        else:
            self.registro_figura = None
            self.figura_exibida = None
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
        self.detalhes.configure(state="normal")
        self.detalhes.delete("1.0", "end")
        self.detalhes.insert(
            "end",
            "\n".join(
                f"{chave.replace('_', ' ')}: {valor}"
                for chave, valor in registro.items()
            ),
        )
        self.detalhes.configure(state="disabled")
        if registro != self.registro_figura:
            self.registro_figura = registro
            self.figura_exibida = None
            self.imagem_mapa.configure(
                image=self.imagem_vazia,
                text="Clique em Carregar mapa e histograma\npara visualizar esta linha.",
            )
            self.imagem_histograma.configure(image=self.imagem_vazia, text="")

    def carregar_figuras(self):
        registro = self.registro_figura
        if registro is None or self.figura_exibida == registro:
            return
        pasta = self.pastas[self.analise.get()] / registro["data"]
        if registro.get("vigor"):
            pasta /= registro["vigor"]
        for widget, sufixo in (
            (self.imagem_mapa, "mapa"),
            (self.imagem_histograma, "histograma"),
        ):
            caminho = pasta / f"{registro['produto']}_{sufixo}.png"
            if caminho.exists():
                with Image.open(caminho) as origem:
                    imagem = origem.copy()
                imagem.thumbnail((max(160, self.figuras.winfo_width() - 30), 530))
                widget.configure(
                    image=ctk.CTkImage(light_image=imagem, size=imagem.size), text=""
                )
            else:
                widget.configure(
                    image=self.imagem_vazia, text="Figura não disponível nesta análise."
                )
        self.figura_exibida = registro.copy()

    def definir_visibilidade(self, visivel):
        self.visivel = visivel
        if not visivel:
            self.limpar_animacao()
        else:
            self.mudar_aba()

    def mudar_aba(self):
        self.limpar_animacao()

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
        caminho = (
            pasta / "timelapse" / f"timelapse_{self.produto_temporal.get()}.gif"
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
        if self.animacao:
            self.animacao.close()
        super().destroy()
