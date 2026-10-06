"""Comando principal: configura entradas, seleciona a ROI e coordena as saídas."""

import argparse
from pathlib import Path


def criar_parser():
    parser = argparse.ArgumentParser(
        description="Análise das cenas Landsat por uma ROI comum."
    )
    parser.add_argument(
        "--entrada",
        type=Path,
        default=Path("entrada"),
        help="Pasta das cenas (padrão: entrada).",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=Path("saida"),
        help="Pasta de saída (padrão: saida).",
    )
    parser.add_argument(
        "--roi",
        type=Path,
        help="GeoJSON existente ou caminho de gravação; padrão: <saida>/roi.geojson.",
    )
    parser.add_argument(
        "--referencia",
        type=Path,
        help="Empilhamento para desenhar a ROI; padrão: primeira data.",
    )
    parser.add_argument(
        "--editar-roi",
        action="store_true",
        help="Abre a janela para editar o desenho e as imagens selecionadas.",
    )
    parser.add_argument(
        "--somente-roi",
        action="store_true",
        help="Seleciona/reutiliza a ROI sem calcular produtos.",
    )
    parser.add_argument(
        "--sem-interface",
        action="store_true",
        help="Não abre a janela; sem ROI salva, usa a imagem inteira.",
    )
    parser.add_argument(
        "--imagem-inteira",
        action="store_true",
        help="Usa toda a imagem mesmo havendo uma ROI salva, sem abrir a janela.",
    )
    parser.add_argument(
        "--sem-timelapse",
        action="store_true",
        help="Gera apenas estatísticas, figuras e relatórios.",
    )
    parser.add_argument(
        "--mde",
        type=Path,
        help="MDE de uma banda em metros, para albedo da superfície.",
    )
    parser.add_argument(
        "--L",
        type=float,
        default=0.5,
        help="Parâmetro do SAVI entre 0 e 1 (padrão: 0,5).",
    )
    parser.add_argument(
        "--tamanho-frame",
        type=int,
        default=900,
        help="Maior lado da grade temporal (padrão: 900).",
    )
    parser.add_argument(
        "--baixar-mapbiomas",
        type=int,
        metavar="ANO",
        help="Baixa cobertura e vigor da Coleção 11 na ROI e acrescenta a análise das pastagens.",
    )
    parser.add_argument(
        "--pastagens",
        type=Path,
        help="Camada só de pastagens (SHP/GeoJSON) ou raster de uso do solo.",
    )
    parser.add_argument(
        "--vigor-pastagens",
        type=Path,
        help="Raster anual de vigor: 1 baixo, 2 moderado, 3 alto.",
    )
    parser.add_argument(
        "--codigo-pastagem",
        type=int,
        default=15,
        help="Código de pastagem no raster de uso do solo (MapBiomas: 15).",
    )
    parser.add_argument(
        "--ano-camada-pastagens",
        type=int,
        help="Ano de referência das camadas locais, registrado no relatório.",
    )
    parser.add_argument(
        "--limites-vigor-ndvi",
        type=float,
        nargs=2,
        metavar=("BAIXO", "ALTO"),
        help="Classifica NDVI por data com dois limites definidos pelo usuário, em vez do vigor anual.",
    )
    parser.add_argument(
        "--somente-pastagens",
        action="store_true",
        help="Gera somente a nova análise, preservando arquivos da análise geral já existentes.",
    )
    return parser


def main(argv=None):
    parser = criar_parser()
    args = parser.parse_args(argv)
    if not 0 <= args.L <= 1:
        parser.error("--L deve estar entre 0 e 1.")
    if args.tamanho_frame < 1:
        parser.error("--tamanho-frame deve ser positivo.")
    if args.editar_roi and args.sem_interface:
        parser.error("--editar-roi não pode ser combinado com --sem-interface.")
    if args.editar_roi and args.imagem_inteira:
        parser.error("--editar-roi não pode ser combinado com --imagem-inteira.")
    if args.mde is not None and not args.mde.is_file():
        parser.error("O arquivo informado em --mde não existe.")
    analisar_pastagens = args.pastagens is not None or args.baixar_mapbiomas is not None
    if (
        args.somente_pastagens or args.vigor_pastagens or args.limites_vigor_ndvi
    ) and not analisar_pastagens:
        parser.error("Informe --pastagens ou --baixar-mapbiomas ANO.")
    if args.baixar_mapbiomas is not None:
        if not 2000 <= args.baixar_mapbiomas <= 2025:
            parser.error("O vigor da Coleção 11 está disponível de 2000 a 2025.")
        if args.pastagens or args.vigor_pastagens or args.ano_camada_pastagens:
            parser.error(
                "Use --baixar-mapbiomas ou camadas locais; evite misturar fontes/anos."
            )
    if (
        args.pastagens
        and args.vigor_pastagens is None
        and args.limites_vigor_ndvi is None
    ):
        parser.error("Informe --vigor-pastagens ou --limites-vigor-ndvi BAIXO ALTO.")
    if args.vigor_pastagens and args.limites_vigor_ndvi is not None:
        parser.error("Escolha o raster de vigor anual ou os limites de NDVI.")
    if args.limites_vigor_ndvi is not None:
        baixo, alto = args.limites_vigor_ndvi
        if not -1 < baixo < alto < 1:
            parser.error("Os limites devem satisfazer -1 < BAIXO < ALTO < 1.")
    for caminho in (args.pastagens, args.vigor_pastagens):
        if caminho is not None and not caminho.is_file():
            parser.error(f"Camada não encontrada: {caminho}")
    # As figuras são exportadas sem janelas; somente o seletor usa Tk, em outro processo.
    import matplotlib

    matplotlib.use("Agg")
    from .area import delimitacao_cenas, usar_imagem_inteira
    from .estatisticas import exportar_estatisticas
    from .metadados import descobrir_cenas
    from .processamento import processar_todas_cenas
    from .relatorios import salvar_relatorio_geral
    from .roi import carregar_roi, selecionar_roi
    from .selecao import filtrar_cenas_selecionadas
    from .timelapse import montar_timelapse, preparar_frames

    try:
        cenas = descobrir_cenas(args.entrada)
        roi_path = args.roi or args.saida / "roi.geojson"
        referencia = args.referencia or cenas[0]["caminho"]
        if args.imagem_inteira:
            anterior = carregar_roi(roi_path) if roi_path.is_file() else {}
            roi = {
                "type": "Feature",
                "geometry": None,
                "properties": {
                    **anterior.get("properties", {}),
                    "imagem_inteira": True,
                },
            }
        elif args.sem_interface:
            if args.roi is not None and not roi_path.is_file():
                raise FileNotFoundError(f"ROI informada não encontrada: {roi_path}.")
            roi = carregar_roi(roi_path) if roi_path.is_file() else None
        else:
            roi = selecionar_roi(
                referencia, roi_path, editar=args.editar_roi, cenas=cenas
            )
        imagem_inteira = usar_imagem_inteira(roi)
        print(
            "Área: imagem inteira de cada cena"
            if imagem_inteira
            else f"ROI: {roi_path.resolve()}",
            flush=True,
        )
        cenas = filtrar_cenas_selecionadas(cenas, roi)
        print(f"Imagens selecionadas para análise: {len(cenas)}", flush=True)
        if args.somente_roi:
            return 0
        if analisar_pastagens:
            from .mapbiomas import obter_mapbiomas
            from .pastagens import processar_pastagens

            caminho_pastagem = args.pastagens
            caminho_vigor = args.vigor_pastagens
            ano_camada = args.ano_camada_pastagens
            if args.baixar_mapbiomas is not None:
                caminho_pastagem, caminho_vigor = obter_mapbiomas(
                    delimitacao_cenas(cenas) if imagem_inteira else roi,
                    args.baixar_mapbiomas,
                    args.entrada / "mapbiomas",
                )
                ano_camada = args.baixar_mapbiomas
                if args.limites_vigor_ndvi is not None:
                    caminho_vigor = None
            if ano_camada is not None and any(
                int(cena["data"][:4]) != ano_camada for cena in cenas
            ):
                print(
                    f"Pastagens: camada de referência de {ano_camada}; há cenas de outros anos.",
                    flush=True,
                )
            processar_pastagens(
                cenas,
                roi,
                caminho_pastagem,
                caminho_vigor,
                destino=args.saida
                / ("pastagens_imagem_completa" if imagem_inteira else "pastagens"),
                codigo_pastagem=args.codigo_pastagem,
                limites_ndvi=args.limites_vigor_ndvi,
                ano_camada=ano_camada,
                L=args.L,
                caminho_mde=args.mde,
            )
            if args.somente_pastagens:
                return 0
        destino = args.saida / ("imagem_completa" if imagem_inteira else "roi")
        registros = processar_todas_cenas(
            cenas, roi, destino, L=args.L, caminho_mde=args.mde
        )
        if not args.sem_timelapse:
            frames, resumo, grade = preparar_frames(
                cenas,
                None if imagem_inteira else roi,
                tamanho=args.tamanho_frame,
                L=args.L,
            )
            montar_timelapse(cenas, frames, destino / "timelapse", grade)
            exportar_estatisticas(
                resumo, destino / "estatisticas_temporais_grade_reduzida.csv"
            )
        salvar_relatorio_geral(
            cenas,
            registros,
            destino,
            incluir_timelapse=not args.sem_timelapse,
            imagem_inteira=imagem_inteira,
        )
        print(
            f"Concluído: {len(cenas)} cenas, {len(registros)} blocos estatísticos.",
            flush=True,
        )
        print(f"Relatório PDF: {(destino / 'relatorio.pdf').resolve()}", flush=True)
        if args.mde is None:
            print(
                "Albedo da superfície pendente: informe --mde quando tiver o raster de elevação."
            )
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Erro: {exc}", flush=True)
        return 1
