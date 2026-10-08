# Análise Landsat por ROI

Projeto Python que processa as cenas escolhidas de `entrada/` na mesma área de interesse (ROI). Calcula reflectância TOA, albedos, índices de vegetação, emissividade, temperatura e componentes do saldo de radiação; gera estatísticas, mapas, histogramas, relatório interpretativo em PDF e time lapse. Os produtos dependem de B10, MDE e temperatura do ar disponíveis. Os relatórios HTML continuam disponíveis para navegar pelos arquivos.

## Executar

### Abrir como aplicativo (sem terminal)

Dê duplo clique em **Abrir Evapo.lnk** na pasta do projeto. O atalho abre o ambiente Python do projeto e a janela Evapo, sem console. `Abrir Evapo.vbs` é uma alternativa. As dependências já instaladas em `.venv` são usadas pelo aplicativo.

A interface usa **CustomTkinter**, com imagens, área e análise em um painel contínuo à esquerda. O botão de processamento permanece acessível no rodapé desse painel. As ferramentas de consulta, movimento e desenho ficam acima do mapa. Ao atualizar o código, feche a janela antiga e abra novamente pelo atalho.

O aplicativo começa sem pasta de imagens aberta, com lista de datas e mapa vazios. Use **Abrir pasta de imagens…**, **Abrir projeto** ou **Recuperar última sessão** para abrir os dados explicitamente. Mesmo após abrir uma pasta ou projeto, clique em uma data para carregar a vista do mapa. **Novo projeto** também começa sem imagens e não herda a pasta anterior.

Na mesma janela você pode:

- Abrir a pasta de entrada, escolher a pasta de saída e informar um MDE.
- Marcar as datas que entram na análise e alternar a imagem exibida com os botões de data ou Anterior/Próxima.
- Escolher RGB, NDVI, SAVI, IAF, albedos TOA/superfície, emissividade, temperatura e produtos de radiação disponíveis.
- Desenhar retângulo, círculo ou polígono diretamente no mapa, abrir uma ROI salva ou selecionar **Imagem inteira**.
- Usar a roda ou os botões de zoom e arrastar no modo **Mover**. Ao aproximar, a vista é relida e os pixels ficam visíveis na resolução original.
- Selecionar **Consultar** e clicar: o painel mostra os valores originais do pixel, linha/coluna, coordenadas, QA e identificação de água. Não consulta um PNG nem o valor de uma prévia reduzida.
- Clicar em **Mínimo/Máximo**: pesquisa os pixels nativos de toda a área escolhida e aproxima a vista no extremo. A busca considera a ROI inteira ou a cena inteira, independentemente do zoom atual.
- Processar as datas marcadas, acompanhar as mensagens dentro da janela e abrir relatórios/resultados. A opção de pastagens obtém as camadas MapBiomas do ano selecionado e mantém a análise adicional.

Antes de processar, confira no painel lateral as imagens marcadas, a área, o MDE e o destino. A seleção é salva automaticamente ao processar; sem desenho, usa a imagem inteira.

Ao concluir, o aplicativo abre a aba **Resultados** automaticamente. O painel esquerdo de configuração aparece somente na guia **Mapa**. Em Resultados, escolha a análise, data, produto e vigor: o mapa e o histograma são atualizados juntos, ajustados ao espaço disponível. **Tabela de estatísticas** abre a tabela em uma janela modal; **Ver todos na tabela** lista todos os registros da análise. Selecione uma linha e use **Ver resultado selecionado** para voltar às figuras. Em **Time lapse**, clique em **Reproduzir** para carregar a animação; ao sair dessa visualização, ela é parada e fechada. Resultados exibidos pertencem à execução salva escolhida, não a alterações ainda não processadas.

### Projetos, histórico, notas e exportações

Na aba **Resultados**, clique no mapa para consultar o valor do pixel processado,
sua linha e coluna. **Dados do pixel** mostra coordenadas e todos os produtos da
mesma célula. A consulta lê os GeoTIFFs em `<análise>/<data>/rasters/`, na grade
nativa e sem recalcular valores; nas pastagens, respeita a classe de vigor
selecionada. A prévia pode ser reduzida, mas a consulta usa a célula original.
Novas execuções também guardam as frequências exatas dos histogramas em JSON.
Execuções antigas continuam exibindo seus PNGs; é necessário processar novamente
para habilitar a consulta dos pixels. A tabela modal tem ordenação por coluna,
datas em dia/mês/ano, números formatados e todas as estatísticas nos detalhes.

**Máscara de pastagem** é um produto separado na lista e usa `classes_vigor.tif`
da execução escolhida: **1 = baixo**, **2 = médio**, **3 = alto vigor**, com as
cores da [legenda do MapBiomas](https://brasil.mapbiomas.org/iniciativas-e-produtos/cobertura-e-uso-da-terra/pastagem/condicao-de-vigor/).
O mapa conserva o fundo 0 (fora das pastagens), o código interno 4 (pastagem sem
vigor classificado) e NoData; esses valores não viram níveis de vigor. O histograma
mostra os três níveis e informa separadamente a quantidade sem vigor conhecido.
Nos demais produtos, **Aplicar máscara de pastagem** restringe a imagem, o
histograma e a consulta por clique às pastagens com vigor classificado (1, 2 e 3).
Desmarque para visualizar a área completa. Nas análises por vigor, escolha
**Todos** para todos os níveis de vigor
ou uma classe específica. Os histogramas contam os pixels nativos, não a prévia.
A tabela continua mostrando as estatísticas salvas da análise. A máscara também
pode ser usada nos produtos da análise geral da mesma execução, quando as grades
coincidem. Execuções antigas permitem ver a máscara já salva; para integrar a
máscara a outros produtos, é preciso ter os rasters numéricos desses produtos.

No menu **Projeto…**, use **Novo projeto**, **Abrir projeto**, **Salvar projeto** e **Salvar projeto como…**. O botão **Salvar** e `Ctrl+S` salvam o projeto atual. O arquivo `.evapo.json` guarda a ROI, as imagens marcadas, o MDE, as opções de análise, a vista, as notas, o histórico de edição e as referências às execuções. Os rasters são referenciados pelos caminhos e permanecem nos arquivos de entrada; o projeto não incorpora uma cópia deles.

**Desfazer** (`Ctrl+Z`) e **Refazer** (`Ctrl+Y`) recuperam recortes, seleção de imagens, configurações e notas. Um novo desenho não substitui um arquivo de ROI no disco. **Usar a imagem inteira** também pode ser desfeito. Na aba **Notas**, escreva livremente ou use **Nova nota** para inserir uma referência à imagem e ao último pixel consultado. As notas fazem parte do projeto.

As edições geram uma recuperação automática em `projetos/<id>/recuperacao.evapo.json`. Para restaurar a última sessão, use **Projeto… → Recuperar última sessão**; ela não é aberta na inicialização. Abrir e fechar o aplicativo vazio preserva a recuperação anterior. Ao trocar de projeto ou fechar, a janela permite salvar o documento, continuar sem salvar ou cancelar. A recuperação não substitui o uso de **Salvar** para criar um arquivo de projeto identificado.

Cada processamento cria uma pasta nova em `projetos/<id>/resultados/execucoes/<data_hora_id>/`, ou em `<destino escolhido>/execucoes/`. Inclui uma cópia da configuração usada e mantém os resultados anteriores. Na aba **Resultados**, escolha a **Execução salva** para consultar uma análise antiga; **Restaurar recorte** recupera a configuração inteira dessa execução para editar e processar novamente. **Salvar como** cria um projeto separado para novas execuções e mantém as referências aos resultados anteriores. Os arquivos antigos em `saida/` são preservados; referências às execuções anteriores permanecem nos projetos salvos e na recuperação da última sessão.

No menu **Exportar…**:

- **Relatório interpretativo PDF:** gera um documento com síntese dos resultados, comparação temporal, fórmulas, fundamentação teórica, interpretação por data e produto, referências e anexo de mapas/histogramas. Também funciona para análises antigas com CSV, sem recalcular rasters. O botão **Exportar relatório PDF** fica na aba Resultados.
- **Vista atual em PNG:** salva o mapa exibido, com o zoom, o contorno e a escala atuais, a 200 dpi. É a vista da tela; use os mapas processados para exportar a análise de toda a área.
- **Todas as imagens PNG:** copia todos os mapas e histogramas de todas as datas e classes da análise selecionada para uma subpasta nova no destino escolhido.
- **Relatório completo ZIP:** inclui os PDFs existentes, HTML, figuras, tabelas CSV, animações, documento de projeto e notas. Esta exportação usa a execução e a análise escolhidas em **Resultados**.

Cada novo processamento gera `relatorio.pdf` na pasta da análise geral e, quando solicitada, na pasta da análise das pastagens. Os textos interpretativos usam as estatísticas salvas e as fórmulas do projeto, sem consultas à internet durante a geração. As referências incluem as aulas fornecidas, os modelos ERDAS, USGS, Huete (SAVI), o manual SEBAL, Ke et al. e MapBiomas. O PDF distingue observações de hipóteses e explica os efeitos das máscaras, da reflectância TOA, da calibração do IAF e da referência anual de vigor. Não atribui classes universais de vigor nem calcula evapotranspiração a partir desses índices.

Atalhos adicionais: `Ctrl+N` cria um projeto, `Ctrl+O` abre e `Ctrl+Shift+S` salva como.

A visão geral pode usar amostragem para caber na tela. Ela não altera os valores do raster; a consulta e a busca de extremos sempre usam a grade nativa. Água com NDVI negativo permanece disponível. Ao aproximar o pixel mínimo, sua cor e valor podem ser conferidos diretamente.

Durante zoom e deslocamento, o mapa já carregado é reaproveitado. Depois que o movimento para, o sistema carrega detalhe apenas se a área ou a resolução exigirem. Até três vistas ficam em memória, e só uma leitura do mapa roda por vez; pedidos intermediários são substituídos pelo mais recente. A camada e a escala de cores permanecem na janela durante a navegação.

No arrasto, novas leituras aguardam o botão do mouse ser solto. RGB, NDVI,
SAVI, IAF e albedo TOA usam uma leitura óptica que dispensa B10 e MDE.
Vistas concluídas durante o movimento também podem ser reutilizadas pelo cache.
O desenho amostra os dados antes de aplicar as cores e reaproveita a imagem
exibida quando ela já atende à vista. Consultas de pixels e buscas de extremos
continuam usando os valores nativos e todos os produtos disponíveis.

Para medir o desempenho com as imagens locais, execute
`.venv\Scripts\python.exe scripts\benchmark_mapa.py`. O comando compara a
leitura completa com a óptica, o tempo de desenho e o acesso ao cache, sem
abrir a interface nem modificar as imagens. Os tempos dependem da cena,
do armazenamento e do tamanho da janela; o teste de desenho usa um canvas
de 900 × 700 pixels e não inclui a transferência para a janela Tk.

O processamento roda em outro processo e o mapa continua disponível. Fechar durante o processamento pergunta se deseja encerrá-lo. Os relatórios, estatísticas, mapas, histogramas e time lapse continuam sendo gerados pelas mesmas rotinas do projeto.

### Modelos das aulas 5 e 6

Os dois albedos são **albedo no topo da atmosfera (TOA ou planetário)** e
**albedo da superfície (corrigido)**. O segundo exige um MDE em metros,
selecionado em **Modelo de elevação…**. Um modelo de cálculo não substitui
esse raster de altitude. O albedo mantém os pesos e os limites dos arquivos
`.gmd` fornecidos, incluindo o piso 0,00001 no albedo da superfície; a Aula 6
mostra uma variante com piso zero.

Os PDFs `Aula5_22_09_26.pdf` e `Aula6_29_09_26.pdf` acrescentam proporção
de vegetação, emissividade, radiância B10, temperatura de brilho, temperatura
da superfície, transmissividade, emissividade atmosférica, radiação de onda
curta incidente, onda longa emitida/incidente e saldo de radiação. Esses
produtos entram nos mapas, consultas de pixels, estatísticas, relatórios,
análise de pastagens e animações da análise geral, conforme os dados disponíveis.

Os coeficientes de radiância, K1, K2, elevação solar e distância Terra–Sol
vêm do MTL de cada cena; valores do exemplo de aula não são reutilizados em
outras aquisições. A temperatura de brilho permanece em Kelvin. A temperatura
da superfície usa `BT_K / (1 + (10,895e-6 * BT_K / 1,438e-2) * ln(epsilon))`
e só depois é convertida para °C. Isso corrige a mistura de Celsius e
micrômetros na expressão do slide, seguindo a
[formulação com Kelvin](https://www.mdpi.com/2072-4292/8/5/413).
A emissividade segue a expressão executável da Aula 6, p. 5: solo 0,966;
mistura `0,973*Pv + 0,966*(1-Pv) + 0,005`; vegetação 0,978.
O texto dos slides diverge dessa expressão, inclusive para água; esta versão
registra a escolha no relatório e não introduz um valor alternativo para água.

Para onda longa incidente e saldo de radiação, informe **Temperatura do ar
(°C)** na interface, ou `--temperatura-ar 25` no terminal. Esse valor é aplicado
a todas as datas selecionadas e fica salvo no projeto e no manifesto da
execução. Para temperaturas diferentes, processe cada data com o valor
correspondente. Sem B10, MDE ou temperatura do ar, apenas os produtos
dependentes ficam pendentes; a aplicação não presume os dados ausentes.
Temperatura de superfície é uma estimativa por emissividade, sem correção por
perfil atmosférico, e não o produto oficial USGS Level-2. As radiações são
instantâneas em W/m²; não representam totais diários nem evapotranspiração.

### Executar pelo terminal (opcional)

Abra o terminal na pasta do projeto:

```powershell
uv sync
uv run evapo
```

Se não existir uma seleção salva, abre uma janela. Marque as datas desejadas e clique em **Continuar**: com desenho, analisa a ROI; sem desenho, analisa a imagem inteira de cada data. Todas as datas começam marcadas. A escolha da área e das imagens fica salva em `saida/roi.geojson` e é reutilizada nas próximas execuções. Para voltar à imagem inteira quando houver um contorno salvo, abra com `--editar-roi`, clique em **Limpar desenho** e depois em **Continuar**.

Resultados por ROI ficam em `saida/roi/`; resultados sem recorte ficam em `saida/imagem_completa/`. No modo de imagem inteira, cada cena usa toda a sua grade nativa, incluindo as bordas sem dados no denominador da cobertura. QA e NoData continuam excluídos das contas. O time lapse usa uma grade que abrange a extensão de todas as datas selecionadas.

Abra `saida/roi/relatorio.html` no navegador: ele contém a comparação entre datas e links para os relatórios individuais, CSV consolidado e time lapse. Funciona localmente, sem Jupyter.

Também é possível executar com `uv run python -m evapo`.

### Comandos úteis

```powershell
# Editar a ROI ou a escolha das imagens e processar as datas marcadas
uv run evapo --editar-roi

# Apenas desenhar/salvar a ROI
uv run evapo --editar-roi --somente-roi

# Processar uma ROI existente, sem abrir a janela
uv run evapo --sem-interface

# Usar a imagem inteira mesmo havendo ROI salva, sem alterar o desenho salvo
uv run evapo --imagem-inteira

# Escolher outra ROI e separar os resultados
uv run evapo --roi "minha_area.geojson" --saida "saida/analise_2" --sem-interface

# Informar o modelo de elevação quando estiver disponível
uv run evapo --mde "entrada/srtm.tif"

# Gerar estatísticas e figuras, sem animações
uv run evapo --sem-timelapse

# Ver todas as opções
uv run evapo --help
```

`--entrada` altera a pasta das cenas; `--referencia` escolhe o empilhamento exibido no seletor; `--L` configura o SAVI (padrão 0,5); `--tamanho-frame` limita o maior lado da grade temporal (padrão 900). Caminhos relativos são resolvidos a partir da pasta atual. Para pastas com espaços, use aspas.

Com `--sem-interface`, se não existir a seleção padrão, usa a imagem inteira. Se você informar explicitamente `--roi` com um arquivo inexistente, informa o erro para evitar ignorar um caminho digitado errado. Fechar a janela ou clicar em Cancelar continua cancelando o processamento.

## Organização dos arquivos

O código está em `src/evapo/`, separado por responsabilidade:

```text
src/evapo/
├── cli.py           # Comando evapo e opções do terminal
├── __main__.py      # Entrada para python -m evapo
├── interface/       # Janela, controles, resultados e ações de projeto
├── mapa/            # Navegação, cache, leitura de vistas e seleção de ROI
├── calculos/        # Fórmulas, produtos, estatísticas e classificação de vigor
├── dados/           # Metadados, projetos, geometrias, camadas e rasters
├── analises/        # Processamento das cenas, pastagens e time lapse
└── relatorios/      # HTML, PDF, interpretação, figuras e exportações
```

`tests/` reúne os testes e `scripts/` contém ferramentas de medição.
`Abrir Evapo.vbs` e `abrir_evapo.pyw` permanecem na raiz para iniciar a janela.
Os módulos usam imports explícitos, como `evapo.mapa.leitura` e
`evapo.interface.sistema`. Os comandos `evapo` e `python -m evapo` continuam
disponíveis; o seletor isolado usa `python -m evapo.mapa.roi`.

Os caminhos abaixo são relativos a `src/evapo/`. Cada arquivo tem uma descrição no início:

| Arquivo | O que faz |
|---|---|
| `__init__.py` | Identifica o pacote Python. |
| `__main__.py` | Permite executar com `python -m evapo`. |
| `cli.py` | Lê as opções do terminal e coordena o fluxo completo. |
| `dados/metadados.py` | Lê MTL JSON/TXT e descobre/ordena as cenas pela data de aquisição. |
| `calculos/reflectancia.py` | Converte DN para reflectância TOA e aplica as máscaras QA por banda. |
| `calculos/indices.py` | Calcula NDVI, SAVI e IAF. |
| `calculos/albedo.py` | Calcula albedo TOA, transmissividade e correção do albedo da superfície. |
| `calculos/energia.py` | Calcula emissividade, temperatura e componentes do saldo de radiação. |
| `calculos/produtos.py` | Define nomes, unidades, escalas e dependências dos produtos. |
| `mapa/roi.py` | Abre o seletor de formas, valida a geometria e salva/carrega GeoJSON. |
| `dados/area.py` | Distingue ROI de imagem inteira e delimita a região de download das camadas. |
| `interface/sistema.py` | Janela integrada de entrada, ROI, mapa, consulta de pixel e processamento. |
| `interface/layout.py` | Organiza e estiliza os controles com CustomTkinter. |
| `dados/projetos.py` | Guarda documentos de projeto, histórico de edição e configurações por execução. |
| `dados/rasters_resultados.py` | Salva e consulta rasters numéricos e histogramas dos resultados. |
| `interface/acoes_projeto.py` | Liga projetos, recuperação automática, desfazer/refazer, notas e exportações à janela. |
| `relatorios/exportacoes.py` | Exporta relatórios completos em ZIP e figuras PNG sem substituir análises anteriores. |
| `interface/resultados.py` | Exibe tabelas filtráveis, estatísticas completas, mapas, histogramas e time lapse na janela. |
| `relatorios/pdf.py` | Gera o PDF interpretativo com tabelas, teoria, referências e figuras dos resultados salvos. |
| `relatorios/interpretacao.py` | Interpreta estatísticas e diferenças temporais, com regras descritivas baseadas na teoria e nos métodos implementados. |
| `mapa/cache_vistas.py` | Reaproveita vistas compatíveis com a área e a resolução do mapa. |
| `mapa/leitura.py` | Lê a vista em blocos, consulta pixels nativos e localiza extremos. |
| `dados/geometria.py` | Verifica se os lados do polígono se cruzam e se o desenho tem área. |
| `mapa/navegacao.py` | Controla zoom, deslocamento do mapa e retorno à visão inicial. |
| `mapa/previas.py` | Prepara as imagens RGB das datas na mesma grade e guarda as prévias para o slider. |
| `dados/selecao.py` | Identifica as cenas e filtra as imagens marcadas na ROI. |
| `dados/mapbiomas.py` | Obtém recortes públicos de cobertura e vigor anual dentro da ROI. |
| `dados/camadas.py` | Alinha raster/vetor à cena e exporta máscaras, GeoJSON e shapefile. |
| `calculos/vigor.py` | Separa baixo, moderado e alto vigor exclusivamente na pastagem. |
| `analises/pastagens.py` | Gera a análise adicional dos parâmetros por classe e data. |
| `relatorios/pastagens.py` | Monta relatórios próprios das pastagens e das classes de vigor. |
| `analises/processamento.py` | Recorta e processa a ROI em resolução nativa para cada cena. |
| `calculos/estatisticas.py` | Calcula estatísticas descritivas exatas e exporta CSV/tabelas HTML. |
| `relatorios/plots.py` | Salva mapas e histogramas individuais em PNG. |
| `analises/timelapse.py` | Alinha as datas na mesma grade e gera frames, GIFs e HTML interativo. |
| `relatorios/html.py` | Monta os relatórios HTML de cada data e o relatório geral. |

`pyproject.toml` define dependências e o comando `evapo`; `uv.lock` registra as versões. `tests/test_calculos.py` verifica fórmulas, QA, geometria e estatísticas da ROI. `tests/test_navegacao.py` verifica zoom, pan e preservação do desenho. `entrada/` contém os rasters, `modelos/` contém os modelos ERDAS e PDFs e `saida/` recebe os resultados.

## Entradas e ROI

Cada cena deve conter um empilhamento DN de sete bandas, na ordem B1 a B7, com nome contendo `Bandas_Empilhadas`, além de MTL JSON ou TXT, QA_PIXEL e QA_RADSAT na mesma pasta. As cinco cenas atuais são ordenadas por aquisição: 16/06/2025, 18/07/2025, 25/12/2025, 29/07/2026 e 30/08/2026.

No seletor:

- **Slider Data:** alterna as imagens em ordem de aquisição, mostrando data e satélite. A troca preserva o zoom, o pan e o desenho da ROI, pois todas as prévias usam as mesmas coordenadas. A opção `--referencia` escolhe a data inicialmente exibida.
- **Anterior / Próxima:** volta ou avança uma imagem, junto com o slider. Os botões param na primeira e na última data.
- **Usar na análise:** marque as datas que entram nas estatísticas, mapas, histogramas, relatórios e time lapse. É necessário marcar pelo menos uma. Imagens desmarcadas continuam disponíveis para comparação no seletor.

- **Zoom + / Zoom −:** aproxima ou afasta a vista. A roda do mouse também dá zoom, centrado na posição do cursor.
- **Mover:** permite arrastar o mapa com o botão esquerdo. O botão do meio permite mover temporariamente em qualquer modo.
- **Desenhar:** volta à seleção da ROI após navegar. O desenho existente é preservado durante o zoom e o deslocamento.
- **Ver tudo:** restaura a visão inicial da imagem sem apagar a ROI.

- **Retângulo:** arraste sobre a imagem; segure Shift para um quadrado.
- **Círculo:** arraste uma caixa; o contorno vermelho é o círculo inscrito, com raio em metros.
- **Polígono:** clique nos vértices e no primeiro vértice para fechar; ajuste os vértices se necessário.

Confira o contorno vermelho antes de continuar. Sem contorno, usa a imagem inteira. Fechar ou cancelar interrompe a seleção sem substituir a configuração anterior. Desenhos sem área, com vértices repetidos ou cruzamentos são rejeitados.

Use o slider ou os botões para comparar regiões cobertas por nuvens com datas de melhor visibilidade. Cinza indica pixels excluídos pelas máscaras QA ou sem cobertura. O percentual mostrado descreve a prévia inteira, incluindo suas bordas sem dados, e não a cobertura da ROI ou do zoom atual. A data exibida ao salvar é registrada como imagem de referência. As cenas marcadas são processadas na mesma ROI, com suas próprias máscaras de nuvens e sombras.

A seleção fica salva no GeoJSON e também é respeitada com `--sem-interface`. Use `--editar-roi` para alterá-la: a janela recupera o contorno e as marcações anteriores, permitindo trocar apenas as imagens. ROIs antigas sem seleção registrada usam todas as cenas.

## Como ler os cálculos no código

As fórmulas são escritas em passos separados, com nomes como `altitude`, `transmissividade`, `numerador`, `denominador` e `pixels_validos`. Os comentários explicam as regras físicas e o motivo das exclusões.

Uma imagem é uma tabela de pixels. Os arrays NumPy permitem aplicar a mesma conta a todos eles de uma vez. Uma **máscara** é uma tabela de `True` e `False` que indica quais pixels podem participar do cálculo:

- `np.isfinite(valores)` indica onde existe um número, excluindo `NaN` e infinito.
- `pixels_validos &= condicao` mantém somente os pixels que também atendem à nova condição.
- `resultado[pixels_validos]` seleciona apenas os pixels válidos.
- `NaN` significa resultado ausente; não representa o número zero.

Por exemplo, `calcular_transmissividade` primeiro calcula a fórmula, depois verifica separadamente se a altitude é conhecida e se a transmissividade está entre zero (exclusivo) e um (inclusive). Por fim, copia os valores aprovados para o resultado e mantém os demais como `NaN`.

A ROI é salva em GeoJSON WGS84 e reprojetada para cada cena. São considerados os centros dos pixels dentro do desenho. Pixels fora do círculo/polígono não entram nas estatísticas nem no denominador da cobertura. Uma área que não contenha centros de pixels Landsat precisa ser ampliada.

## Resultados

Cada pasta `saida/roi/AAAA-MM-DD/` contém RGB, mapas e histogramas de albedo TOA, NDVI, SAVI e IAF, `estatisticas.csv` e `relatorio.html`. Se houver MDE, inclui também albedo da superfície.

Na pasta `saida/roi/`:

- `relatorio.html`: resumo comparativo e acesso a todas as datas.
- `relatorio.pdf`: relatório interpretativo consolidado, com fundamentação teórica, referências e figuras.
- `estatisticas_todas_cenas_roi.csv`: estatísticas integrais, em resolução nativa.
- `manifesto_roi.json`: ROI, grades e parâmetros usados.
- `timelapse/`: GIFs dos cinco produtos, PNGs por data, manifesto e `timelapse_interativo.html`.
- `estatisticas_temporais_grade_reduzida.csv`: estatísticas da grade de visualização.

As tabelas incluem pixels válidos/ausentes, cobertura, média, mediana, desvio padrão e variância populacionais, extremos, amplitude, quartis, percentis 5 e 95 e intervalo interquartil. Os percentis da análise nativa são exatos. Se uma data/produto não tiver pixels válidos após QA, o relatório indica isso e a data permanece nos resultados.

As animações usam a mesma grade geográfica, ROI, escalas de cores e ajuste RGB entre datas. Cinza indica dados ausentes. Cada frame permanece o mesmo tempo na tela, apesar dos intervalos irregulares entre aquisições. A grade temporal não amplia artificialmente a resolução nativa em ROIs pequenas.

Cada execução substitui os resultados nos mesmos caminhos. O relatório e as animações refletem a seleção atual; pastas de datas geradas em execuções anteriores permanecem no disco. Use `--saida` para separar análises. Os arquivos anteriores em `saida/figuras/` e `saida/timelapse/` pertencem à análise das cenas completas, anterior à ROI.

## Método

### Análise adicional das pastagens

Os resultados gerais da ROI continuam disponíveis. A análise de pastagens tem sua própria pasta, `saida/pastagens/`, e respeita a mesma ROI e as imagens marcadas no seletor.

Sem ROI, a máscara de pastagem é aplicada à imagem inteira e a nova análise fica em `saida/pastagens_imagem_completa/`. O download MapBiomas abrange todas as cenas marcadas. Para esse modo, acrescente `--imagem-inteira` ao comando abaixo; recortes baixados anteriormente para uma ROI pequena não cobrem toda a cena.

Para obter os dados públicos do MapBiomas, gerar os polígonos e analisar somente as pastagens, preservando os arquivos já produzidos:

```powershell
uv run evapo --baixar-mapbiomas 2025 --somente-pastagens --sem-interface
```

O programa lê por HTTP somente os blocos da região da ROI. Salva os recortes em `entrada/mapbiomas/colecao11_ANO_IDENTIFICADOR/`, com fonte, ano e geometria. Pode reutilizar o recorte da mesma ROI em outra execução. Downloads exigem internet; uma ROI diferente recebe outro identificador.

A [Coleção 11 consultada](https://brasil.mapbiomas.org/downloads/mapas-para-download-geotiff/) disponibiliza cobertura e vigor até **2025**. A [classe de pastagem](https://brasil.mapbiomas.org/iniciativas-e-produtos/cobertura-e-uso-da-terra/pastagem/pastagem/) tem código **15**. O [produto anual de condição de vigor](https://brasil.mapbiomas.org/iniciativas-e-produtos/cobertura-e-uso-da-terra/pastagem/condicao-de-vigor/) fornece **1 = baixo**, **2 = médio**, **3 = alto**; o relatório usa “moderado” para o código 2. Seu método usa séries temporais MODIS/EVI. As classes anuais são uma estratificação espacial de referência, enquanto os parâmetros Landsat são calculados separadamente em cada aquisição. Assim, o vigor anual não é uma classificação do NDVI instantâneo de cada cena.

No comando acima, a máscara e as classes de **2025** também são aplicadas às cenas de **2026**. O relatório registra essa diferença: isso não confirma a permanência da pastagem ou do vigor em 2026. Para analisar outro ano de referência, informe-o explicitamente; os anos aceitos pelo download de vigor são 2000–2025. Para análises com diferentes referências anuais, use execuções e pastas `--saida` separadas.

Também pode usar arquivos locais:

```powershell
# Raster de cobertura: mantém somente o código 15; vigor anual com códigos 1, 2 e 3
uv run evapo --pastagens "entrada/mapa_cobertura_2025.tif" --vigor-pastagens "entrada/mapa_vigor_2025.tif" --ano-camada-pastagens 2025 --somente-pastagens --sem-interface

# Shapefile contendo exclusivamente os polígonos de pastagem; mantenha SHP/SHX/DBF/PRJ juntos
uv run evapo --pastagens "entrada/pastagens.shp" --vigor-pastagens "entrada/mapa_vigor_2025.tif" --ano-camada-pastagens 2025 --somente-pastagens --sem-interface
```

GeoJSON de pastagens em WGS84 também é aceito. Vetores são considerados uma delimitação completa de pastagens na área; não forneça uma camada de todos os usos sem filtrar. Rasters precisam ter uma única banda, um ano e CRS. Para máscara raster binária, use `--codigo-pastagem 1`. A reprojeção categórica usa vizinho mais próximo e a seleção usa os centros dos pixels.

Caso o orientador defina dois limites de NDVI, é possível classificar o vigor em **cada cena**, em vez de usar o vigor anual. Não há limites automáticos ou universais no programa. Exemplo de chamada PowerShell com os limites que você definir:

```powershell
# Defina $limiteBaixo e $limiteAlto com os valores aprovados para seu estudo
uv run evapo --pastagens "entrada/pastagens.shp" --limites-vigor-ndvi $limiteBaixo $limiteAlto --somente-pastagens --sem-interface --saida "saida/analise_ndvi"
```

As regras são: baixo se `NDVI < limiteBaixo`; moderado se `limiteBaixo <= NDVI < limiteAlto`; alto se `NDVI >= limiteAlto`. Os limites devem satisfazer `-1 < limiteBaixo < limiteAlto < 1`. Pixels sem NDVI válido, inclusive por nuvens, ficam como **pastagem sem vigor classificado**. Essas classes não equivalem ao produto anual do MapBiomas.

A nova pasta contém:

- `relatorio.html`, `estatisticas_por_vigor.csv`, `cobertura_por_vigor.csv` e `manifesto.json` com referências, grades, ROI, cenas, limites e fontes.
- `camadas/pastagens.geojson` e `camadas/pastagens.shp`, com seus arquivos auxiliares: polígonos da máscara de referência na grade da primeira cena, preservando buracos. São derivados da camada fornecida, sem aplicar as exclusões QA da cena.
- Uma pasta por data com mapa das classes, máscara de pastagem e vigor em GeoTIFF, estatísticas e relatório.
- Pastas `baixo/`, `moderado/` e `alto/` por data, cada uma com estatísticas descritivas, mapas, histogramas e relatório de albedo TOA, NDVI, SAVI e IAF. Com `--mde`, também inclui albedo da superfície.

Na análise adicional, a máscara usada em cada parâmetro é **ROI ∩ pastagem ∩ classe de vigor ∩ pixels válidos do produto**. Cada classe tem seu próprio denominador de cobertura. Classes vazias continuam nas tabelas com zero pixels e médias ausentes (`nan`). Pastagens sem classe não são atribuídas a baixo vigor; sua área aparece no CSV de cobertura. No método NDVI, a cobertura por classe é condicionada à disponibilidade do NDVI usado para classificar.

Os GeoTIFFs de vigor usam 0 para fora da pastagem, 1/2/3 para vigor, 4 para pastagem sem classe e 255 como NoData. A máscara binária usa 0/1 e NoData 255. Áreas em hectares são medidas na grade projetada em metros, sem correção da distorção cartográfica. Não se somam linhas de ROI, pastagem e classes: elas representam conjuntos sobrepostos.

Sem `--somente-pastagens`, o programa também executa o fluxo geral já existente, com seus mapas, estatísticas e time lapse. Para manter análises adicionais de diferentes anos ou métodos, use outra pasta `--saida`.

### Cálculos Landsat

A sequência segue os modelos ERDAS fornecidos:

1. **Reflectância TOA:** `rho = (MULT * DN + ADD) / sen(elevação solar)`, com coeficientes MTL.
2. **Albedo TOA:** `0.130*rho1 + 0.115*rho2 + 0.143*rho3 + 0.180*rho4 + 0.281*rho5 + 0.108*rho6 + 0.042*rho7`, limitado a [0, 1].
3. **Transmissividade por pixel:** `tau = 0.75 + 0.00002 * altitude_m`, com elevação do MDE em metros.
4. **Albedo da superfície:** `(albedo_toa - 0.03) / tau²`.

O modelo `modelo_albedo_superficie_srtm.gmd` substitui resultados <= 0 por 0,00001 e >= 1 por 1; o código reproduz essa regra. O exemplo da aula usa zero como limite inferior. Pixels inválidos de QA/MDE permanecem como `NaN`.

NDVI usa B4/B5. SAVI usa L=0,5 por padrão. IAF usa a relação empírica `-ln((0.69-SAVI)/0.59)/0.91`, com zero para SAVI <= 0,1, saturação em 6 para SAVI >= 0,687 e exclusão de água/neve pela QA.

O MDE pode ser informado em GeoTIFF ou ERDAS IMG, incluindo `entrada/recorte_srtm_s22_w044_1arc_v3_utm_wgs84.img`. As bandas Landsat e os modelos `.gmd` não contêm a altitude do terreno. Sem `--mde`, os outros produtos são gerados normalmente e o relatório indica a pendência do albedo da superfície. A conferência computacional não substitui a validação com dados de campo; nuvens, sazonalidade e atmosfera afetam comparações.

## Verificação

```powershell
uv run python -m unittest discover -s tests -v
```

## Referências

- `modelos/modelo_albedo_toa.gmd`
- `modelos/modelo_albedo_superficie_srtm.gmd`
- `modelos/Aula3_Modelagem_08_09_26.pdf`
- `modelos/Aula4_15_09_26.pdf`
- [USGS: reflectância TOA](https://www.usgs.gov/landsat-missions/using-usgs-landsat-level-1-data-product)
- [Manual SEBAL](https://posmet.ufv.br/wp-content/uploads/2017/04/MET-479-Waters-et-al-SEBAL.pdf)
