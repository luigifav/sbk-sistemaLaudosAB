# mapa_colunas.py
#
# Mapeamento entre colunas da planilha Excel de entrada e campos da tabela
# `processos` no banco de dados (definida em servidor.py).
#
# As chaves são os nomes das colunas exatamente como aparecem no cabeçalho da
# planilha. Os valores são os nomes dos campos correspondentes no banco.
#
# Observação: o importador normaliza os cabeçalhos para lowercase antes de
# comparar (ver post_importar_casos em servidor.py), portanto as chaves aqui
# são mantidas em case original apenas para documentação e legibilidade.
# Ao usar este mapa no importador, aplique .strip().lower() na coluna da
# planilha e .lower() nas chaves deste dicionário antes de comparar.

MAPA_PLANILHA_PARA_BANCO: dict[str, str] = {
    # Identificação do processo
    "Processo":             "processo",
    "Pasta":                "pasta",
    "Data Entrada":         "dt_inclusao",

    # Partes e representação
    "Autor":                "autor",
    "CPF do Adverso":       "nr_cpf_cnpj",
    "Escritorio":           "nm_escritorio",
    "Advogado do Autor":    "advogado",

    # Classificação
    "Produto":              "produto",
    "Causa Raiz":           "causa_raiz",
    "Natureza":             "natureza",
    "Fase":                 "fase",
    "Filial":               "filial",
    "Motivo do Ajuizamento": "motivo_ajuizamento",

    # Localização geográfica e jurisdição
    "Comarca":              "comarca",
    "Estado":               "estado",

    # Resultado / desfecho
    "Desfecho":             "resultado_tipo",
    "Observacoes":          "observacoes",

    # Responsável interno
    "Analista Interno":     "responsavel",

    # Subsídio (indica se há subsídio favorável ao banco)
    "Possui Subsídio":      "subsidios_fav",
}


# Colunas da planilha sem campo correspondente no banco atual.
# Cada entrada é uma tupla (coluna_planilha, nome_campo_sugerido).
# Os campos sugeridos devem ser adicionados via ALTER TABLE ou no CREATE TABLE.

COLUNAS_SEM_CAMPO: list[tuple[str, str]] = [
    # Flags e indicadores booleanos / numéricos
    ("Ex cliente",              "fl_ex_cliente"),          # booleano: era cliente antes
    ("autor contumaz",          "fl_autor_contumaz"),      # booleano: autor recorrente/serial
    ("qtde ações",              "qt_acoes"),               # INTEGER: quantidade de ações do autor
    ("Cumprimento de Sentença", "fl_cumprimento_sentenca"),# booleano: está em fase de cumprimento
    ("Processo Relevante?",     "fl_relevante"),           # booleano: processo marcado como relevante
    ("Soma de fl_falecido",     "fl_falecido"),            # INTEGER/booleano: autor falecido
    ("Soma de fl_adv_agressor", "fl_adv_agressor"),        # INTEGER/booleano: advogado agressor
    ("Soma de Duração (Meses)", "duracao_meses"),          # INTEGER: duração do processo em meses
    ("Soma de qt_beneficio",    "qt_beneficio"),           # INTEGER: quantidade de benefícios

    # Campos textuais sem equivalente atual
    ("Representante",           "representante"),          # TEXT: representante legal do autor
    ("Equipe",                  "equipe"),                 # TEXT: equipe responsável
    ("Motivo Relevancia",       "motivo_relevancia"),      # TEXT: motivo do destaque do processo
    ("Incluído Por",            "incluido_por"),           # TEXT: usuário que incluiu o registro
    ("Categoria",               "categoria"),              # TEXT: categoria do processo
    ("Orgao",                   "orgao"),                  # TEXT: órgão julgador (ex: TRT, TJGO)
    ("Juizo",                   "juizo"),                  # TEXT: vara/juízo específico
    ("Polo",                    "polo"),                   # TEXT: polo processual (ativo/passivo)
    ("Situacao",                "situacao_externa"),       # TEXT: situação vinda da planilha; evitar
                                                           # conflito com o campo `status` interno
    ("Encerramento",            "dt_encerramento"),        # TEXT/DATE: data de encerramento
    ("Motivo Encerramento",     "motivo_encerramento"),    # TEXT: motivo do encerramento
    ("CC Benner",               "cc_benner"),              # TEXT: código de custo no sistema Benner
    ("Departamento",            "departamento"),           # TEXT: departamento responsável
    ("Divisao",                 "divisao"),                # TEXT: divisão interna

    # Valores monetários
    ("Valor Condenação AX",     "vl_condenacao"),          # REAL: valor da condenação
    ("Valor da causa",          "vl_causa"),               # REAL: valor dado à causa
    ("Valor Descontos Concedidos", "vl_descontos"),        # REAL: descontos concedidos no acordo
    ("vl_beneficio",            "vl_beneficio"),           # REAL: valor do benefício previdenciário

    # Benefício previdenciário
    ("nr_beneficio",            "nr_beneficio"),           # TEXT: número do benefício (INSS etc.)

    # Advogado contratado externamente
    ("Advogado Quarteirizado",  "advogado_quarteirizado"), # TEXT: escritório/adv. terceirizado
]
