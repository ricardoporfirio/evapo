"""Recortes, notas, histórico e resultados precisam sobreviver ao salvar/reabrir."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zipfile import ZipFile

from evapo.acoes_projeto import AcoesProjeto
from evapo.exportacoes import exportar_imagens, exportar_relatorio
from evapo.projetos import Projeto
from evapo.roi import salvar_roi


class ProjetoTest(unittest.TestCase):
    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporario.cleanup)
        self.pasta = Path(self.temporario.name)
        self.estado = {
            "entrada": str(self.pasta / "entrada"),
            "saida": str(self.pasta / "saida"),
            "roi": None,
            "imagens": ["cena/imagem.tif"],
            "notas": "Primeira nota",
        }
        self.projeto = Projeto("Pastagem", self.estado)

    def test_salvar_reabrir_e_desfazer_recorte_e_notas(self):
        estado = deepcopy(self.estado)
        estado["roi"] = salvar_roi([(0, 0), (1, 0), (1, 1), (0, 1)], "EPSG:4326", None)
        estado["notas"] = "Nota do recorte"
        self.projeto.editar(estado)
        # O histórico não pode compartilhar a geometria mutável com a janela.
        estado["roi"]["geometry"]["coordinates"][0][0][0] = 99
        arquivo = self.pasta / "teste.evapo.json"
        self.projeto.salvar(arquivo)
        aberto = Projeto.abrir(arquivo)
        self.assertEqual(aberto.estado["notas"], "Nota do recorte")
        self.assertEqual(aberto.estado["roi"]["geometry"]["coordinates"][0][0][0], 0)
        self.assertIsNone(aberto.voltar()["roi"])
        self.assertEqual(aberto.avancar()["notas"], "Nota do recorte")
        aberto.voltar()
        novo = deepcopy(aberto.estado)
        novo["notas"] = "Uma nova edição"
        aberto.editar(novo)
        self.assertIsNone(aberto.avancar())

    def test_execucoes_preservam_arquivos_e_configuracoes(self):
        primeira = self.projeto.iniciar_execucao(self.pasta / "resultados")
        arquivo = Path(primeira["pasta"]) / "original.png"
        arquivo.write_bytes(b"nao substituir")
        estado = deepcopy(self.estado)
        estado["notas"] = "Outro recorte"
        self.projeto.editar(estado)
        segunda = self.projeto.iniciar_execucao(self.pasta / "resultados")
        self.assertNotEqual(primeira["pasta"], segunda["pasta"])
        self.assertEqual(arquivo.read_bytes(), b"nao substituir")
        self.assertEqual(primeira["estado"]["notas"], "Primeira nota")

    def test_exportar_relatorio_completo_e_pngs_sem_sobrescrever(self):
        analise = self.pasta / "roi"
        data = analise / "2025-06-16"
        data.mkdir(parents=True)
        (analise / "relatorio.html").write_text(
            '<img src="2025-06-16/ndvi_mapa.png">', encoding="utf-8"
        )
        (data / "ndvi_mapa.png").write_bytes(b"PNG")
        (analise / "relatorio.pdf").write_bytes(b"%PDF-1.4 Relatorio interpretativo")
        (data / "relatorio.html").write_text("Detalhes", encoding="utf-8")
        destino = self.pasta / "relatorio.zip"
        exportar_relatorio(analise, destino, self.projeto.documento())
        with ZipFile(destino) as pacote:
            self.assertIn("2025-06-16/ndvi_mapa.png", pacote.namelist())
            self.assertIn("relatorio.pdf", pacote.namelist())
            self.assertEqual(pacote.read("notas.txt").decode(), "Primeira nota")
            self.assertEqual(
                json.loads(pacote.read("projeto.evapo.json"))["nome"], "Pastagem"
            )
        primeira, quantidade = exportar_imagens(analise, self.pasta / "exportados")
        segunda, _ = exportar_imagens(analise, self.pasta / "exportados")
        self.assertEqual(quantidade, 1)
        self.assertNotEqual(primeira, segunda)
        self.assertEqual((primeira / "2025-06-16/ndvi_mapa.png").read_bytes(), b"PNG")

    def test_rejeitar_documento_sem_configuracao(self):
        arquivo = self.pasta / "invalido.json"
        arquivo.write_text('{"formato":"evapo","versao":1,"estado":{}}')
        with self.assertRaises(ValueError):
            Projeto.abrir(arquivo)


class ExportacaoPDFTest(unittest.TestCase):
    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporario.cleanup)
        self.pasta = Path(self.temporario.name)
        self.analise = self.pasta / "execucao_antiga" / "roi"
        self.analise.mkdir(parents=True)
        # Resultados antigos podem não ter um PDF nem o relatório HTML.
        (self.analise / "estatisticas_todas_cenas_roi.csv").write_text(
            "data;produto;media\n2025-06-16;ndvi;0.6\n", encoding="utf-8"
        )
        self.app = AcoesProjeto()
        self.app.doc = Projeto("Pastagem", {"notas": "Observações"})
        self.app.saida = self.pasta / "saida"
        self.app.execucao_selecionada = Mock()
        self.app.execucao_selecionada.get.return_value = "Sem execuções"
        self.app.painel_resultados = SimpleNamespace(
            pastas={"ROI": self.analise},
            analise=Mock(),
            atualizar=Mock(),
        )
        self.app.painel_resultados.analise.get.return_value = "ROI"
        self.app.registrar_alteracao = Mock()
        self.app.status = Mock()
        self.app.tarefa = Mock()

    def test_exportar_pdf_antigo_sem_html_so_apos_salvar_destino(self):
        destino = self.pasta / "relatorio.pdf"
        with patch(
            "evapo.acoes_projeto.filedialog.asksaveasfilename",
            return_value=str(destino),
        ) as dialogo, patch(
            "evapo.relatorio_pdf.gerar_pdf_da_pasta", return_value=destino
        ) as gerar:
            self.app.exportar_relatorio_pdf_projeto()
            gerar.assert_not_called()
            executar, retorno = self.app.tarefa.call_args.args
            retorno(executar())
        self.assertEqual(dialogo.call_args.kwargs["defaultextension"], ".pdf")
        gerar.assert_called_once_with(
            self.analise, destino, self.app.doc.documento()
        )
        self.app.painel_resultados.atualizar.assert_not_called()
        self.app.status.set.assert_called_with(f"Relatório PDF exportado: {destino}")

    def test_cancelar_exportacao_nao_gera_pdf_nem_altera_projeto(self):
        with patch(
            "evapo.acoes_projeto.filedialog.asksaveasfilename", return_value=""
        ):
            self.app.exportar_relatorio_pdf_projeto()
        self.app.tarefa.assert_not_called()
        self.app.registrar_alteracao.assert_not_called()
        self.app.status.set.assert_not_called()

    def test_descobrir_resultados_da_execucao_selecionada(self):
        self.app.doc.execucoes = [
            {"nome": "Antiga", "pasta": str(self.analise.parent)},
            {"nome": "Nova", "pasta": str(self.pasta / "execucao_nova")},
        ]
        self.app.execucao_selecionada.get.return_value = "Antiga"
        painel = self.app.painel_resultados
        painel.pastas = {}

        def atualizar(saida):
            painel.pastas = {"ROI": Path(saida) / "roi"}

        painel.atualizar.side_effect = atualizar
        self.assertEqual(self.app.pasta_analise_existente(), self.analise)
        painel.atualizar.assert_called_once_with(self.analise.parent)

    def test_sem_resultados_nao_abre_dialogo_de_destino(self):
        self.app.painel_resultados.pastas = {}
        with patch("evapo.acoes_projeto.messagebox.showinfo") as aviso, patch(
            "evapo.acoes_projeto.filedialog.asksaveasfilename"
        ) as dialogo:
            self.app.exportar_relatorio_pdf_projeto()
        aviso.assert_called_once()
        dialogo.assert_not_called()
        self.app.tarefa.assert_not_called()

    def test_falha_ao_ler_resultados_informa_erro(self):
        self.app.painel_resultados.pastas = {}
        self.app.painel_resultados.atualizar.side_effect = ValueError("CSV inválido")
        with patch("evapo.acoes_projeto.messagebox.showerror") as aviso, patch(
            "evapo.acoes_projeto.filedialog.asksaveasfilename"
        ) as dialogo:
            self.app.exportar_relatorio_pdf_projeto()
        aviso.assert_called_once()
        self.assertIn("CSV inválido", self.app.status.set.call_args.args[0])
        dialogo.assert_not_called()
        self.app.tarefa.assert_not_called()
