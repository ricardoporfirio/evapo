"""Zoom e deslocamento do mapa sem alterar as coordenadas da ROI."""

from matplotlib.backend_bases import MouseButton


class NavegacaoMapa:
    """A roda aproxima/afasta; o modo Mover permite arrastar com o botão esquerdo.

    O botão do meio também permite mover, mesmo durante o modo Desenhar.
    Os seletores ficam desativados durante o movimento para não criar uma ROI
    por acidente. Ao terminar, o desenho que já existia é preservado.
    """

    def __init__(self, eixo, ao_mudar_modo, redesenhar=None, ao_terminar=None):
        self.eixo = eixo
        self.ao_mudar_modo = ao_mudar_modo
        self.redesenhar = redesenhar or eixo.figure.canvas.draw_idle
        self.ao_terminar = ao_terminar
        self.limites_iniciais_x = eixo.get_xlim()
        self.limites_iniciais_y = eixo.get_ylim()
        self.modo = "desenhar"
        self.inicio_do_movimento = None

        tela = eixo.figure.canvas
        self.conexoes = [
            tela.mpl_connect("scroll_event", self.usar_roda),
            tela.mpl_connect("button_press_event", self.iniciar_movimento),
            tela.mpl_connect("motion_notify_event", self.mover_mapa),
            tela.mpl_connect("button_release_event", self.terminar_movimento),
        ]

    def escolher_modo(self, modo):
        if modo not in ("desenhar", "mover"):
            raise ValueError("Escolha o modo desenhar ou mover.")
        self.inicio_do_movimento = None
        self.modo = modo
        self.ao_mudar_modo(modo)

    def aplicar_zoom(self, aproximar, centro_x=None, centro_y=None):
        # Menor intervalo visível significa mais aproximação.
        fator_zoom = 1 / 1.25 if aproximar else 1.25
        esquerda, direita = self.eixo.get_xlim()
        inferior, superior = self.eixo.get_ylim()
        if centro_x is None:
            centro_x = (esquerda + direita) / 2
        if centro_y is None:
            centro_y = (inferior + superior) / 2

        novos_limites_x = (
            centro_x + (esquerda - centro_x) * fator_zoom,
            centro_x + (direita - centro_x) * fator_zoom,
        )
        novos_limites_y = (
            centro_y + (inferior - centro_y) * fator_zoom,
            centro_y + (superior - centro_y) * fator_zoom,
        )
        self.eixo.set_xlim(novos_limites_x)
        self.eixo.set_ylim(novos_limites_y)
        self.redesenhar()

    def usar_roda(self, evento):
        if evento.inaxes != self.eixo or evento.step == 0:
            return
        if self.inicio_do_movimento is not None:
            return
        self.aplicar_zoom(evento.step > 0, evento.xdata, evento.ydata)

    def ver_tudo(self):
        self.eixo.set_xlim(self.limites_iniciais_x)
        self.eixo.set_ylim(self.limites_iniciais_y)
        self.redesenhar()

    def iniciar_movimento(self, evento):
        if evento.inaxes != self.eixo:
            return
        botao_do_meio = evento.button == MouseButton.MIDDLE
        botao_esquerdo_no_modo_mover = (
            evento.button == MouseButton.LEFT and self.modo == "mover"
        )
        if not botao_do_meio and not botao_esquerdo_no_modo_mover:
            return

        self.inicio_do_movimento = {
            "mouse_x": evento.x,
            "mouse_y": evento.y,
            "limites_x": self.eixo.get_xlim(),
            "limites_y": self.eixo.get_ylim(),
            "botao": evento.button,
        }
        self.ao_mudar_modo("mover")

    def mover_mapa(self, evento):
        if self.inicio_do_movimento is None or evento.x is None or evento.y is None:
            return
        inicio = self.inicio_do_movimento
        esquerda, direita = inicio["limites_x"]
        inferior, superior = inicio["limites_y"]

        # Converte o deslocamento do mouse (pixels da tela) para metros no mapa.
        metros_por_pixel_x = (direita - esquerda) / self.eixo.bbox.width
        metros_por_pixel_y = (superior - inferior) / self.eixo.bbox.height
        deslocamento_x = (evento.x - inicio["mouse_x"]) * metros_por_pixel_x
        deslocamento_y = (evento.y - inicio["mouse_y"]) * metros_por_pixel_y

        self.eixo.set_xlim(esquerda - deslocamento_x, direita - deslocamento_x)
        self.eixo.set_ylim(inferior - deslocamento_y, superior - deslocamento_y)
        self.redesenhar()

    def terminar_movimento(self, evento):
        if self.inicio_do_movimento is None:
            return
        if evento.button != self.inicio_do_movimento["botao"]:
            return
        self.inicio_do_movimento = None
        self.ao_mudar_modo(self.modo)
        if self.ao_terminar is not None:
            self.ao_terminar()
