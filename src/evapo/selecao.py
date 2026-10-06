"""Guarda a escolha das imagens e filtra as cenas que entram na análise."""


def identificar_cena(cena):
    """Usa pasta/nome para manter a seleção mesmo se o projeto mudar de lugar."""
    caminho = cena["caminho"]
    return f"{caminho.parent.name}/{caminho.name}"


def filtrar_cenas_selecionadas(cenas, roi):
    escolhidas = (roi or {}).get("properties", {}).get("imagens_selecionadas")
    # ROIs anteriores a esse recurso continuam usando todas as imagens.
    if escolhidas is None:
        return cenas
    if not isinstance(escolhidas, list) or not escolhidas:
        raise ValueError("Selecione pelo menos uma imagem na janela da ROI.")
    disponiveis = {identificar_cena(cena) for cena in cenas}
    ausentes = set(escolhidas) - disponiveis
    if ausentes:
        raise ValueError(
            "Há imagens selecionadas que não estão em entrada. Abra --editar-roi para atualizar a seleção."
        )
    return [cena for cena in cenas if identificar_cena(cena) in escolhidas]
