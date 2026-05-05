"""
exportar_banco.py
Exporta o banco SQLite local para o PostgreSQL do Railway.

Uso:
  python exportar_banco.py postgresql://usuario:senha@host:5432/banco

O DATABASE_URL completo aparece no painel do Railway em:
  Projeto > PostgreSQL > Connect > DATABASE_URL
"""
import sys
import sqlite3
import os

if len(sys.argv) < 2:
    print("Uso: python exportar_banco.py DATABASE_URL_DO_RAILWAY")
    print("Ex:  python exportar_banco.py postgresql://postgres:xxx@xxx.railway.app:5432/railway")
    sys.exit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Instalando psycopg2...")
    os.system("pip install psycopg2-binary")
    import psycopg2
    import psycopg2.extras

DB_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banco_laudos.db")
PG_URL   = sys.argv[1]

if not os.path.exists(DB_LOCAL):
    print(f"Banco local nao encontrado: {DB_LOCAL}")
    sys.exit(1)

print(f"\nConectando ao banco local: {DB_LOCAL}")
sqlite_conn = sqlite3.connect(DB_LOCAL)
sqlite_conn.row_factory = sqlite3.Row

print("Conectando ao PostgreSQL do Railway...")
pg_conn = psycopg2.connect(PG_URL)
pg_cur  = pg_conn.cursor()

# ── Criar schema no PostgreSQL ──
print("Criando tabelas no PostgreSQL...")
pg_cur.execute("""
CREATE TABLE IF NOT EXISTS usuarios (
    id         SERIAL PRIMARY KEY,
    login      TEXT UNIQUE NOT NULL,
    nome       TEXT NOT NULL,
    senha_hash TEXT NOT NULL,
    admin      INTEGER DEFAULT 0,
    ativo      INTEGER DEFAULT 1
)""")

pg_cur.execute("""
CREATE TABLE IF NOT EXISTS processos (
    id                  SERIAL PRIMARY KEY,
    processo            TEXT UNIQUE NOT NULL,
    pasta               TEXT, nr_cpf_cnpj TEXT, nm_escritorio TEXT,
    dt_inclusao         TEXT, status TEXT DEFAULT 'em_andamento',
    responsavel         TEXT, dt_atualizacao TEXT, dt_abertura TEXT,
    produto             TEXT, autor TEXT, causa_raiz TEXT,
    advogado            TEXT, motivo_ajuizamento TEXT,
    comarca             TEXT, estado TEXT, fase TEXT,
    natureza            TEXT, adv_agressor TEXT, filial TEXT,
    resumo_causa        TEXT, nome_cliente TEXT, endereco TEXT,
    analfabeto          TEXT, testemunhas TEXT,
    subsidios_fav       TEXT, estrategia TEXT, resultado_tipo TEXT,
    observacoes         TEXT,
    ck_bo TEXT, ck_analfabeto TEXT, ck_terceiros TEXT, ck_primeira_tx TEXT,
    ck_biometria_leg TEXT, ck_biometria_ok TEXT, ck_docs_ok TEXT, ck_conta_agi TEXT,
    ck_compras TEXT, ck_compras_anormais TEXT, ck_ted TEXT, ck_saque_cartao TEXT,
    ck_uso_cartao TEXT, ck_pagamento_fatura TEXT, ck_valor_conta TEXT, ck_spc TEXT,
    ck_procuracao TEXT, ck_comprov_end TEXT, ck_outras_acoes TEXT, ck_passagens TEXT,
    appsmith_qtd TEXT, conductor_qtd TEXT, fraud_qtd TEXT, ged_qtd TEXT,
    matera_qtd TEXT, recupera_qtd TEXT, salesforce_qtd TEXT, biometria_qtd TEXT
)""")

pg_cur.execute("""
CREATE TABLE IF NOT EXISTS contratos (
    id          SERIAL PRIMARY KEY,
    processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
    nr_contrato TEXT, ds_produto TEXT, dt_contrato TEXT,
    vl_contrato TEXT, canal TEXT
)""")

pg_cur.execute("""
CREATE TABLE IF NOT EXISTS historico (
    id          SERIAL PRIMARY KEY,
    processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
    usuario     TEXT, acao TEXT, status_anterior TEXT, status_novo TEXT,
    dt_registro TEXT
)""")

pg_cur.execute("""
CREATE TABLE IF NOT EXISTS anexos (
    id          SERIAL PRIMARY KEY,
    processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
    app_id      TEXT NOT NULL, nome TEXT NOT NULL,
    tipo        TEXT, caminho TEXT NOT NULL, dt_criacao TEXT
)""")

pg_conn.commit()
print("Tabelas criadas.")

# ── Migrar usuarios ──
rows = sqlite_conn.execute("SELECT login, nome, senha_hash, admin, ativo FROM usuarios").fetchall()
print(f"\nMigrando {len(rows)} usuarios...")
for r in rows:
    try:
        pg_cur.execute(
            "INSERT INTO usuarios (login, nome, senha_hash, admin, ativo) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (login) DO NOTHING",
            [r["login"], r["nome"], r["senha_hash"], r["admin"], r["ativo"]]
        )
    except Exception as e:
        print(f"  Erro usuario {r['login']}: {e}")
pg_conn.commit()
print("Usuarios migrados.")

# ── Migrar processos ──
processos = sqlite_conn.execute("SELECT * FROM processos").fetchall()
print(f"\nMigrando {len(processos)} processos (pode demorar)...")

cols_proc = [d[0] for d in sqlite_conn.execute("SELECT * FROM processos LIMIT 0").description]
id_map = {}  # sqlite_id → pg_id

for i, p in enumerate(processos):
    row = dict(p)
    sqlite_id = row.pop("id")
    cols = [c for c in cols_proc if c != "id"]
    vals = [row.get(c) for c in cols]
    placeholders = ", ".join(["%s"] * len(cols))
    col_str = ", ".join(cols)
    try:
        pg_cur.execute(
            f"INSERT INTO processos ({col_str}) VALUES ({placeholders}) "
            f"ON CONFLICT (processo) DO NOTHING RETURNING id",
            vals
        )
        result = pg_cur.fetchone()
        if result:
            id_map[sqlite_id] = result[0]
    except Exception as e:
        print(f"  Erro processo {row.get('processo','?')}: {e}")
        pg_conn.rollback()
    if (i+1) % 500 == 0:
        pg_conn.commit()
        print(f"  {i+1}/{len(processos)} processos...")

pg_conn.commit()
print(f"Processos migrados. Mapeados: {len(id_map)}")

# ── Migrar contratos ──
contratos = sqlite_conn.execute("SELECT * FROM contratos").fetchall()
print(f"\nMigrando {len(contratos)} contratos...")
for ct in contratos:
    pg_id = id_map.get(ct["processo_id"])
    if not pg_id:
        continue
    try:
        pg_cur.execute(
            "INSERT INTO contratos (processo_id, nr_contrato, ds_produto, dt_contrato, vl_contrato, canal) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            [pg_id, ct["nr_contrato"], ct["ds_produto"], ct["dt_contrato"],
             ct.get("vl_contrato"), ct.get("canal")]
        )
    except Exception as e:
        print(f"  Erro contrato: {e}")

pg_conn.commit()
print("Contratos migrados.")

sqlite_conn.close()
pg_conn.close()

print("\n" + "="*50)
print("Migracao concluida com sucesso!")
print("Agora suba o codigo para o Railway.")
print("="*50)
input("\nPressione Enter para sair...")
