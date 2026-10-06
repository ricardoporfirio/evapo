"""Confere as ações reais da janela sem diálogos nem alterações nos dados do usuário."""

import json
import unittest
from copy import deepcopy
from unittest.mock import patch

import customtkinter as ctk
import test_imagem_inteira as base

from evapo.projetos import Projeto, gravar_documento
from evapo.sistema import SistemaEvapo


class SistemaProjetosTest(unittest.TestCase):
    setUp = base.ImagemInteiraTest.setUp

    def criar_janela(self, carregar=True):
        janela = ctk.CTk()
        janela.withdraw()

        def fechar():
            for timer in janela.tk.call("after", "info"):
                janela.tk.call("after", "cancel", timer)
            janela.destroy()

        self.addCleanup(fechar)
        app = SistemaEvapo(janela, self.pasta)
        janela.after_cancel(app.timer_inicial)
        app.atualizar_vista = lambda: None
        self.mock_descobrir = patch(
            "evapo.sistema.descobrir_cenas", return_value=self.cenas
        )
        self.descobrir = self.mock_descobrir.start()
        self.addCleanup(self.mock_descobrir.stop)
        app.iniciar_sessao()
        if carregar:
            app.entrada = self.pasta / "entrada"
            app.carregar_entrada()
            app.mostrar_data(0)
        app.aplicando_projeto = False
        app.doc.estado = app.estado_atual()
        return app

    def test_inicio_vazio_mesmo_com_entrada_e_sessao_anterior(self):
        app = self.criar_janela(carregar=False)
        estado_anterior = deepcopy(app.doc.estado)
        estado_anterior["entrada"] = str(self.pasta)
        anterior = Projeto("Sessão anterior", estado_anterior)
        recuperacao = self.pasta / "projetos" / "anterior.evapo.json"
        anterior.salvar(recuperacao)
        ultima = self.pasta / "projetos" / "ultima_sessao.json"
        gravar_documento(ultima, {"recuperacao": str(recuperacao)})
        ponteiro_anterior = ultima.read_text(encoding="utf-8")
        with patch("evapo.sistema.rasterio.open") as abrir_raster:
            app.iniciar_sessao()
            app.recuperar_automaticamente()
            abrir_raster.assert_not_called()
        self.descobrir.assert_not_called()
        self.assertIsNone(app.entrada)
        self.assertEqual(app.cenas, [])
        self.assertEqual(app.marcadas, [])
        self.assertFalse(app.lista_datas.winfo_children())
        self.assertFalse(app.mapa_ativo)
        self.assertEqual(app.botao_processar.cget("state"), "disabled")
        self.assertEqual(ultima.read_text(encoding="utf-8"), ponteiro_anterior)
        with patch("evapo.sistema.filedialog.askdirectory", return_value=str(self.pasta)):
            app.abrir_entrada()
        self.descobrir.assert_called_once()
        self.assertEqual(len(app.cenas), len(self.cenas))
        self.assertTrue(app.lista_datas.winfo_children())
        self.assertFalse(app.mapa_ativo)

    def test_novo_projeto_nao_herda_imagens_abertas(self):
        app = self.criar_janela()
        self.descobrir.reset_mock()
        with patch.object(app, "confirmar_troca_projeto", return_value=True), patch(
            "evapo.acoes_projeto.ctk.CTkInputDialog"
        ) as dialogo:
            dialogo.return_value.get_input.return_value = "Novo vazio"
            app.novo_projeto()
        self.descobrir.assert_not_called()
        self.assertIsNone(app.entrada)
        self.assertFalse(app.cenas)
        self.assertFalse(app.lista_datas.winfo_children())
        self.assertFalse(app.mapa_ativo)

    def test_projeto_salvo_sem_imagens_reabre_vazio(self):
        app = self.criar_janela(carregar=False)
        arquivo = self.pasta / "vazio.evapo.json"
        app.doc.salvar(arquivo)
        app.aplicar_estado(Projeto.abrir(arquivo).estado)
        self.descobrir.assert_not_called()
        self.assertIsNone(app.entrada)
        self.assertFalse(app.cenas)

    def test_recuperacao_de_sessao_exige_acao_explicita(self):
        app = self.criar_janela(carregar=False)
        estado_anterior = deepcopy(app.doc.estado)
        estado_anterior["entrada"] = str(self.pasta)
        estado_anterior["notas"] = "Notas da sessão anterior"
        anterior = Projeto("Sessão anterior", estado_anterior)
        recuperacao = self.pasta / "projetos" / "anterior.evapo.json"
        anterior.salvar(recuperacao)
        gravar_documento(
            self.pasta / "projetos" / "ultima_sessao.json",
            {"recuperacao": str(recuperacao)},
        )
        app.iniciar_sessao()
        self.descobrir.assert_not_called()
        app.recuperar_ultima_sessao()
        self.descobrir.assert_called_once()
        self.assertEqual(app.doc.nome, "Sessão anterior")
        self.assertEqual(app.notas.get("1.0", "end-1c"), estado_anterior["notas"])
        self.assertEqual(len(app.cenas), len(self.cenas))
        self.assertFalse(app.mapa_ativo)

    def test_recorte_undo_redo_salvar_reabrir_com_notas(self):
        app = self.criar_janela()
        app.definir_roi(
            [(500000, 7600000), (500090, 7600000), (500090, 7599940), (500000, 7599940)]
        )
        roi = deepcopy(app.roi)
        self.assertFalse((app.saida / "roi.geojson").exists())
        app.desfazer()
        self.assertIsNone(app.roi)
        self.assertTrue(app.mapa_ativo)
        app.refazer()
        self.assertEqual(app.roi, roi)
        self.assertTrue(app.mapa_ativo)
        app.notas.insert("end", "Nota da pastagem")
        app.registrar_alteracao()
        arquivo = self.pasta / "pastagem.evapo.json"
        with patch(
            "evapo.acoes_projeto.filedialog.asksaveasfilename",
            return_value=str(arquivo),
        ):
            self.assertTrue(app.salvar_projeto())
        aberto = Projeto.abrir(arquivo)
        self.assertEqual(aberto.estado["roi"], roi)
        self.assertEqual(aberto.estado["notas"], "Nota da pastagem")
        app.imagem_inteira()
        app.aplicar_estado(aberto.estado)
        self.assertEqual(app.roi, roi)
        self.assertEqual(app.notas.get("1.0", "end-1c"), "Nota da pastagem")
        # Reabrir a pasta não pode substituir a ROI por um arquivo antigo.
        app.carregar_entrada()
        self.assertEqual(app.roi, roi)
        recuperacao = (
            app.projeto / "projetos" / app.doc.identificador / "recuperacao.evapo.json"
        )
        self.assertTrue(recuperacao.exists())

    def test_salvar_como_cria_projeto_separado(self):
        app = self.criar_janela()
        origem = self.pasta / "original.evapo.json"
        app.doc.salvar(origem)
        id_original, destino_original = app.doc.identificador, app.saida
        copia = self.pasta / "copia.evapo.json"
        with patch(
            "evapo.acoes_projeto.filedialog.asksaveasfilename", return_value=str(copia)
        ):
            self.assertTrue(app.salvar_projeto(como=True))
        self.assertNotEqual(app.doc.identificador, id_original)
        self.assertNotEqual(app.saida, destino_original)
        self.assertEqual(
            json.loads(origem.read_text(encoding="utf-8"))["id"], id_original
        )

    def test_imagens_so_carregam_ao_escolher_data(self):
        app = self.criar_janela()
        # Recupera o método real, que a preparação dos testes substitui.
        app.atualizar_vista = SistemaEvapo.atualizar_vista.__get__(app)
        with patch.object(app, "iniciar_leitura") as ler:
            app.carregar_entrada()
            app.atualizar_vista()
            app.aplicar_estado(app.doc.estado)
            self.assertFalse(app.mapa_ativo)
            ler.assert_not_called()
            app.mostrar_data(0)
            self.assertTrue(app.mapa_ativo)
            ler.assert_called_once()
            self.assertIsNotNone(app.leitura_pendente)
