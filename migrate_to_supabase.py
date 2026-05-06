"""
migrate_to_supabase.py

Migra os dados do banco SQLite local (banco_laudos.db) para um PostgreSQL
do Supabase. Reaproveita a logica de schema/mapeamento ja consolidada em
servidor.py (o arquivo exportar_banco.py do repositorio nao contem codigo
Python valido, e um XLSX, por isso a fonte autoritativa de schema usada
aqui e o servidor.py).

Uso:
    python migrate_to_supabase.py "postgresql://USER:PASS@HOST:PORT/DB"

Caracteristicas:
- Idempotente: usa ON CONFLICT DO NOTHING, pode ser executado multiplas vezes.
- Rollback por tabela: se uma tabela falhar, ela e revertida sem afetar as demais.
- Imprime contagem de registros migrados ao final.
"""

import os
import sys
import sqlite3

import psycopg2
import psycopg2.extras


DB_SQLITE = os.environ.get(
    "SQLITE_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "banco_laudos.db"),
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS processos (
    id              SERIAL PRIMARY KEY,
    processo        TEXT    NOT NULL UNIQUE,
    pasta           TEXT,
    nr_cpf_cnpj     TEXT,
    nm_escritorio   TEXT,
    dt_inclusao     TEXT,
    status          TEXT    NOT NULL DEFAULT 'em_andamento',
    responsavel     TEXT,
    dt_atualizacao  TEXT,
    dt_abertura     TEXT,
    produto         TEXT,
    autor           TEXT,
    resumo_causa    TEXT,
    causa_raiz      TEXT,
    advogado_agressor TEXT,
    nome_cliente    TEXT,
    endereco        TEXT,
    analfabeto      TEXT,
    testemunhas     TEXT,
    subsidios_fav   TEXT,
    estrategia      TEXT,
    resultado_tipo  TEXT,
    observacoes     TEXT,
    advogado            TEXT,
    motivo_ajuizamento  TEXT,
    comarca             TEXT,
    estado              TEXT,
    fase                TEXT,
    natureza            TEXT,
    adv_agressor        TEXT,
    filial              TEXT,
    validacao_contrato  TEXT,
    validacao_obs       TEXT,
    caminho_pdf         TEXT,
    ck_bo TEXT, ck_analfabeto TEXT, ck_terceiros TEXT, ck_primeira_tx TEXT,
    ck_biometria_leg TEXT, ck_biometria_ok TEXT, ck_docs_ok TEXT, ck_conta_agi TEXT,
    ck_compras TEXT, ck_compras_anormais TEXT, ck_ted TEXT, ck_saque_cartao TEXT,
    ck_uso_cartao TEXT, ck_pagamento_fatura TEXT, ck_valor_conta TEXT, ck_spc TEXT,
    ck_procuracao TEXT, ck_comprov_end TEXT, ck_outras_acoes TEXT, ck_passagens TEXT,
    appsmith_qtd TEXT, conductor_qtd TEXT, fraud_qtd TEXT, ged_qtd TEXT,
    matera_qtd TEXT, recupera_qtd TEXT, salesforce_qtd TEXT, biometria_qtd TEXT,
    fl_ex_cliente           TEXT,
    fl_autor_contumaz       TEXT,
    qt_acoes                INTEGER,
    fl_cumprimento_sentenca TEXT,
    fl_relevante            TEXT,
    fl_falecido             INTEGER,
    fl_adv_agressor         INTEGER,
    duracao_meses           INTEGER,
    qt_beneficio            INTEGER,
    representante           TEXT,
    equipe                  TEXT,
    motivo_relevancia       TEXT,
    incluido_por            TEXT,
    categoria               TEXT,
    orgao                   TEXT,
    juizo                   TEXT,
    polo                    TEXT,
    situacao_externa        TEXT,
    dt_encerramento         TEXT,
    motivo_encerramento     TEXT,
    cc_benner               TEXT,
    departamento            TEXT,
    divisao                 TEXT,
    vl_condenacao           REAL,
    vl_causa                REAL,
    vl_descontos            REAL,
    vl_beneficio            REAL,
    nr_beneficio            TEXT,
    advogado_quarteirizado  TEXT
);

CREATE TABLE IF NOT EXISTS contratos (
    id              SERIAL PRIMARY KEY,
    processo_id     INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
    nr_contrato     TEXT,
    ds_produto      TEXT,
    dt_contrato     TEXT,
    vl_contrato     TEXT,
    canal           TEXT
);

CREATE TABLE IF NOT EXISTS usuarios (
    id          SERIAL PRIMARY KEY,
    login       TEXT UNIQUE NOT NULL,
    nome        TEXT NOT NULL,
    senha_hash  TEXT NOT NULL,
    admin       INTEGER DEFAULT 0,
    ativo       INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS anexos (
    id          SERIAL PRIMARY KEY,
    processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
    app_id      TEXT NOT NULL,
    nome        TEXT NOT NULL,
    tipo        TEXT,
    caminho     TEXT NOT NULL,
    conteudo    BYTEA,
    dt_criacao  TEXT
);
COMMENT ON COLUMN anexos.conteudo IS
    'Legado: bytes do arquivo armazenados inline. Novos anexos usam Cloudflare R2 e devem deixar este campo NULL, gravando apenas a chave/URL em caminho.';

CREATE TABLE IF NOT EXISTS historico (
    id              SERIAL PRIMARY KEY,
    processo_id     INTEGER NOT NULL REFERENCES processos(id),
    usuario         TEXT,
    acao            TEXT,
    status_anterior TEXT,
    status_novo     TEXT,
    dt_registro     TEXT
);

CREATE INDEX IF NOT EXISTS idx_processos_status   ON processos(status);
CREATE INDEX IF NOT EXISTS idx_processos_processo ON processos(processo);
CREATE INDEX IF NOT EXISTS idx_contratos_proc     ON contratos(processo_id);
CREATE INDEX IF NOT EXISTS idx_anexos_proc        ON anexos(processo_id);
CREATE INDEX IF NOT EXISTS idx_historico_proc     ON historico(processo_id);
"""


TABELAS = ["processos", "contratos", "usuarios", "anexos", "historico"]

CONFLICT_KEY = {
    "processos": "(processo)",
    "contratos": "(id)",
    "usuarios":  "(login)",
    "anexos":    "(id)",
    "historico": "(id)",
}


def colunas_sqlite(sqlite_conn, tabela):
    cur = sqlite_conn.execute(f"PRAGMA table_info({tabela})")
    return [r[1] for r in cur.fetchall()]


def colunas_postgres(pg_conn, tabela):
    cur = pg_conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = %s AND table_schema = 'public'",
        (tabela,),
    )
    return [r[0] for r in cur.fetchall()]


def criar_schema(pg_conn):
    cur = pg_conn.cursor()
    cur.execute(SCHEMA_SQL)
    pg_conn.commit()
    print("Schema PostgreSQL pronto.")


def migrar_tabela(sqlite_conn, pg_conn, tabela):
    sl_cols = colunas_sqlite(sqlite_conn, tabela)
    if not sl_cols:
        print(f"  [{tabela}] tabela inexistente no SQLite, pulando.")
        return 0
    pg_cols = set(colunas_postgres(pg_conn, tabela))
    cols = [c for c in sl_cols if c in pg_cols]
    if not cols:
        print(f"  [{tabela}] sem colunas em comum, pulando.")
        return 0

    rows = sqlite_conn.execute(
        f"SELECT {', '.join(cols)} FROM {tabela}"
    ).fetchall()
    if not rows:
        print(f"  [{tabela}] 0 registros no SQLite.")
        return 0

    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    sql = (
        f"INSERT INTO {tabela} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT {CONFLICT_KEY[tabela]} DO NOTHING"
    )

    cur = pg_conn.cursor()
    inseridos = 0
    try:
        valores = [tuple(r[c] for c in cols) for r in rows]
        psycopg2.extras.execute_batch(cur, sql, valores, page_size=200)
        inseridos = cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(valores)
        pg_conn.commit()
        print(f"  [{tabela}] {len(valores)} lidos / {inseridos} inseridos (ou ja existentes).")
    except Exception as e:
        pg_conn.rollback()
        print(f"  [{tabela}] ERRO, rollback aplicado: {e}")
        return 0
    return inseridos


def reset_sequences(pg_conn):
    cur = pg_conn.cursor()
    for tabela in TABELAS:
        try:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{tabela}','id'), "
                f"COALESCE((SELECT MAX(id) FROM {tabela}), 1), true)"
            )
        except Exception as e:
            pg_conn.rollback()
            print(f"  [{tabela}] sequence nao ajustada: {e}")
    pg_conn.commit()


def main():
    if len(sys.argv) < 2:
        print('Uso: python migrate_to_supabase.py "postgresql://USER:PASS@HOST:PORT/DB"')
        sys.exit(1)

    dsn = sys.argv[1]
    if not os.path.exists(DB_SQLITE):
        print(f"SQLite nao encontrado em: {DB_SQLITE}")
        sys.exit(1)

    print(f"Origem: {DB_SQLITE}")
    print(f"Destino: {dsn.split('@')[-1] if '@' in dsn else dsn}")

    sqlite_conn = sqlite3.connect(DB_SQLITE)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg2.connect(dsn)

    try:
        criar_schema(pg_conn)
        contagens = {}
        for tabela in TABELAS:
            contagens[tabela] = migrar_tabela(sqlite_conn, pg_conn, tabela)
        reset_sequences(pg_conn)
    finally:
        sqlite_conn.close()
        pg_conn.close()

    print("\nResumo da migracao:")
    for tabela, n in contagens.items():
        print(f"  {tabela:12s} {n} registros")
    print("Concluido.")


if __name__ == "__main__":
    main()
