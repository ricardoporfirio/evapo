"""Organiza a janela CustomTkinter em mapa, configuração e consulta de pixel."""

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from evapo.interface.resultados import PainelResultados

FUNDO = "#edf2f6"
AZUL = "#1e5b78"
TEXTO = "#203744"


def titulo(pai, texto):
    ctk.CTkLabel(pai, text=texto, font=("Segoe UI", 15, "bold"), text_color=TEXTO).pack(
        anchor="w", padx=14, pady=(14, 6)
    )


def botao(pai, texto, comando, destaque=False, **opcoes):
    return ctk.CTkButton(
        pai,
        text=texto,
        command=comando,
        height=34,
        fg_color=AZUL if destaque else "#e5edf3",
        hover_color="#cbdde7" if not destaque else "#17485f",
        text_color="white" if destaque else TEXTO,
        corner_radius=8,
        **opcoes,
    )


def montar_interface(app, escalas):
    janela = app.janela
    janela.configure(fg_color=FUNDO)
    janela.grid_columnconfigure(1, weight=1)
    janela.grid_rowconfigure(1, weight=1)
    cabecalho = ctk.CTkFrame(janela, fg_color=AZUL, corner_radius=0, height=66)
    cabecalho.grid(row=0, column=0, columnspan=2, sticky="ew")
    ctk.CTkLabel(
        cabecalho, text="EVAPO", font=("Segoe UI", 24, "bold"), text_color="white"
    ).pack(side="left", padx=22, pady=16)
    ctk.CTkLabel(
        cabecalho,
        text="Landsat",
        text_color="#d3e3eb",
        font=("Segoe UI", 14),
    ).pack(side="left", padx=10)
    botao(cabecalho, "Ver resultados", app.abrir_relatorio, width=110).pack(
        side="right", padx=8
    )

    def exportar(opcao):
        {
            "Relatório interpretativo PDF": app.exportar_relatorio_pdf_projeto,
            "Vista atual em PNG": app.exportar_vista_png,
            "Todas as imagens PNG": app.exportar_pngs,
            "Relatório completo ZIP": app.exportar_relatorio_projeto,
        }[opcao]()
        menu_exportar.set("Exportar…")

    menu_exportar = ctk.CTkOptionMenu(
        cabecalho,
        values=[
            "Relatório interpretativo PDF",
            "Relatório completo ZIP",
            "Vista atual em PNG",
            "Todas as imagens PNG",
        ],
        command=exportar,
        width=160,
    )
    menu_exportar.set("Exportar…")
    menu_exportar.pack(side="right", padx=6)
    app.botao_redo = botao(cabecalho, "Refazer", app.refazer, width=75)
    app.botao_redo.pack(side="right", padx=4)
    app.botao_undo = botao(cabecalho, "Desfazer", app.desfazer, width=75)
    app.botao_undo.pack(side="right", padx=4)
    botao(cabecalho, "Salvar", app.salvar_projeto, width=75).pack(side="right", padx=4)

    def projeto(opcao):
        {
            "Novo projeto": app.novo_projeto,
            "Abrir projeto": app.abrir_projeto,
            "Recuperar última sessão": app.recuperar_ultima_sessao,
            "Salvar projeto": app.salvar_projeto,
            "Salvar projeto como…": lambda: app.salvar_projeto(como=True),
        }[opcao]()
        menu_projeto.set("Projeto…")

    menu_projeto = ctk.CTkOptionMenu(
        cabecalho,
        values=[
            "Novo projeto",
            "Abrir projeto",
            "Recuperar última sessão",
            "Salvar projeto",
            "Salvar projeto como…",
        ],
        command=projeto,
        width=130,
    )
    menu_projeto.set("Projeto…")
    menu_projeto.pack(side="right", padx=6)

    lateral = ctk.CTkFrame(janela, width=290, fg_color="white", corner_radius=12)
    app.lateral = lateral
    lateral.grid(row=1, column=0, sticky="nsew", padx=(14, 8), pady=12)
    lateral.grid_propagate(False)
    configuracao = ctk.CTkScrollableFrame(lateral, fg_color="white", width=260)
    configuracao.pack(fill="both", expand=True, padx=6, pady=6)
    imagens = ctk.CTkFrame(configuracao, fg_color="transparent")
    area = ctk.CTkFrame(configuracao, fg_color="transparent")
    analise = ctk.CTkFrame(configuracao, fg_color="transparent")
    for secao in (imagens, area, analise):
        secao.pack(fill="x", pady=(0, 8))
    titulo(imagens, "Suas imagens")
    botao(imagens, "Abrir pasta de imagens…", app.abrir_entrada).pack(
        fill="x", padx=12, pady=6
    )
    ctk.CTkLabel(
        imagens,
        text="Marque as datas para processar.\nClique na data para exibir no mapa.",
        justify="left",
        text_color="#607583",
        font=("Segoe UI", 12),
    ).pack(anchor="w", padx=14, pady=8)
    app.lista_datas = ctk.CTkScrollableFrame(
        imagens, fg_color="transparent", label_text="Datas disponíveis", height=170
    )
    app.lista_datas.pack(fill="both", expand=True, padx=4, pady=6)
    titulo(area, "Área de interesse")
    ctk.CTkLabel(
        area, textvariable=app.area, text_color=AZUL, font=("Segoe UI", 13, "bold")
    ).pack(anchor="w", padx=14, pady=6)
    botao(area, "Usar a imagem inteira", app.imagem_inteira).pack(
        fill="x", padx=12, pady=4
    )
    botao(area, "Abrir ROI salva…", app.abrir_roi).pack(fill="x", padx=12, pady=4)
    titulo(area, "Desenhar no mapa")
    for nome in ("Retângulo", "Círculo", "Polígono"):
        ctk.CTkRadioButton(
            area,
            text=nome,
            variable=app.ferramenta,
            value=nome,
            command=app.mudar_ferramenta,
            fg_color=AZUL,
        ).pack(anchor="w", padx=16, pady=8)
    ctk.CTkLabel(
        area,
        text="Arraste para retângulo ou círculo.\nNo polígono, clique nos vértices e\nno primeiro ponto para fechar.",
        justify="left",
        text_color="#607583",
        font=("Segoe UI", 12),
    ).pack(anchor="w", padx=14, pady=16)
    titulo(analise, "Configurar análise")
    botao(analise, "Pasta de resultados…", app.abrir_saida).pack(
        fill="x", padx=12, pady=5
    )
    botao(analise, "Modelo de elevação…", app.abrir_mde).pack(fill="x", padx=12, pady=5)
    ctk.CTkLabel(analise, text="Temperatura do ar (°C)", text_color="#607583").pack(
        anchor="w", padx=14, pady=(8, 0)
    )
    ctk.CTkEntry(analise, textvariable=app.temperatura_ar).pack(fill="x", padx=12, pady=4)
    ctk.CTkLabel(
        analise, text="Opcional; aplicada a todas as datas.\nNecessária para onda longa incidente\ne saldo de radiação.",
        justify="left", text_color="#607583", font=("Segoe UI", 12),
    ).pack(anchor="w", padx=14)
    ctk.CTkLabel(analise, text="L do SAVI (0 a 1)", text_color="#607583").pack(
        anchor="w", padx=14, pady=(8, 0)
    )
    ctk.CTkEntry(analise, textvariable=app.l_savi).pack(fill="x", padx=12, pady=4)
    ctk.CTkLabel(
        analise, text="Padrão: 0,5. O IAF usa a calibração\nSEBAL com L=0,1.",
        justify="left", text_color="#607583", font=("Segoe UI", 12),
    ).pack(anchor="w", padx=14)
    app.opcao_pastagens = ctk.CTkCheckBox(
        analise, text="Analisar pastagens", variable=app.pastagens, fg_color=AZUL
    )
    app.opcao_pastagens.pack(anchor="w", padx=14, pady=(18, 8))
    ctk.CTkLabel(
        analise, text="MapBiomas • ano de referência", text_color="#607583"
    ).pack(anchor="w", padx=14)
    app.ano_pastagens = ctk.CTkOptionMenu(
        analise,
        variable=app.ano,
        values=[str(a) for a in range(2000, 2026)],
        fg_color=AZUL,
        button_color=AZUL,
        state="disabled",
    )
    app.ano_pastagens.pack(fill="x", padx=12, pady=8)
    ctk.CTkLabel(
        analise,
        textvariable=app.resumo_analise,
        justify="left",
        anchor="w",
        wraplength=235,
    ).pack(fill="x", padx=14, pady=8)
    acoes = ctk.CTkFrame(lateral, fg_color="white")
    acoes.pack(fill="x", padx=6, pady=(0, 8))
    app.progresso = ctk.CTkProgressBar(acoes, mode="indeterminate")
    app.progresso.pack(fill="x", padx=12, pady=4)
    app.progresso.set(0)
    ctk.CTkLabel(
        acoes, textvariable=app.estado_processamento, wraplength=235, text_color=TEXTO
    ).pack(
        fill="x", padx=12
    )
    app.botao_processar = botao(
        acoes, "Processar imagens marcadas", app.processar, destaque=True
    )
    app.botao_processar.pack(fill="x", padx=12, pady=(8, 8))
    botao(analise, "Ver resultados salvos", app.abrir_relatorio).pack(
        fill="x", padx=12, pady=4
    )
    botao(analise, "Pasta de exportações", app.abrir_resultados).pack(
        fill="x", padx=12, pady=4
    )

    app.paginas = ctk.CTkTabview(
        janela, fg_color="transparent", segmented_button_selected_color=AZUL,
        command=app.mudar_pagina,
    )
    app.paginas.grid(row=1, column=1, sticky="nsew", padx=(4, 14), pady=12)
    principal = app.paginas.add("Mapa")
    resultados = app.paginas.add("Resultados")
    historico = ctk.CTkFrame(resultados, fg_color="white")
    historico.pack(fill="x", pady=(0, 6))
    execucoes = ctk.CTkFrame(historico, fg_color="transparent")
    execucoes.pack(fill="x")
    ctk.CTkLabel(execucoes, text="Execução salva:", text_color=TEXTO).pack(side="left", padx=10)
    app.lista_execucoes = ctk.CTkOptionMenu(
        execucoes,
        variable=app.execucao_selecionada,
        values=["Sem execuções"],
        command=app.escolher_execucao,
        width=310,
    )
    app.lista_execucoes.pack(side="left", padx=8, pady=8)
    botao(execucoes, "Restaurar recorte", app.restaurar_execucao, width=120).pack(
        side="left", padx=4
    )
    def exportar_resultado(opcao):
        {
            "Relatório PDF": app.exportar_relatorio_pdf_projeto,
            "Relatório completo ZIP": app.exportar_relatorio_projeto,
            "Imagens PNG": app.exportar_pngs,
        }[opcao]()
        exportacoes.set("Exportar resultado…")

    exportacoes = ctk.CTkOptionMenu(
        execucoes, values=["Relatório PDF", "Relatório completo ZIP", "Imagens PNG"],
        command=exportar_resultado, fg_color=AZUL, button_color=AZUL, width=170,
    )
    exportacoes.set("Exportar resultado…")
    exportacoes.pack(side="right", padx=8)
    app.painel_resultados = PainelResultados(resultados)
    app.painel_resultados.pack(fill="both", expand=True)
    notas = app.paginas.add("Notas")
    ctk.CTkLabel(
        notas,
        text="Notas do projeto · salvas no projeto e na recuperação automática",
        anchor="w",
    ).pack(fill="x", padx=12, pady=8)
    botao(notas, "Nova nota com referência à imagem / pixel", app.nova_nota).pack(
        anchor="w", padx=12, pady=8
    )
    app.notas = ctk.CTkTextbox(notas, wrap="word", font=("Segoe UI", 14))
    app.notas.pack(fill="both", expand=True, padx=12, pady=12)
    app.notas.bind("<KeyRelease>", app.editar_notas)
    app.notas.bind("<Control-z>", lambda evento: (app.desfazer(), "break")[1])
    app.notas.bind("<Control-y>", lambda evento: (app.refazer(), "break")[1])
    app.notas.bind("<FocusOut>", lambda evento: app.registrar_alteracao())
    principal.grid_columnconfigure(0, weight=1)
    principal.grid_rowconfigure(2, weight=1)
    controles = ctk.CTkFrame(principal, fg_color="white", corner_radius=10)
    controles.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    botao(controles, "‹", lambda: app.trocar_data(-1), width=35).pack(
        side="left", padx=(10, 4), pady=10
    )
    app.data_visivel = ctk.CTkLabel(
        controles, text="Sem imagens abertas", font=("Segoe UI", 14, "bold"), text_color=TEXTO
    )
    app.data_visivel.pack(side="left", padx=8)
    botao(controles, "›", lambda: app.trocar_data(1), width=35).pack(
        side="left", padx=4
    )
    ctk.CTkOptionMenu(
        controles,
        variable=app.produto,
        values=["RGB", *escalas],
        width=180,
        fg_color=AZUL,
        button_color=AZUL,
        command=lambda valor: app.atualizar_vista(),
    ).pack(side="right", padx=12)
    ferramentas = ctk.CTkFrame(principal, fg_color="transparent")
    ferramentas.grid(row=1, column=0, sticky="ew", pady=(0, 8))
    ctk.CTkSegmentedButton(
        ferramentas,
        values=["Consultar", "Mover", "Retângulo", "Círculo", "Polígono"],
        variable=app.ferramenta,
        selected_color=AZUL,
        command=lambda valor: app.mudar_ferramenta(),
    ).pack(anchor="w", pady=(0, 6))
    navegacao = ctk.CTkFrame(ferramentas, fg_color="transparent")
    navegacao.pack(fill="x")
    for texto, comando in (
        ("+", lambda: app.navegacao.aplicar_zoom(True)),
        ("−", lambda: app.navegacao.aplicar_zoom(False)),
        ("Ver tudo", app.ver_tudo),
    ):
        botao(navegacao, texto, comando, width=65).pack(side="left", padx=4)
    botao(navegacao, "Ir ao máximo", lambda: app.ir_extremo(False), width=115).pack(
        side="right", padx=4
    )
    botao(navegacao, "Ir ao mínimo", lambda: app.ir_extremo(True), width=115).pack(
        side="right", padx=4
    )
    mapa = ctk.CTkFrame(principal, fg_color="white", corner_radius=12)
    mapa.grid(row=2, column=0, sticky="nsew")
    app.figura = Figure(figsize=(9, 7), facecolor="white")
    app.eixo = app.figura.add_axes([0.08, 0.12, 0.76, 0.80])
    app.eixo.set_title("Abra uma pasta de imagens para começar")
    app.eixo_cores = app.figura.add_axes([0.90, 0.18, 0.02, 0.64])
    app.eixo_cores.set_visible(False)
    app.canvas = FigureCanvasTkAgg(app.figura, master=mapa)
    app.canvas.get_tk_widget().configure(bg="white", highlightthickness=0)
    app.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

    rodape = ctk.CTkFrame(principal, fg_color="white", corner_radius=10)
    rodape.grid(row=3, column=0, sticky="ew", pady=(8, 0))
    rodape.grid_columnconfigure(0, weight=1)
    rodape.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(
        rodape, text="PIXEL ORIGINAL", font=("Segoe UI", 12, "bold"), text_color=AZUL
    ).grid(row=0, column=0, sticky="w", padx=14, pady=(8, 2))
    ctk.CTkLabel(
        rodape, text="PROCESSAMENTO", font=("Segoe UI", 12, "bold"), text_color=AZUL
    ).grid(row=0, column=1, sticky="w", padx=14, pady=(8, 2))
    app.info_pixel = ctk.CTkTextbox(
        rodape,
        height=122,
        fg_color="#f5f8fa",
        text_color=TEXTO,
        font=("Consolas", 12),
        wrap="word",
    )
    app.info_pixel.grid(row=1, column=0, sticky="ew", padx=(10, 5), pady=(0, 10))
    app.info_pixel.insert(
        "end", "Selecione Consultar e clique no mapa.\nRoda do mouse: zoom no cursor."
    )
    app.info_pixel.configure(state="disabled")
    app.log = ctk.CTkTextbox(
        rodape,
        height=122,
        fg_color="#f5f8fa",
        text_color=TEXTO,
        font=("Consolas", 11),
        wrap="word",
        state="disabled",
    )
    app.log.grid(row=1, column=1, sticky="ew", padx=(5, 10), pady=(0, 10))
    ctk.CTkLabel(
        janela, textvariable=app.status, text_color="#526b79", anchor="w"
    ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 8))
