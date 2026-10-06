"""Reutiliza vistas que já cobrem o mapa com resolução suficiente."""

from collections import OrderedDict


class CacheVistas:
    def __init__(self, capacidade=3):
        self.capacidade = capacidade
        self.vistas = OrderedDict()
        self.contador = 0

    def guardar(self, chave, resultado):
        self.contador += 1
        self.vistas[self.contador] = (chave, resultado)
        while len(self.vistas) > self.capacidade:
            self.vistas.popitem(last=False)

    def buscar(self, chave, limites, resolucao):
        esquerda, inferior, direita, superior = limites
        for indice in reversed(self.vistas):
            contexto, resultado = self.vistas[indice]
            if contexto != chave:
                continue
            produtos, bordas, _, _ = resultado
            a, b, c, d = bordas
            altura, largura = produtos["NDVI"].shape
            pixel = max((c - a) / largura, (d - b) / altura)
            cobre_vista = (
                a <= esquerda and b <= inferior and c >= direita and d >= superior
            )
            if cobre_vista and pixel <= resolucao * 1.05:
                self.vistas.move_to_end(indice)
                return resultado
        return None
