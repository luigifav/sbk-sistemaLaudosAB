# Changelog

## 2026-05-06 - Teste E2E e ajustes do fluxo de importacao/laudo

### Adicionado

- `gerar_laudo_pdf.py`: reconstruido como modulo Python valido. O arquivo
  anterior era um zip binario contendo `servidor.py`/`migrar_banco.py` (commit
  `7f8a76f`), o que quebrava `mod.gerar_pdf(...)` em `app.py`. A nova
  implementacao usa `reportlab` e expoe `gerar_pdf(dados, destino)` com
  destino `"buffer"` retornando bytes.
- `tblIdent` (Identificacao do Processo) no PDF agora inclui:
  - Comarca
  - Estado
  - Valor da Causa (formatado em BRL via `_fmt_brl`)
  - Motivo do Ajuizamento
  - Filial, Natureza, Fase, Causa Raiz, Produto, Escritorio,
    Advogado do Autor, Pasta, Responsavel
- Secao "Resultado da Analise" no PDF: Possui Subsidio Favoravel,
  Tipo de Resultado, Estrategia, Observacoes.
- Secao "Contratos" quando o processo tiver contratos vinculados.

### Corrigido

- `sistema_laudos_v2.html` / `preencherAutomatico(p)`: nomes de campos
  alinhados com o esquema do banco retornado pelo endpoint
  `GET /api/processos/<numero>`:
  - `p.encerramento` -> `p.dt_encerramento`
  - `p.desfecho` -> `p.resultado_tipo`
  - `p.advogado_autor` -> `p.advogado`
  - `p.escritorio` -> `p.nm_escritorio`
  - `p.valor_causa` -> `p.vl_causa` (com fallback para `valor_causa`)
  - `p.cumprimento_sentenca` -> `p.fl_cumprimento_sentenca`
  - `p.possui_subsidio` -> `p.subsidios_fav`
  - `p.soma_duracao_meses` -> `p.duracao_meses`
- Pre-selecao do select `subsidiFav`: normaliza `Sim`/`Nao` (com e sem
  acento, capitalizacao do banco) para `sim`/`nao` (valores das options).
- Alerta automatico de cumprimento de sentenca passa a usar o flag correto
  `fl_cumprimento_sentenca` retornado pelo banco.

### Mapeamento de colunas da planilha (data (7).xlsx) -> banco

Confirmado por teste E2E (3 inseridos / 2 atualizados, 0 ignorados):

Identificacao e partes
- Processo -> processo
- Pasta -> pasta
- Data Entrada -> dt_inclusao
- Autor -> autor
- CPF do Adverso -> nr_cpf_cnpj
- Escritorio -> nm_escritorio
- Advogado do Autor -> advogado

Classificacao
- Produto -> produto
- Causa Raiz -> causa_raiz
- Natureza -> natureza
- Fase -> fase
- Filial -> filial
- Motivo do Ajuizamento -> motivo_ajuizamento

Localizacao
- Comarca -> comarca
- Estado -> estado

Resultado / responsavel
- Desfecho -> resultado_tipo
- Observacoes -> observacoes
- Analista Interno -> responsavel
- Possui Subsidio -> subsidios_fav

Flags e numericos (mapa COLUNAS_SEM_CAMPO em `mapa_colunas.py`)
- Ex cliente -> fl_ex_cliente
- autor contumaz -> fl_autor_contumaz
- qtde acoes -> qt_acoes
- Cumprimento de Sentenca -> fl_cumprimento_sentenca
- Processo Relevante? -> fl_relevante
- Soma de fl_falecido -> fl_falecido
- Soma de fl_adv_agressor -> fl_adv_agressor
- Soma de Duracao (Meses) -> duracao_meses
- Soma de qt_beneficio -> qt_beneficio

Textuais
- Representante, Equipe, Motivo Relevancia, Incluido Por, Categoria,
  Orgao, Juizo, Polo, Situacao -> situacao_externa, Encerramento ->
  dt_encerramento, Motivo Encerramento, CC Benner, Departamento, Divisao,
  nr_beneficio, Advogado Quarteirizado.

Monetarios (convertidos via `_limpar_monetario`)
- Valor Condenacao AX -> vl_condenacao
- Valor da causa -> vl_causa
- Valor Descontos Concedidos -> vl_descontos
- vl_beneficio -> vl_beneficio

### Fora do escopo desta entrega

- Os arquivos `data.xlsx` e `data (7).xlsx` versionados no repositorio
  estao corrompidos (texto puro com .xlsx). Para o teste E2E foram
  geradas planilhas sinteticas com os cabecalhos exatos (acentuacao
  preservada) cobrindo todas as colunas mapeadas. O importador depende
  de cabecalhos identicos (case-insensitive porem accent-sensitive).
- Importacao da planilha real `files.zip` (29 MB, xlsx valido com 26 MB
  de sheet1.xml): nao executada nesta passagem.
- Migracao automatica do schema sqlite local para incluir as novas
  colunas em bancos pre-existentes: o schema atual ja cria as colunas
  via `criar_tabelas` quando o `banco_laudos.db` e regenerado; bancos
  legados podem precisar de `migrar_banco.py`.
- Renderizacao de imagens de anexos no PDF: nao incluida na nova
  implementacao de `gerar_laudo_pdf.py`. Apenas tabelas estruturadas
  (identificacao, resultado, contratos) sao geradas.
- Integracao Postgres (Railway): testada apenas em modo SQLite local.
