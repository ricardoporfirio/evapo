"""Abrir ou recuperar um projeto deve carregar a execução indicada na tela."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from evapo.interface.acoes_projeto import AcoesProjeto
from evapo.dados.projetos import Projeto, gravar_documento


class Variavel:
    def __init__(self, valor=None):
        self.valor = valor

    def get(self):
        return self.valor

    def set(self, valor):
        self.valor = valor


class AberturaResultadosTest(unittest.TestCase):
    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.pasta = Path(temporario.name)
        self.estado = dict(entrada=None, saida=str(self.pasta / "resultados"),
                           roi=None, imagens=None, notas="", pastagens=True)
        projeto = Projeto("Teste", self.estado)
        self.antiga = projeto.iniciar_execucao(self.estado["saida"])
        self.ultima = projeto.iniciar_execucao(self.estado["saida"])
        self.arquivo = self.pasta / "teste.evapo.json"
        projeto.salvar(self.arquivo)
        self.app = AcoesProjeto()
        self.app.doc = projeto
        self.app.projeto = self.pasta
        self.app.saida = Path(self.estado["saida"])
        self.app.execucao_selecionada = Variavel()
        self.app.paginas = Variavel()
        self.app.status = Variavel()
        self.app.painel_resultados = Mock()
        self.app.confirmar_troca_projeto = Mock(return_value=True)
        for nome in ("aplicar_estado", "atualizar_titulo", "recuperar_automaticamente", "mudar_pagina"):
            setattr(self.app, nome, Mock())

    def conferir_ultima(self):
        pasta = Path(self.ultima["pasta"])
        self.app.painel_resultados.atualizar.assert_called_once_with(
            pasta, pasta / "pastagens_imagem_completa"
        )
        self.assertEqual(self.app.execucao_selecionada.get(), self.ultima["nome"])

    def test_abrir_carrega_pasta_da_execucao_e_preserva_aba_mapa(self):
        with patch("evapo.interface.acoes_projeto.filedialog.askopenfilename", return_value=str(self.arquivo)):
            self.app.abrir_projeto()
        self.conferir_ultima()
        self.assertEqual(self.app.paginas.get(), "Mapa")

    def test_recuperacao_carrega_pasta_da_execucao(self):
        gravar_documento(self.pasta / "projetos" / "ultima_sessao.json",
                        {"recuperacao": str(self.arquivo)})
        self.app.recuperar_ultima_sessao()
        self.conferir_ultima()

    def test_sem_execucoes_preserva_resultados_antigos_na_saida(self):
        self.app.doc.execucoes = []
        self.app.carregar_resultados_projeto()
        self.app.painel_resultados.atualizar.assert_called_once_with(self.app.saida)

    def test_escolher_execucao_antiga_carrega_apenas_a_escolhida(self):
        self.app.escolher_execucao(self.antiga["nome"])
        pasta = Path(self.antiga["pasta"])
        self.app.painel_resultados.atualizar.assert_called_once_with(
            pasta, pasta / "pastagens_imagem_completa"
        )
        self.assertEqual(self.app.paginas.get(), "Resultados")

    def test_preferencia_respeita_roi_salva_na_execucao(self):
        self.ultima["estado"]["roi"] = {"geometry": {"type": "Polygon"}}
        self.app.carregar_resultados_projeto(self.ultima["nome"])
        pasta = Path(self.ultima["pasta"])
        self.app.painel_resultados.atualizar.assert_called_once_with(pasta, pasta / "pastagens")


if __name__ == "__main__":
    unittest.main()
