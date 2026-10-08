"""Documentos de projeto, histórico de edição e execuções que não se sobrescrevem."""

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def gravar_documento(caminho, documento):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(
        json.dumps(documento, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporario.replace(caminho)


class Projeto:
    def __init__(self, nome, estado):
        self.identificador = uuid4().hex
        self.nome = nome
        self.arquivo = None
        self.estado = deepcopy(estado)
        self.desfazer = []
        self.refazer = []
        self.execucoes = []

    def editar(self, estado):
        if estado == self.estado:
            return False
        self.desfazer.append(deepcopy(self.estado))
        self.desfazer = self.desfazer[-100:]
        self.refazer.clear()
        self.estado = deepcopy(estado)
        return True

    def voltar(self):
        if not self.desfazer:
            return None
        self.refazer.append(deepcopy(self.estado))
        self.estado = self.desfazer.pop()
        return deepcopy(self.estado)

    def avancar(self):
        if not self.refazer:
            return None
        self.desfazer.append(deepcopy(self.estado))
        self.estado = self.refazer.pop()
        return deepcopy(self.estado)

    def documento(self):
        return {
            "formato": "evapo",
            "versao": 1,
            "id": self.identificador,
            "nome": self.nome,
            "arquivo": str(self.arquivo) if self.arquivo else None,
            "estado": self.estado,
            "desfazer": self.desfazer,
            "refazer": self.refazer,
            "execucoes": self.execucoes,
        }

    def salvar(self, caminho):
        anterior = self.arquivo
        self.arquivo = Path(caminho).resolve()
        try:
            gravar_documento(self.arquivo, self.documento())
        except OSError:
            self.arquivo = anterior
            raise

    @classmethod
    def abrir(cls, caminho, recuperacao=False):
        documento = json.loads(Path(caminho).read_text(encoding="utf-8"))
        if documento.get("formato") != "evapo" or documento.get("versao") != 1:
            raise ValueError("Este arquivo não é um projeto Evapo compatível.")
        estado = documento.get("estado")
        if not isinstance(estado, dict) or not all(
            chave in estado for chave in ("entrada", "saida", "roi", "imagens", "notas")
        ):
            raise ValueError("O projeto não contém as configurações necessárias.")
        projeto = cls(documento["nome"], estado)
        projeto.identificador = documento["id"]
        projeto.arquivo = (
            Path(documento["arquivo"])
            if recuperacao and documento.get("arquivo")
            else (None if recuperacao else Path(caminho).resolve())
        )
        projeto.desfazer = documento.get("desfazer", [])
        projeto.refazer = documento.get("refazer", [])
        projeto.execucoes = documento.get("execucoes", [])
        return projeto

    def iniciar_execucao(self, destino):
        nome = (
            datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
            + "_"
            + uuid4().hex[:6]
        )
        pasta = Path(destino) / "execucoes" / nome
        pasta.mkdir(parents=True, exist_ok=False)
        execucao = {
            "nome": nome,
            "pasta": str(pasta.resolve()),
            "status": "processando",
            "estado": deepcopy(self.estado),
        }
        self.execucoes.append(execucao)
        gravar_documento(pasta / "configuracao.evapo.json", self.documento())
        return execucao
