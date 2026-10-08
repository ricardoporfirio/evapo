"""Ações da janela: projetos, recuperação, histórico, notas e exportações."""

from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from evapo.dados.area import usar_imagem_inteira
from evapo.relatorios.exportacoes import exportar_imagens, exportar_relatorio
from evapo.dados.projetos import Projeto, gravar_documento
from evapo.dados.selecao import identificar_cena


class AcoesProjeto:
    def preparar_projeto(self):
        self.aplicando_projeto = True
        self.alterado = False
        self.timer_notas = None
        self.imagens_projeto = None
        self.execucao_atual = None
        self.doc = Projeto(
            "Sem título",
            {
                "entrada": str(self.entrada) if self.entrada else None,
                "saida": str(self.saida),
                "mde": None,
                "temperatura_ar": "",
                "roi": None,
                "imagens": None,
                "pastagens": False,
                "ano": "2025",
                "produto": "NDVI",
                "notas": "",
            },
        )
        self.saida = self.projeto / "projetos" / self.doc.identificador / "resultados"
        self.doc.estado["saida"] = str(self.saida)

    def estado_atual(self):
        imagens = (
            [
                identificar_cena(cena)
                for cena, marcada in zip(self.cenas, self.marcadas)
                if marcada.get()
            ]
            if self.cenas
            else self.imagens_projeto
        )
        return {
            "entrada": str(self.entrada.resolve()) if self.entrada else None,
            "saida": str(self.saida.resolve()),
            "mde": self.mde,
            "temperatura_ar": self.temperatura_ar.get(),
            "roi": deepcopy(self.roi),
            "imagens": imagens,
            "pastagens": self.pastagens.get(),
            "ano": self.ano.get(),
            "produto": self.produto.get(),
            "notas": self.notas.get("1.0", "end-1c"),
            "data_visivel": identificar_cena(self.cenas[self.indice])
            if self.cenas
            else None,
            "vista": {"x": list(self.eixo.get_xlim()), "y": list(self.eixo.get_ylim())}
            if self.cenas
            else None,
        }

    def registrar_alteracao(self, *args):
        if self.aplicando_projeto:
            return
        if self.doc.editar(self.estado_atual()):
            self.alterado = True
            self.recuperar_automaticamente()
        self.atualizar_titulo()
        self.atualizar_resumo()

    def atualizar_titulo(self):
        self.janela.title(f"Evapo — {self.doc.nome}{' *' if self.alterado else ''}")
        self.botao_undo.configure(state="normal" if self.doc.desfazer else "disabled")
        self.botao_redo.configure(state="normal" if self.doc.refazer else "disabled")
        opcoes = [e["nome"] for e in self.doc.execucoes] or ["Sem execuções"]
        self.lista_execucoes.configure(values=opcoes)

    def recuperar_automaticamente(self):
        if not self.alterado and self.doc.arquivo is None:
            return
        try:
            caminho = (
                self.projeto
                / "projetos"
                / self.doc.identificador
                / "recuperacao.evapo.json"
            )
            gravar_documento(caminho, self.doc.documento())
            gravar_documento(
                self.projeto / "projetos" / "ultima_sessao.json",
                {"recuperacao": str(caminho.resolve())},
            )
        except OSError as erro:
            self.status.set(
                f"Não foi possível salvar a recuperação: {erro}. Use Salvar projeto."
            )

    def iniciar_sessao(self):
        self.carregar_entrada()
        self.aplicando_projeto = False
        self.doc.estado = self.estado_atual()
        self.atualizar_titulo()
        self.status.set("Abra uma pasta de imagens ou um projeto para começar.")

    def recuperar_ultima_sessao(self):
        if not self.confirmar_troca_projeto():
            return
        ultima = self.projeto / "projetos" / "ultima_sessao.json"
        if ultima.exists():
            import json

            try:
                caminho = json.loads(ultima.read_text(encoding="utf-8"))["recuperacao"]
                self.doc = Projeto.abrir(caminho, recuperacao=True)
                self.aplicar_estado(self.doc.estado)
                self.execucao_selecionada.set(
                    self.doc.execucoes[-1]["nome"]
                    if self.doc.execucoes
                    else "Sem execuções"
                )
                self.alterado = True
                self.atualizar_titulo()
                self.status.set(
                    "Sessão recuperada. Recortes, notas e histórico restaurados."
                )
                self.carregar_resultados_projeto()
                return
            except OSError, ValueError, KeyError, TypeError:
                self.status.set(
                    "A recuperação não pôde ser lida. Abra um projeto salvo."
                )
        else:
            self.status.set("Nenhuma sessão anterior disponível para recuperar.")

    def aplicar_estado(self, estado, carregar_mapa=False):
        self.aplicando_projeto = True
        if self.timer_notas:
            self.janela.after_cancel(self.timer_notas)
            self.timer_notas = None
        self.geracao += 1
        self.leitura_pendente = None
        self.entrada = Path(estado["entrada"]) if estado["entrada"] else None
        self.saida = Path(estado["saida"])
        self.mde = estado.get("mde")
        self.temperatura_ar.set(estado.get("temperatura_ar", ""))
        self.roi = deepcopy(estado["roi"])
        self.imagens_projeto = estado["imagens"]
        self.pastagens.set(estado.get("pastagens", False))
        self.ano.set(estado.get("ano", "2025"))
        self.produto.set(estado.get("produto", "NDVI"))
        self.notas.delete("1.0", "end")
        self.notas.insert("1.0", estado.get("notas", ""))
        for seletor in self.seletores.values():
            seletor.clear()
        self.relatorio_processado = None
        self.crs = None
        self.carregar_entrada()
        if self.cenas:
            indice = next(
                (
                    i
                    for i, c in enumerate(self.cenas)
                    if identificar_cena(c) == estado.get("data_visivel")
                ),
                0,
            )
            self.mostrar_data(indice, restaurar=True, carregar=carregar_mapa)
            if estado.get("vista"):
                self.carregando = True
                self.eixo.set_xlim(estado["vista"]["x"])
                self.eixo.set_ylim(estado["vista"]["y"])
                self.carregando = False
                self.atualizar_vista()
        self.aplicando_projeto = False
        self.atualizar_resumo()

    def confirmar_troca_projeto(self):
        if self.processando:
            messagebox.showinfo(
                "Projeto", "Aguarde a execução terminar antes de trocar de projeto."
            )
            return False
        self.registrar_alteracao()
        if not self.alterado:
            return True
        resposta = messagebox.askyesnocancel(
            "Salvar projeto", "Salvar as alterações deste projeto antes de continuar?"
        )
        if resposta is None:
            return False
        return self.salvar_projeto() if resposta else True

    def novo_projeto(self):
        if not self.confirmar_troca_projeto():
            return
        nome = ctk.CTkInputDialog(
            text="Nome do novo projeto:", title="Novo projeto"
        ).get_input()
        if not nome or not nome.strip():
            return
        estado = self.estado_atual()
        estado.update(
            entrada=None, roi=None, notas="", imagens=None, vista=None,
            data_visivel=None, mde=None, temperatura_ar="", pastagens=False,
        )
        self.doc = Projeto(nome.strip(), estado)
        self.doc.estado["saida"] = str(
            self.projeto / "projetos" / self.doc.identificador / "resultados"
        )
        self.aplicar_estado(self.doc.estado)
        self.alterado = True
        self.execucao_selecionada.set("Sem execuções")
        self.painel_resultados.atualizar(self.saida)
        self.paginas.set("Mapa")
        self.mudar_pagina()
        self.atualizar_titulo()
        self.recuperar_automaticamente()

    def abrir_projeto(self):
        if not self.confirmar_troca_projeto():
            return
        caminho = filedialog.askopenfilename(
            title="Abrir projeto Evapo",
            filetypes=[("Projeto Evapo", "*.evapo.json"), ("JSON", "*.json")],
        )
        if not caminho:
            return
        try:
            projeto = Projeto.abrir(caminho)
            self.doc = projeto
            self.aplicar_estado(projeto.estado)
            self.alterado = False
            self.execucao_selecionada.set(
                projeto.execucoes[-1]["nome"] if projeto.execucoes else "Sem execuções"
            )
            self.atualizar_titulo()
            self.recuperar_automaticamente()
            self.paginas.set("Mapa")
            self.mudar_pagina()
            self.carregar_resultados_projeto()
            self.status.set(f"Projeto aberto: {projeto.nome}")
        except (OSError, ValueError, KeyError, TypeError) as erro:
            messagebox.showerror("Projeto", str(erro))

    def salvar_projeto(self, como=False):
        self.registrar_alteracao()
        caminho = None if como else self.doc.arquivo
        if not caminho:
            caminho = filedialog.asksaveasfilename(
                title="Salvar projeto Evapo",
                initialfile=f"{self.doc.nome}.evapo.json",
                defaultextension=".evapo.json",
                filetypes=[("Projeto Evapo", "*.evapo.json")],
            )
        if not caminho:
            return False
        try:
            if como and self.doc.arquivo != Path(caminho).resolve():
                from uuid import uuid4

                copia = deepcopy(self.doc)
                copia.identificador = uuid4().hex
                copia.nome = Path(caminho).name.removesuffix(".evapo.json")
                copia.estado["saida"] = str(
                    self.projeto / "projetos" / copia.identificador / "resultados"
                )
                copia.salvar(caminho)
                self.doc = copia
                self.saida = Path(copia.estado["saida"])
                self.atualizar_resumo()
            else:
                self.doc.salvar(caminho)
            self.alterado = False
            self.recuperar_automaticamente()
            self.atualizar_titulo()
            self.status.set(f"Projeto salvo: {caminho}")
            return True
        except OSError as erro:
            messagebox.showerror("Salvar projeto", str(erro))
            return False

    def desfazer(self):
        self.registrar_alteracao()
        estado = self.doc.voltar()
        if estado is not None:
            self.aplicar_estado(estado, carregar_mapa=self.mapa_ativo)
            self.alterado = True
            self.atualizar_titulo()
            self.recuperar_automaticamente()

    def refazer(self):
        estado = self.doc.avancar()
        if estado is not None:
            self.aplicar_estado(estado, carregar_mapa=self.mapa_ativo)
            self.alterado = True
            self.atualizar_titulo()
            self.recuperar_automaticamente()

    def editar_notas(self, evento=None):
        if self.timer_notas:
            self.janela.after_cancel(self.timer_notas)
        self.timer_notas = self.janela.after(700, self.concluir_notas)

    def concluir_notas(self):
        self.timer_notas = None
        self.registrar_alteracao()

    def nova_nota(self):
        from datetime import datetime

        referencia = self.cenas[self.indice]["data"] if self.cenas else "Projeto"
        pixel = getattr(self, "ultimo_pixel", None)
        texto = f"\n\n[{datetime.now().astimezone():%d/%m/%Y %H:%M}] {referencia} · {self.produto.get()}"
        if pixel:
            texto += f" · X={pixel[0]:.2f}, Y={pixel[1]:.2f}, CRS={self.crs}"
        self.notas.insert("end", texto + "\n")
        self.paginas.set("Notas")
        self.mudar_pagina()
        self.notas.focus_set()
        self.notas.see("end")
        self.registrar_alteracao()

    def pasta_analise_existente(self):
        """Encontra a análise escolhida sem ler rasters nem abrir suas figuras."""
        pasta = self.painel_resultados.pastas.get(self.painel_resultados.analise.get())
        if not pasta:
            nome = self.execucao_selecionada.get()
            execucao = next(
                (e for e in self.doc.execucoes if e["nome"] == nome),
                self.doc.execucoes[-1] if self.doc.execucoes else None,
            )
            saida = Path(execucao["pasta"]) if execucao else self.saida
            try:
                self.painel_resultados.atualizar(saida)
            except (OSError, ValueError, KeyError) as erro:
                mensagem = f"Não foi possível ler os resultados para exportar: {erro}"
                self.status.set(mensagem)
                messagebox.showerror("Exportação", mensagem)
                return None
            pasta = self.painel_resultados.pastas.get(self.painel_resultados.analise.get())
        if not pasta or not any(
            (pasta / nome).is_file()
            for nome in ("estatisticas_todas_cenas_roi.csv", "estatisticas_por_vigor.csv")
        ):
            messagebox.showinfo(
                "Exportação",
                "Processe as imagens ou abra os resultados de uma execução salva. "
                "Escolha a análise que deseja exportar na aba Resultados.",
            )
            return None
        return pasta

    def pasta_analise(self):
        pasta = self.pasta_analise_existente()
        if pasta and not (pasta / "relatorio.html").is_file():
            messagebox.showinfo(
                "Exportação", "Esta análise não possui o relatório completo HTML. "
                "Use Exportar relatório PDF para gerar a interpretação dos resultados.",
            )
            return None
        return pasta

    def exportar_relatorio_pdf_projeto(self):
        pasta = self.pasta_analise_existente()
        if not pasta:
            return
        destino = filedialog.asksaveasfilename(
            title="Exportar relatório interpretativo em PDF",
            initialfile=f"relatorio_evapo_{pasta.name}.pdf",
            defaultextension=".pdf",
            filetypes=[("Relatório PDF", "*.pdf")],
        )
        if not destino:
            return
        self.registrar_alteracao()
        projeto = deepcopy(self.doc.documento())
        self.status.set("Gerando relatório PDF com a interpretação dos resultados…")

        def executar():
            from evapo.relatorios.pdf import gerar_pdf_da_pasta

            arquivo = gerar_pdf_da_pasta(pasta, Path(destino), projeto)
            return f"Relatório PDF exportado: {arquivo}"

        self.tarefa(executar, self.status.set)

    def exportar_relatorio_projeto(self):
        pasta = self.pasta_analise()
        if not pasta:
            return
        destino = filedialog.asksaveasfilename(
            title="Exportar relatório completo (PDF, HTML, figuras, tabelas e animações)",
            initialfile="relatorio_evapo.zip",
            defaultextension=".zip",
            filetypes=[("Relatório completo ZIP", "*.zip")],
        )
        if destino:
            self.registrar_alteracao()
            projeto = deepcopy(self.doc.documento())

            def executar():
                exportar_relatorio(pasta, destino, projeto)
                return f"Relatório completo exportado: {destino}"

            self.tarefa(executar, self.status.set)

    def exportar_pngs(self):
        pasta = self.pasta_analise()
        if not pasta:
            return
        destino = filedialog.askdirectory(
            title="Exportar todos os mapas e histogramas em PNG"
        )
        if destino:

            def executar():
                exportacao, quantidade = exportar_imagens(pasta, destino)
                return f"{quantidade} imagens exportadas em: {exportacao}"

            self.tarefa(executar, self.status.set)

    def exportar_vista_png(self):
        if self.camada is None or self.leitura_em_andamento or self.timer_vista:
            messagebox.showinfo(
                "PNG", "Aguarde o mapa terminar de carregar antes de exportar a vista."
            )
            return
        destino = filedialog.asksaveasfilename(
            title="Exportar vista atual do mapa",
            initialfile=f"{self.cenas[self.indice]['data']}_{self.produto.get().replace(' ', '_')}.png",
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
        )
        if destino:
            try:
                self.figura.savefig(destino, dpi=200, facecolor="white")
                self.status.set(
                    f"Vista exportada: {destino}. Para todas as datas, use Exportar imagens PNG."
                )
            except OSError as erro:
                messagebox.showerror("PNG", str(erro))

    def carregar_resultados_projeto(self, nome=None):
        if nome is None:
            nome = self.execucao_selecionada.get()
        execucao = next((e for e in self.doc.execucoes if e["nome"] == nome), None)
        if execucao is None:
            # Projetos antigos podem ter resultados diretamente na saída.
            self.painel_resultados.atualizar(self.saida)
            return
        pasta = Path(execucao["pasta"])
        estado = execucao.get("estado", {})
        preferida = None
        if estado.get("pastagens"):
            analise = (
                "pastagens_imagem_completa"
                if usar_imagem_inteira(estado.get("roi"))
                else "pastagens"
            )
            preferida = pasta / analise
        self.painel_resultados.atualizar(pasta, preferida)

    def escolher_execucao(self, nome):
        execucao = next((e for e in self.doc.execucoes if e["nome"] == nome), None)
        if execucao:
            try:
                self.carregar_resultados_projeto(nome)
                self.paginas.set("Resultados")
                self.mudar_pagina()
            except (OSError, ValueError) as erro:
                messagebox.showerror("Resultados", str(erro))

    def restaurar_execucao(self):
        execucao = next(
            (
                e
                for e in self.doc.execucoes
                if e["nome"] == self.execucao_selecionada.get()
            ),
            None,
        )
        if not execucao or not execucao.get("estado"):
            messagebox.showinfo(
                "Configuração",
                "Escolha uma execução deste projeto com configuração salva.",
            )
            return
        self.registrar_alteracao()
        estado = deepcopy(execucao["estado"])
        self.doc.editar(estado)
        self.aplicar_estado(estado, carregar_mapa=True)
        self.alterado = True
        self.recuperar_automaticamente()
        self.atualizar_titulo()
        self.paginas.set("Mapa")
        self.mudar_pagina()
        self.status.set(
            "Configuração restaurada. O próximo processamento criará uma nova execução."
        )
