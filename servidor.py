"""
servidor.py — Sistema de Laudos SBK
Uso: python servidor.py

Requisitos: pip install openpyxl
Acesse: http://localhost:8000
"""

import json
import os
import hashlib
import re
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# ── Detectar ambiente: PostgreSQL (Railway) ou SQLite (local) ──
DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES  = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    class _PGConn:
        """Wrapper que emula a interface do sqlite3 para o PostgreSQL."""
        def __init__(self, dsn):
            self._conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
            self._conn.autocommit = False

        def execute(self, sql, params=None):
            sql_pg = sql.replace("?", "%s")
            # Adaptar INSERT para retornar id
            if sql_pg.strip().upper().startswith("INSERT") and "RETURNING" not in sql_pg.upper():
                sql_pg = sql_pg.rstrip().rstrip(";") + " RETURNING id"
            cur = self._conn.cursor()
            cur.execute(sql_pg, params or [])
            cur.lastrowid = None
            if sql_pg.strip().upper().startswith("INSERT"):
                try:
                    row = cur.fetchone()
                    cur.lastrowid = row["id"] if row else None
                except Exception:
                    pass
            return _PGCursor(cur)

        def executescript(self, sql):
            cur = self._conn.cursor()
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    # Adaptar schema SQLite → PostgreSQL
                    stmt = stmt.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
                    stmt = stmt.replace("AUTOINCREMENT", "")
                    try:
                        cur.execute(stmt)
                    except Exception:
                        self._conn.rollback()
            return _PGCursor(cur)

        def commit(self):   self._conn.commit()
        def rollback(self): self._conn.rollback()
        def close(self):    self._conn.close()

    class _PGCursor:
        def __init__(self, cur): self._cur = cur
        @property
        def lastrowid(self): return self._cur.lastrowid
        @lastrowid.setter
        def lastrowid(self, v): self._cur.lastrowid = v
        def fetchone(self):
            row = self._cur.fetchone()
            if row is None: return None
            return _DictRow(dict(row))
        def fetchall(self):
            return [_DictRow(dict(r)) for r in self._cur.fetchall()]
        def __getitem__(self, key): return self._cur[key]

    class _DictRow(dict):
        """Emula sqlite3.Row — acesso por nome e por índice."""
        def __getitem__(self, key):
            if isinstance(key, int):
                return list(self.values())[key]
            return super().__getitem__(key)
        def get(self, key, default=None):
            return super().get(key, default)

# ─────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────
PORTA      = int(os.environ.get("PORT", 8080))
DIR_BASE    = os.path.dirname(os.path.abspath(__file__))
ANEXOS_DIR  = os.path.join(DIR_BASE, "anexos_laudos")
os.makedirs(ANEXOS_DIR, exist_ok=True)
DB_ARQUIVO = os.environ.get("SQLITE_DB_PATH", os.path.join(DIR_BASE, "banco_laudos.db"))

# Usuários do sistema  {login: {senha_hash, nome}}
# Para adicionar usuários: python servidor.py --adduser login senha nome
USUARIOS = {
    "teste": {
        "senha_hash": hashlib.sha256("1234".encode()).hexdigest(),
        "nome": "Teste"
    }
}


# ─────────────────────────────────────────────
# BANCO DE DADOS
# ─────────────────────────────────────────────
def conectar():
    if USE_POSTGRES:
        return _PGConn(DATABASE_URL)
    conn = sqlite3.connect(DB_ARQUIVO)
    conn.row_factory = sqlite3.Row
    return conn


def criar_tabelas():
    conn = conectar()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS processos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            processo        TEXT    NOT NULL UNIQUE,
            pasta           TEXT,
            nr_cpf_cnpj     TEXT,
            nm_escritorio   TEXT,
            dt_inclusao     TEXT,
            status          TEXT    NOT NULL DEFAULT 'em_andamento',
            responsavel     TEXT,
            dt_atualizacao  TEXT,
            dt_abertura     TEXT,
            -- campos do laudo preenchidos pelo analista
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
            -- checklist
            ck_bo TEXT, ck_analfabeto TEXT, ck_terceiros TEXT, ck_primeira_tx TEXT,
            ck_biometria_leg TEXT, ck_biometria_ok TEXT, ck_docs_ok TEXT, ck_conta_agi TEXT,
            ck_compras TEXT, ck_compras_anormais TEXT, ck_ted TEXT, ck_saque_cartao TEXT,
            ck_uso_cartao TEXT, ck_pagamento_fatura TEXT, ck_valor_conta TEXT, ck_spc TEXT,
            ck_procuracao TEXT, ck_comprov_end TEXT, ck_outras_acoes TEXT, ck_passagens TEXT,
            -- sistemas
            appsmith_qtd TEXT, conductor_qtd TEXT, fraud_qtd TEXT, ged_qtd TEXT,
            matera_qtd TEXT, recupera_qtd TEXT, salesforce_qtd TEXT, biometria_qtd TEXT
        );

        CREATE TABLE IF NOT EXISTS contratos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id     INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
            nr_contrato     TEXT,
            ds_produto      TEXT,
            dt_contrato     TEXT,
            vl_contrato     TEXT,
            canal           TEXT
        );

        CREATE TABLE IF NOT EXISTS usuarios (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            login    TEXT UNIQUE NOT NULL,
            nome     TEXT NOT NULL,
            senha_hash TEXT NOT NULL,
            admin    INTEGER DEFAULT 0,
            ativo    INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS anexos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
            app_id      TEXT NOT NULL,
            nome        TEXT NOT NULL,
            tipo        TEXT,
            caminho     TEXT NOT NULL,
            conteudo    BLOB,
            dt_criacao  TEXT
        );
        CREATE TABLE IF NOT EXISTS historico (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id     INTEGER NOT NULL REFERENCES processos(id),
            usuario         TEXT,
            acao            TEXT,
            status_anterior TEXT,
            status_novo     TEXT,
            dt_registro     TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_processos_status   ON processos(status);
        CREATE INDEX IF NOT EXISTS idx_processos_processo ON processos(processo);
        CREATE INDEX IF NOT EXISTS idx_contratos_proc     ON contratos(processo_id);
    """)
    # Migrations — adiciona colunas novas em bancos já existentes
    for col in ["autor TEXT", "dt_abertura TEXT", "adv_agressor TEXT", "motivo_ajuizamento TEXT",
                "comarca TEXT", "estado TEXT", "fase TEXT", "natureza TEXT",
                "filial TEXT", "advogado TEXT",
                "validacao_contrato TEXT", "validacao_obs TEXT"]:
        try:
            conn.execute(f"ALTER TABLE processos ADD COLUMN {col}")
        except Exception:
            pass
    try:
        conn.execute("ALTER TABLE processos ADD COLUMN testemunhas TEXT")
    except Exception:
        pass
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS anexos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
            app_id TEXT NOT NULL, nome TEXT NOT NULL,
            tipo TEXT, caminho TEXT NOT NULL, conteudo BLOB, dt_criacao TEXT
        )""")
    except Exception:
        pass
    # Migration: adicionar coluna conteudo para bancos já existentes
    conteudo_col = "conteudo BYTEA" if USE_POSTGRES else "conteudo BLOB"
    try:
        conn.execute(f"ALTER TABLE anexos ADD COLUMN {conteudo_col}")
        conn.commit()
    except Exception:
        pass
    ck_cols = [
        "ck_bo","ck_analfabeto","ck_terceiros","ck_primeira_tx",
        "ck_biometria_leg","ck_biometria_ok","ck_docs_ok","ck_conta_agi",
        "ck_compras","ck_compras_anormais","ck_ted","ck_saque_cartao",
        "ck_uso_cartao","ck_pagamento_fatura","ck_valor_conta","ck_spc",
        "ck_procuracao","ck_comprov_end","ck_outras_acoes","ck_passagens",
        "appsmith_qtd","conductor_qtd","fraud_qtd","ged_qtd",
        "matera_qtd","recupera_qtd","salesforce_qtd","biometria_qtd"
    ]
    for col in ck_cols:
        try:
            conn.execute(f"ALTER TABLE processos ADD COLUMN {col} TEXT")
        except Exception:
            pass
    try:
        conn.execute("ALTER TABLE processos ADD COLUMN caminho_pdf TEXT")
    except Exception:
        pass
    # Criar usuário padrão se banco vazio
    existing = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    if existing == 0:
        import hashlib as _hl
        conn.execute(
            "INSERT INTO usuarios (login, nome, senha_hash, admin) VALUES (?,?,?,?)",
            ["teste", "Teste", _hl.sha256("1234".encode()).hexdigest(), 1]
        )
    conn.commit()
    conn.close()
    print(f"  Banco '{DB_ARQUIVO}' pronto.")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def processo_para_dict(row, contratos=None):
    d = dict(row)
    if contratos is not None:
        d["contratos"] = contratos
    return d


def json_resp(handler, status, data):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", len(body))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def ler_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length))


# ─────────────────────────────────────────────
# ROTEADOR
# ─────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Silencia logs de arquivos estáticos, mostra só a API
        try:
            if args and isinstance(args[0], str) and "/api/" in args[0]:
                print(f"  {self.address_string()} {args[0]}")
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()



    def get_anexos(self, numero):
        """Retorna lista de anexos de um processo."""
        conn = conectar()
        proc = conn.execute("SELECT id FROM processos WHERE processo=?", [numero]).fetchone()
        if not proc:
            conn.close()
            return json_resp(self, 404, {"erro": "Processo nao encontrado"})
        rows = conn.execute(
            "SELECT id, app_id, nome, tipo FROM anexos WHERE processo_id=? ORDER BY app_id, id",
            [proc["id"]]
        ).fetchall()
        conn.close()
        json_resp(self, 200, {"anexos": [dict(r) for r in rows]})

    def get_anexo_arquivo(self, anexo_id):
        """Retorna o arquivo de um anexo pelo id."""
        conn = conectar()
        row = conn.execute("SELECT caminho, nome, tipo, conteudo FROM anexos WHERE id=?", [anexo_id]).fetchone()
        conn.close()
        if not row:
            return json_resp(self, 404, {"erro": "Anexo nao encontrado"})
        if os.path.exists(row["caminho"]):
            with open(row["caminho"], "rb") as f:
                dados = f.read()
        elif row["conteudo"]:
            dados = bytes(row["conteudo"])
        else:
            return json_resp(self, 404, {"erro": "Anexo nao encontrado"})
        tipo = row["tipo"] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", len(dados))
        self.send_header("Content-Disposition", f'inline; filename="{row["nome"]}"')
        self.end_headers()
        self.wfile.write(dados)

    def post_salvar_anexo(self, numero):
        """Salva um anexo (base64) no disco e registra no banco."""
        import base64 as _b64, uuid as _uuid
        body = ler_body(self)
        app_id = body.get("app_id", "")
        nome   = body.get("nome", "anexo")
        tipo   = body.get("tipo", "image/png")
        data   = body.get("data", "")

        if not data:
            return json_resp(self, 400, {"erro": "Dados do arquivo nao enviados"})

        conn = conectar()
        proc = conn.execute("SELECT id FROM processos WHERE processo=?", [numero]).fetchone()
        if not proc:
            conn.close()
            return json_resp(self, 404, {"erro": "Processo nao encontrado"})

        # Decodificar base64
        try:
            b64 = data.split(",", 1)[1] if "," in data else data
            raw = _b64.b64decode(b64)
        except Exception as e:
            conn.close()
            return json_resp(self, 400, {"erro": f"Erro ao decodificar: {e}"})

        # Salvar arquivo
        ext = ".png" if "png" in tipo else ".jpg" if "jp" in tipo else ".pdf"
        nome_arquivo = f"{numero.replace('/', '_')}_{app_id}_{_uuid.uuid4().hex[:8]}{ext}"
        caminho = os.path.join(ANEXOS_DIR, nome_arquivo)
        with open(caminho, "wb") as f:
            f.write(raw)

        # Registrar no banco (conteudo salvo como BLOB para persistir em ambientes efêmeros)
        cur = conn.execute(
            "INSERT INTO anexos (processo_id, app_id, nome, tipo, caminho, conteudo, dt_criacao) VALUES (?,?,?,?,?,?,?)",
            [proc["id"], app_id, nome, tipo, caminho, raw, agora()]
        )
        anexo_id = cur.lastrowid
        conn.commit()
        conn.close()
        json_resp(self, 200, {"ok": True, "id": anexo_id})

    def post_deletar_anexo(self, anexo_id):
        """Remove um anexo do disco e do banco."""
        conn = conectar()
        row = conn.execute("SELECT caminho FROM anexos WHERE id=?", [anexo_id]).fetchone()
        if row:
            try: os.unlink(row["caminho"])
            except: pass
            conn.execute("DELETE FROM anexos WHERE id=?", [anexo_id])
            conn.commit()
        conn.close()
        json_resp(self, 200, {"ok": True})


    def get_relatorio_produtividade(self):
        """Relatório de produtividade: casos concluídos com analista e data."""
        conn = conectar()
        rows = conn.execute(
            """SELECT p.processo, p.status, p.dt_atualizacao as dt_conclusao,
                      p.responsavel, p.produto, p.autor
               FROM processos p
               WHERE p.status = 'concluido'
               ORDER BY p.dt_atualizacao DESC"""
        ).fetchall()
        conn.close()
        json_resp(self, 200, {"dados": [dict(r) for r in rows]})

    def get_relatorio_faturamento(self):
        """Relatório de faturamento: casos concluídos com resultado."""
        conn = conectar()
        rows = conn.execute(
            """SELECT p.processo, p.dt_atualizacao as dt_conclusao,
                      p.resultado_tipo, p.status
               FROM processos p
               WHERE p.status = 'concluido'
               ORDER BY p.dt_atualizacao DESC"""
        ).fetchall()
        conn.close()
        json_resp(self, 200, {"dados": [dict(r) for r in rows]})

    def get_usuarios(self):
        conn = conectar()
        rows = conn.execute(
            "SELECT login, nome, admin, ativo FROM usuarios ORDER BY nome"
        ).fetchall()
        conn.close()
        json_resp(self, 200, {"usuarios": [dict(r) for r in rows]})

    def post_criar_usuario(self):
        body  = ler_body(self)
        login = body.get("login","").strip()
        nome  = body.get("nome","").strip()
        senha = body.get("senha","")
        admin = int(body.get("admin", 0))

        if not login or not nome or not senha:
            return json_resp(self, 400, {"erro": "Login, nome e senha sao obrigatorios"})

        conn = conectar()
        try:
            conn.execute(
                "INSERT INTO usuarios (login, nome, senha_hash, admin) VALUES (?,?,?,?)",
                [login, nome, hashlib.sha256(senha.encode()).hexdigest(), admin]
            )
            conn.commit()
            json_resp(self, 200, {"ok": True})
        except Exception:
            json_resp(self, 400, {"erro": f"Login ja existe: {login}"})
        finally:
            conn.close()

    def post_editar_usuario(self, login_u):
        body  = ler_body(self)
        acao  = body.get("acao","")
        conn  = conectar()
        try:
            if acao == "senha":
                nova = body.get("senha","")
                if nova:
                    conn.execute(
                        "UPDATE usuarios SET senha_hash=? WHERE login=?",
                        [hashlib.sha256(nova.encode()).hexdigest(), login_u]
                    )
            elif acao == "ativar":
                conn.execute("UPDATE usuarios SET ativo=1 WHERE login=?", [login_u])
            elif acao == "desativar":
                conn.execute("UPDATE usuarios SET ativo=0 WHERE login=?", [login_u])
            elif acao == "admin":
                conn.execute("UPDATE usuarios SET admin=? WHERE login=?",
                             [int(body.get("valor",0)), login_u])
            conn.commit()
            json_resp(self, 200, {"ok": True})
        except Exception as e:
            json_resp(self, 500, {"erro": str(e)})
        finally:
            conn.close()

    def post_mover_processo(self, numero):
        body        = ler_body(self)
        novo_status = body.get("status","")
        usuario     = body.get("usuario","sistema")
        validos     = {"pendente_validacao","em_andamento","aguardando","concluido","sem_contrato"}

        if novo_status not in validos:
            return json_resp(self, 400, {"erro": f"Status invalido: {novo_status}"})

        conn = conectar()
        proc = conn.execute(
            "SELECT id, status FROM processos WHERE processo=?", [numero]
        ).fetchone()

        if not proc:
            conn.close()
            return json_resp(self, 404, {"erro": "Processo nao encontrado"})

        conn.execute(
            """UPDATE processos
               SET status=?, responsavel=NULL, dt_abertura=NULL, dt_atualizacao=?
               WHERE processo=?""",
            [novo_status, agora(), numero]
        )
        try:
            conn.execute(
                "INSERT INTO historico (processo_id, usuario, acao) VALUES (?,?,?)",
                [proc["id"], usuario, f"movido para {novo_status}"]
            )
        except Exception:
            pass
        conn.commit()
        conn.close()
        json_resp(self, 200, {"ok": True, "processo": numero, "status": novo_status})

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"
        qs     = parse_qs(parsed.query)

        # ── API ──────────────────────────────
        if path == "/api/processos":
            self.get_processos(qs)
        elif re.match(r"^/api/processos/(.+)/pdf$", path):
            numero = re.match(r"^/api/processos/(.+)/pdf$", path).group(1)
            self.get_pdf_processo(numero)
        elif re.match(r"^/api/processos/(.+)/anexos$", path):
            numero = re.match(r"^/api/processos/(.+)/anexos$", path).group(1)
            self.get_anexos(numero)
        elif re.match(r"^/api/processos/(.+)$", path):
            numero = re.match(r"^/api/processos/(.+)$", path).group(1)
            self.get_processo(numero)
        elif path == "/api/contadores":
            self.get_contadores()
        elif path == "/api/validar-sessao":
            self.get_validar_sessao(qs)
        elif path == "/api/aguardando":
            self.get_aguardando(qs)
        elif path == "/api/analistas":
            self.get_analistas()
        elif path == "/api/admin/usuarios":
            self.get_usuarios()
        elif path == "/api/relatorios/produtividade":
            self.get_relatorio_produtividade()
        elif path == "/api/relatorios/faturamento":
            self.get_relatorio_faturamento()
        elif re.match(r"^/api/anexos/(\d+)$", path):
            anexo_id = re.match(r"^/api/anexos/(\d+)$", path).group(1)
            self.get_anexo_arquivo(int(anexo_id))

        # ── Arquivos estáticos ───────────────
        elif path == "/" or path == "/index.html":
            import os as _os
            html_name = "sistema_laudos_v2.html" if _os.path.exists(_os.path.join(DIR_BASE, "sistema_laudos_v2.html")) else "sistema_laudos_layout.html"
            self.servir_arquivo(html_name, "text/html")
        elif path.endswith(".html"):
            self.servir_arquivo(path.lstrip("/"), "text/html")
        elif path.endswith(".js"):
            self.servir_arquivo(path.lstrip("/"), "application/javascript")
        elif path.endswith(".json"):
            self.servir_arquivo(path.lstrip("/"), "application/json")
        else:
            self.send_error(404, "Não encontrado")

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")

        if path == "/api/login":
            self.post_login()
        elif path == "/api/processos":
            self.post_processo()
        elif path == "/api/importar-casos":
            self.post_importar_casos()
        elif re.match(r"^/api/processos/(.+)/status$", path):
            numero = re.match(r"^/api/processos/(.+)/status$", path).group(1)
            self.post_status(numero)
        elif re.match(r"^/api/processos/(.+)/laudo$", path):
            numero = re.match(r"^/api/processos/(.+)/laudo$", path).group(1)
            self.post_laudo(numero)
        elif re.match(r"^/api/processos/(.+)/liberar$", path):
            numero = re.match(r"^/api/processos/(.+)/liberar$", path).group(1)
            self.post_liberar(numero)
        elif re.match(r"^/api/processos/(.+)/gerar-laudo$", path):
            numero = re.match(r"^/api/processos/(.+)/gerar-laudo$", path).group(1)
            self.post_gerar_laudo(numero)
        elif re.match(r"^/api/processos/(.+)/mover$", path):
            numero = re.match(r"^/api/processos/(.+)/mover$", path).group(1)
            self.post_mover_processo(numero)
        elif re.match(r"^/api/processos/(.+)/anexos$", path):
            numero = re.match(r"^/api/processos/(.+)/anexos$", path).group(1)
            self.post_salvar_anexo(numero)
        elif re.match(r"^/api/anexos/(\d+)/deletar$", path):
            anexo_id = re.match(r"^/api/anexos/(\d+)/deletar$", path).group(1)
            self.post_deletar_anexo(int(anexo_id))
        elif path == "/api/admin/usuarios":
            self.post_criar_usuario()
        elif re.match(r"^/api/admin/usuarios/(.+)$", path):
            login_u = re.match(r"^/api/admin/usuarios/(.+)$", path).group(1)
            self.post_editar_usuario(login_u)
        elif path == "/api/admin/reimportar":
            self.post_reimportar()
        else:
            self.send_error(404)

    # ─────────────────────────────────────────
    # ENDPOINTS
    # ─────────────────────────────────────────

    def get_contadores(self):
        # Liberar automaticamente processos abertos há 60+ min sem conclusão
        try:
            conn_lp = conectar()
            from datetime import datetime, timedelta
            limite = (datetime.now() - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
            conn_lp.execute(
                """UPDATE processos
                   SET responsavel=NULL, dt_abertura=NULL, dt_atualizacao=?
                   WHERE status='em_andamento'
                     AND dt_abertura IS NOT NULL AND dt_abertura != ''
                     AND dt_abertura < ?""",
                [agora(), limite]
            )
            conn_lp.commit()
            conn_lp.close()
        except Exception:
            pass
        conn = conectar()
        rows = conn.execute(
            "SELECT status, COUNT(*) as total FROM processos GROUP BY status"
        ).fetchall()
        conn.close()
        cnt = {"em_andamento": 0, "aguardando": 0, "sem_contrato": 0, "concluido": 0}
        for r in rows:
            if r["status"] in cnt:
                cnt[r["status"]] = r["total"]
        json_resp(self, 200, cnt)

    def get_processos(self, qs):
        status          = qs.get("status",          [None])[0]
        busca           = qs.get("q",               [None])[0]
        trabalhados     = qs.get("trabalhados",      [None])[0]  # '1' = só com responsavel
        sem_responsavel = qs.get("sem_responsavel",  [None])[0]  # '1' = só sem responsavel
        pagina  = int(qs.get("pagina",     ["1"])[0])
        por_pag = int(qs.get("por_pagina", ["50"])[0])

        where  = []
        params = []

        if status:
            where.append("p.status = ?")
            params.append(status)

        if busca:
            like = f"%{busca}%"
            where.append("(p.processo LIKE ? OR p.nr_cpf_cnpj LIKE ? OR p.nm_escritorio LIKE ?)")
            params += [like, like, like]

        # Tabela do dashboard: só processos que já foram abertos por um analista
        if trabalhados == "1":
            where.append("p.responsavel IS NOT NULL AND p.responsavel != ''")

        # Novo laudo: próximo da fila sem responsavel ainda
        if sem_responsavel == "1":
            where.append("(p.responsavel IS NULL OR p.responsavel = '')")

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        offset    = (pagina - 1) * por_pag

        conn  = conectar()
        total = conn.execute(
            f"SELECT COUNT(*) FROM processos p {where_sql}", params
        ).fetchone()[0]

        rows  = conn.execute(
            f"""SELECT p.id, p.processo, p.pasta, p.nr_cpf_cnpj, p.nm_escritorio,
                       p.status, p.responsavel, p.dt_atualizacao, p.produto
                FROM processos p {where_sql}
                ORDER BY p.dt_atualizacao DESC, p.id ASC
                LIMIT ? OFFSET ?""",
            params + [por_pag, offset]
        ).fetchall()
        conn.close()

        json_resp(self, 200, {
            "total":    total,
            "pagina":   pagina,
            "por_pagina": por_pag,
            "processos": [dict(r) for r in rows]
        })

    def get_processo(self, numero):
        conn = conectar()
        proc = conn.execute(
            "SELECT * FROM processos WHERE processo = ?", [numero]
        ).fetchone()

        if not proc:
            conn.close()
            return json_resp(self, 404, {"erro": "Processo não encontrado"})

        # Gravar dt_abertura para controle de timeout 60 min
        conn.execute(
            "UPDATE processos SET dt_abertura=? WHERE processo=? AND (dt_abertura IS NULL OR dt_abertura='')",
            [agora(), numero]
        )
        conn.commit()

        contratos = conn.execute(
            "SELECT * FROM contratos WHERE processo_id = ?", [proc["id"]]
        ).fetchall()

        historico = conn.execute(
            """SELECT usuario, acao, status_anterior, status_novo, dt_registro
               FROM historico WHERE processo_id = ?
               ORDER BY id DESC LIMIT 20""",
            [proc["id"]]
        ).fetchall()

        conn.close()
        json_resp(self, 200, {
            **dict(proc),
            "contratos": [dict(c) for c in contratos],
            "historico":  [dict(h) for h in historico]
        })

    def post_login(self):
        body  = ler_body(self)
        login = body.get("login", "").strip()
        senha = body.get("senha", "")

        conn = conectar()
        user = conn.execute(
            "SELECT login, nome, senha_hash, admin FROM usuarios WHERE login=? AND ativo=1",
            [login]
        ).fetchone()
        conn.close()

        if user and user["senha_hash"] == hashlib.sha256(senha.encode()).hexdigest():
            json_resp(self, 200, {"ok": True, "nome": user["nome"],
                                   "login": login, "admin": bool(user["admin"])})
        else:
            json_resp(self, 401, {"ok": False, "erro": "Usuário ou senha inválidos"})


    def get_validar_sessao(self, qs):
        login = (qs.get("login", [None])[0] or "").strip()
        if not login:
            return json_resp(self, 400, {"ok": False, "erro": "Login obrigatório"})
        conn = conectar()
        user = conn.execute(
            "SELECT login, nome, admin FROM usuarios WHERE login=? AND ativo=1",
            [login]
        ).fetchone()
        conn.close()
        if user:
            json_resp(self, 200, {"ok": True, "nome": user["nome"],
                                   "login": user["login"], "admin": bool(user["admin"])})
        else:
            json_resp(self, 200, {"ok": False})

    def post_processo(self):
        """Cria um novo processo manual (não vindo do Excel)."""
        body = ler_body(self)
        numero = (body.get("processo") or "").strip()
        if not numero:
            return json_resp(self, 400, {"erro": "Número de processo obrigatório"})

        conn = conectar()
        try:
            conn.execute(
                """INSERT INTO processos
                   (processo, pasta, nr_cpf_cnpj, nm_escritorio, status, dt_atualizacao)
                   VALUES (?,?,?,?,?,?)""",
                [numero, body.get("pasta",""), body.get("nr_cpf_cnpj",""),
                 body.get("nm_escritorio",""), "em_andamento", agora()]
            )
            conn.commit()
            json_resp(self, 201, {"ok": True})
        except sqlite3.IntegrityError:
            json_resp(self, 409, {"erro": "Processo já cadastrado"})
        finally:
            conn.close()

    def post_status(self, numero):
        """Muda o status de um processo: em_andamento ↔ aguardando | concluido."""
        body    = ler_body(self)
        novo    = body.get("status")
        usuario = body.get("usuario", "sistema")
        validos = {"pendente_validacao", "em_andamento", "aguardando", "sem_contrato", "concluido"}

        if novo not in validos:
            return json_resp(self, 400, {"erro": f"Status inválido. Válidos: {validos}"})

        conn = conectar()
        proc = conn.execute(
            "SELECT id, status FROM processos WHERE processo = ?", [numero]
        ).fetchone()

        if not proc:
            conn.close()
            return json_resp(self, 404, {"erro": "Processo não encontrado"})

        anterior = proc["status"]
        conn.execute(
            "UPDATE processos SET status=?, responsavel=?, dt_atualizacao=? WHERE id=?",
            [novo, usuario, agora(), proc["id"]]
        )
        conn.execute(
            """INSERT INTO historico (processo_id, usuario, acao, status_anterior, status_novo)
               VALUES (?,?,?,?,?)""",
            [proc["id"], usuario, f"status: {anterior} → {novo}", anterior, novo]
        )
        conn.commit()
        conn.close()
        json_resp(self, 200, {"ok": True, "status_anterior": anterior, "status_novo": novo})

    def post_laudo(self, numero):
        """Salva os campos preenchidos pelo analista no laudo."""
        body    = ler_body(self)
        usuario = body.get("usuario", "sistema")

        campos = [
            "produto", "autor", "resumo_causa", "causa_raiz", "advogado_agressor",
            "adv_agressor",
            "nome_cliente", "endereco", "analfabeto", "testemunhas",
            "subsidios_fav", "estrategia", "resultado_tipo", "observacoes",
            # checklist
            "ck_bo", "ck_analfabeto", "ck_terceiros", "ck_primeira_tx",
            "ck_biometria_leg", "ck_biometria_ok", "ck_docs_ok", "ck_conta_agi",
            "ck_compras", "ck_compras_anormais", "ck_ted", "ck_saque_cartao",
            "ck_uso_cartao", "ck_pagamento_fatura", "ck_valor_conta", "ck_spc",
            "ck_procuracao", "ck_comprov_end", "ck_outras_acoes", "ck_passagens",
            # sistemas
            "appsmith_qtd", "conductor_qtd", "fraud_qtd", "ged_qtd",
            "matera_qtd", "recupera_qtd", "salesforce_qtd", "biometria_qtd"
        ]

        conn = conectar()
        proc = conn.execute(
            "SELECT id FROM processos WHERE processo = ?", [numero]
        ).fetchone()

        if not proc:
            conn.close()
            return json_resp(self, 404, {"erro": "Processo não encontrado"})

        sets    = ", ".join(f"{c}=?" for c in campos if c in body)
        valores = [body[c] for c in campos if c in body]

        if sets:
            conn.execute(
                f"UPDATE processos SET {sets}, responsavel=?, dt_atualizacao=? WHERE id=?",
                valores + [usuario, agora(), proc["id"]]
            )
            conn.execute(
                """INSERT INTO historico (processo_id, usuario, acao)
                   VALUES (?,?,?)""",
                [proc["id"], usuario, "laudo salvo"]
            )

        # Salvar contratos se vieram no body
        if "contratos" in body and isinstance(body["contratos"], list):
            conn.execute("DELETE FROM contratos WHERE processo_id = ?", [proc["id"]])
            for ct in body["contratos"]:
                nr    = ct.get("nr","")
                prod  = ct.get("prod","")
                dt    = ct.get("dt","")
                canal = ct.get("canal","")
                vl    = ct.get("vl","")
                if nr:
                    conn.execute(
                        "INSERT INTO contratos (processo_id, nr_contrato, ds_produto, dt_contrato, vl_contrato, canal) VALUES (?,?,?,?,?,?)",
                        [proc["id"], nr, prod, dt, vl, canal]
                    )

        conn.commit()
        conn.close()
        json_resp(self, 200, {"ok": True})


    def get_aguardando(self, qs):
        busca    = qs.get("q",        [None])[0]
        analista = qs.get("analista", [None])[0]
        pagina   = int(qs.get("pagina",     ["1"])[0])
        por_pag  = int(qs.get("por_pagina", ["50"])[0])
        where  = ["p.status = 'aguardando'"]
        params = []
        if busca:
            like = f"%{busca}%"
            where.append("(p.processo LIKE ? OR p.autor LIKE ?)")
            params += [like, like]
        if analista:
            where.append("p.responsavel = ?")
            params.append(analista)
        where_sql = "WHERE " + " AND ".join(where)
        offset    = (pagina - 1) * por_pag
        conn  = conectar()
        total = conn.execute(f"SELECT COUNT(*) FROM processos p {where_sql}", params).fetchone()[0]
        rows  = conn.execute(
            f"""SELECT p.processo, p.autor, p.nr_cpf_cnpj, p.produto,
                       p.causa_raiz, p.responsavel, p.dt_inclusao, p.dt_atualizacao
                FROM processos p {where_sql}
                ORDER BY p.dt_atualizacao DESC LIMIT ? OFFSET ?""",
            params + [por_pag, offset]
        ).fetchall()
        conn.close()
        json_resp(self, 200, {"total": total, "pagina": pagina, "processos": [dict(r) for r in rows]})

    def get_analistas(self):
        conn = conectar()
        rows = conn.execute(
            """SELECT DISTINCT responsavel FROM processos
               WHERE status = 'aguardando' AND responsavel IS NOT NULL AND responsavel != ''
               ORDER BY responsavel"""
        ).fetchall()
        conn.close()
        json_resp(self, 200, {"analistas": [r["responsavel"] for r in rows]})

    def post_liberar(self, numero):
        conn = conectar()
        proc = conn.execute("SELECT id FROM processos WHERE processo = ?", [numero]).fetchone()
        if not proc:
            conn.close()
            return json_resp(self, 404, {"erro": "Processo nao encontrado"})
        conn.execute(
            "UPDATE processos SET responsavel=NULL, dt_abertura=NULL, status='em_andamento', dt_atualizacao=? WHERE processo=?",
            [agora(), numero]
        )
        conn.commit()
        conn.close()
        json_resp(self, 200, {"ok": True, "processo": numero})


    def post_validar_contrato(self, numero):
        """Valida se há contrato e move o processo para a fila correta."""
        body             = ler_body(self)
        possui_contrato  = body.get("possui_contrato", "")   # "sim" ou "nao"
        obs              = body.get("obs", "")
        usuario          = body.get("usuario", "sistema")

        if possui_contrato not in ("sim", "nao"):
            return json_resp(self, 400, {"erro": "possui_contrato deve ser 'sim' ou 'nao'"})

        novo_status = "em_andamento" if possui_contrato == "sim" else "sem_contrato"

        conn = conectar()
        proc = conn.execute(
            "SELECT id, status FROM processos WHERE processo = ?", [numero]
        ).fetchone()

        if not proc:
            conn.close()
            return json_resp(self, 404, {"erro": "Processo nao encontrado"})

        anterior = proc["status"]
        conn.execute(
            """UPDATE processos
               SET status=?, validacao_contrato=?, validacao_obs=?,
                   responsavel=NULL, dt_abertura=NULL, dt_atualizacao=?
               WHERE id=?""",
            [novo_status, possui_contrato, obs, agora(), proc["id"]]
        )
        acao = f"validacao: contrato={'sim' if possui_contrato=='sim' else 'nao'} — movido para {novo_status}"
        conn.execute(
            """INSERT INTO historico (processo_id, usuario, acao, status_anterior, status_novo)
               VALUES (?,?,?,?,?)""",
            [proc["id"], usuario, acao, anterior, novo_status]
        )
        conn.commit()
        conn.close()
        json_resp(self, 200, {"ok": True, "status_novo": novo_status})

    def post_importar_casos(self):
        """Importa carga diaria de processos via Excel (multipart/form-data)."""
        import cgi, io

        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return json_resp(self, 400, {"erro": "Envie os arquivos via multipart/form-data"})

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": ctype,
            "CONTENT_LENGTH": str(length),
        }
        form = cgi.FieldStorage(
            fp=io.BytesIO(raw),
            environ=environ,
            keep_blank_values=True
        )

        try:
            import openpyxl
        except ImportError:
            return json_resp(self, 500, {"erro": "openpyxl nao instalado. Execute: pip install openpyxl"})

        def parse_xlsx(field_item):
            data = field_item.file.read()
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return [], []
            headers = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
            result = []
            for row in rows[1:]:
                if all(v is None or str(v).strip() == "" for v in row):
                    continue
                result.append(dict(zip(headers, [str(v).strip() if v is not None else "" for v in row])))
            return headers, result

        inseridos  = 0
        atualizados = 0
        ignorados  = 0
        log        = []

        conn = conectar()
        try:
            if "processos" not in form:
                return json_resp(self, 400, {"erro": "Campo 'processos' obrigatorio"})

            _, rows_proc = parse_xlsx(form["processos"])

            for row in rows_proc:
                numero = row.get("processo", "").strip()
                if not numero:
                    ignorados += 1
                    log.append(f"Linha ignorada: campo 'processo' vazio")
                    continue

                existing = conn.execute(
                    "SELECT id FROM processos WHERE processo = ?", [numero]
                ).fetchone()

                pasta        = row.get("pasta", "")
                cpf_cnpj     = row.get("nr_cpf_cnpj", "") or row.get("cpf_cnpj", "") or row.get("cpf", "")
                escritorio   = row.get("nm_escritorio", "") or row.get("escritorio", "")
                dt_inclusao  = row.get("dt_inclusao", "") or row.get("data_inclusao", "") or row.get("data", "")

                if existing:
                    conn.execute(
                        """UPDATE processos SET pasta=?, nr_cpf_cnpj=?, nm_escritorio=?,
                           dt_inclusao=?, dt_atualizacao=? WHERE id=?""",
                        [pasta, cpf_cnpj, escritorio, dt_inclusao, agora(), existing["id"]]
                    )
                    atualizados += 1
                    log.append(f"Atualizado: {numero}")
                else:
                    conn.execute(
                        """INSERT INTO processos
                           (processo, pasta, nr_cpf_cnpj, nm_escritorio, dt_inclusao, status, dt_atualizacao)
                           VALUES (?,?,?,?,?,?,?)""",
                        [numero, pasta, cpf_cnpj, escritorio, dt_inclusao, "em_andamento", agora()]
                    )
                    inseridos += 1
                    log.append(f"Inserido: {numero}")

            if "contratos" in form:
                _, rows_cont = parse_xlsx(form["contratos"])
                for row in rows_cont:
                    numero_cont = row.get("processo", "").strip()
                    if not numero_cont:
                        continue
                    proc_row = conn.execute(
                        "SELECT id FROM processos WHERE processo = ?", [numero_cont]
                    ).fetchone()
                    if not proc_row:
                        log.append(f"Contrato ignorado: processo {numero_cont} nao encontrado")
                        continue
                    nr_cont    = row.get("nr_contrato", "") or row.get("contrato", "")
                    ds_produto = row.get("ds_produto", "") or row.get("produto", "")
                    dt_cont    = row.get("dt_contrato", "") or row.get("data_contrato", "")
                    vl_cont    = row.get("vl_contrato", "") or row.get("valor", "")
                    canal      = row.get("canal", "")
                    already = conn.execute(
                        "SELECT id FROM contratos WHERE processo_id=? AND nr_contrato=?",
                        [proc_row["id"], nr_cont]
                    ).fetchone()
                    if not already:
                        conn.execute(
                            """INSERT INTO contratos (processo_id, nr_contrato, ds_produto, dt_contrato, vl_contrato, canal)
                               VALUES (?,?,?,?,?,?)""",
                            [proc_row["id"], nr_cont, ds_produto, dt_cont, vl_cont, canal]
                        )
                        log.append(f"Contrato {nr_cont} vinculado a {numero_cont}")

            conn.commit()
        except Exception as ex:
            conn.close()
            return json_resp(self, 500, {"erro": f"Erro ao processar planilha: {ex}"})

        conn.close()
        json_resp(self, 200, {
            "ok": True,
            "inseridos": inseridos,
            "atualizados": atualizados,
            "ignorados": ignorados,
            "log": log
        })

    def get_pdf_processo(self, numero):
        """Serve o PDF salvo de um laudo."""
        conn = conectar()
        proc = conn.execute(
            "SELECT caminho_pdf FROM processos WHERE processo = ?", [numero]
        ).fetchone()
        conn.close()

        if not proc or not proc["caminho_pdf"]:
            return json_resp(self, 404, {"erro": "PDF nao encontrado para este processo"})

        caminho = proc["caminho_pdf"]
        if not os.path.exists(caminho):
            return json_resp(self, 404, {"erro": "Arquivo PDF nao encontrado no servidor"})

        nome_arquivo = f"laudo_{numero.replace('/', '_').replace(' ', '_')}.pdf"
        with open(caminho, "rb") as f:
            pdf_bytes = f.read()

        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'attachment; filename="{nome_arquivo}"')
        self.send_header("Content-Length", len(pdf_bytes))
        self.end_headers()
        self.wfile.write(pdf_bytes)

    def post_gerar_laudo(self, numero):
        """Gera o laudo em PDF e retorna para download."""
        import importlib.util, tempfile, json as _json

        body = ler_body(self)

        # Buscar dados do banco
        conn = conectar()
        proc = conn.execute("SELECT * FROM processos WHERE processo = ?", [numero]).fetchone()
        cts  = conn.execute("SELECT * FROM contratos WHERE processo_id = ?", [proc["id"]]).fetchall() if proc else []
        conn.close()

        if not proc:
            return json_resp(self, 404, {"erro": "Processo nao encontrado"})

        # Montar dados: banco + formulário (formulário tem prioridade)
        dados = dict(proc)
        dados.update({k: v for k, v in body.items() if v is not None and v != ""})

        # Normalizar campos
        from datetime import datetime as _dt

        dados["data_dist"]  = dados.get("data_dist")  or dados.get("dt_inclusao","")
        dados["autor"]      = dados.get("autor")       or dados.get("nome_cliente","")
        dados["cpf"]        = dados.get("cpf")         or dados.get("nr_cpf_cnpj","")
        dados["endereco"]   = dados.get("endereco","")
        dados["produto"]    = dados.get("produto","")  or dados.get("produto_principal","")
        dados["causa_raiz"] = dados.get("causa_raiz","")
        dados["responsavel"]= dados.get("responsavel","") or dados.get("usuario","")

        # Data do laudo: garantir formato dd/mm/yyyy
        dl = dados.get("data_laudo","")
        if dl:
            if len(dl) == 10 and dl[4] == "-":  # YYYY-MM-DD → DD/MM/YYYY
                dl = dl[8:10] + "/" + dl[5:7] + "/" + dl[0:4]
        else:
            dl = _dt.today().strftime("%d/%m/%Y")
        dados["data_laudo"] = dl

        # Checklist: garantir campos com fallback vazio
        for _ck in ["ck_bo","ck_analfabeto","ck_terceiros","ck_primeira_tx",
                    "ck_biometria_leg","ck_biometria_ok","ck_docs_ok","ck_conta_agi",
                    "ck_compras","ck_compras_anormais","ck_ted","ck_saque_cartao",
                    "ck_uso_cartao","ck_pagamento_fatura","ck_valor_conta","ck_spc",
                    "ck_procuracao","ck_comprov_end","ck_outras_acoes","ck_passagens"]:
            if not dados.get(_ck):
                dados[_ck] = ""

        # Sistemas: garantir "0" como fallback
        for _s in ["appsmith_qtd","conductor_qtd","fraud_qtd","ged_qtd",
                   "matera_qtd","recupera_qtd","salesforce_qtd","biometria_qtd"]:
            if not dados.get(_s):
                dados[_s] = "0"

        # Contratos: preferir os do formulário, senão do banco
        if body.get("contratos"):
            dados["contratos"] = body["contratos"]
        else:
            dados["contratos"] = [
                {"nr": ct["nr_contrato"], "prod": ct["ds_produto"],
                 "dt": ct["dt_contrato"], "vl":  ct.get("vl_contrato",""),
                 "canal": ct.get("canal","")}
                for ct in cts
            ]

        # Anexos: carregar arquivos do disco usando os IDs enviados
        import base64 as _b64gp
        anexos_ids = body.get("anexos_ids", {})
        dados["anexos"] = {}
        for app_id, lista in anexos_ids.items():
            dados["anexos"][app_id] = []
            for item in lista:
                row = conn2 = None
                try:
                    conn2 = conectar()
                    row = conn2.execute(
                        "SELECT caminho, nome, tipo, conteudo FROM anexos WHERE id=?", [item["id"]]
                    ).fetchone()
                    conn2.close()
                    if row:
                        if os.path.exists(row["caminho"]):
                            with open(row["caminho"], "rb") as f_anx:
                                raw = f_anx.read()
                        elif row["conteudo"]:
                            raw = bytes(row["conteudo"])
                        else:
                            raw = None
                        if raw:
                            b64 = "data:" + (row["tipo"] or "image/png") + ";base64," + _b64gp.b64encode(raw).decode()
                            dados["anexos"][app_id].append({
                                "nome": row["nome"], "tipo": row["tipo"], "data": b64
                            })
                except Exception:
                    if conn2:
                        try: conn2.close()
                        except: pass

        # Carregar o script de geração
        script_path = os.path.join(DIR_BASE, "gerar_laudo_pdf.py")
        if not os.path.exists(script_path):
            return json_resp(self, 500, {"erro": "gerar_laudo_pdf.py nao encontrado na pasta do sistema"})

        try:
            spec = importlib.util.spec_from_file_location("gerar_laudo_pdf", script_path)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            pdf_bytes = mod.gerar_pdf(dados, "buffer")
        except Exception as ex:
            return json_resp(self, 500, {"erro": f"Erro ao gerar PDF: {ex}"})

        nome_arquivo = f"laudo_{numero.replace('/', '_').replace(' ','_')}.pdf"

        # Salvar PDF em disco e registrar caminho no banco
        try:
            pdf_dir = os.path.join(DIR_BASE, "laudos_pdf")
            os.makedirs(pdf_dir, exist_ok=True)
            caminho_pdf = os.path.join(pdf_dir, nome_arquivo)
            with open(caminho_pdf, "wb") as f_out:
                f_out.write(pdf_bytes)
            conn_upd = conectar()
            conn_upd.execute(
                "UPDATE processos SET caminho_pdf=?, dt_atualizacao=? WHERE processo=?",
                [caminho_pdf, agora(), numero]
            )
            conn_upd.commit()
            conn_upd.close()
        except Exception:
            pass  # salvar PDF e' opcional: nao impede o download

        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'attachment; filename="{nome_arquivo}"')
        self.send_header("Content-Length", len(pdf_bytes))
        self.end_headers()
        self.wfile.write(pdf_bytes)


    def post_reimportar(self):
        """Reimporta os arquivos Excel locais (data.xlsx e data (7).xlsx) para o banco."""
        arq1 = os.path.join(DIR_BASE, "data.xlsx")
        arq2 = os.path.join(DIR_BASE, "data (7).xlsx")

        if not os.path.exists(arq1):
            return json_resp(self, 404, {"erro": f"Arquivo não encontrado: data.xlsx"})

        try:
            import importar_excel as _mod_imp
            import io
            from contextlib import redirect_stdout

            _mod_imp.DB_ARQUIVO = DB_ARQUIVO

            buf = io.StringIO()
            with redirect_stdout(buf):
                _mod_imp.importar(arq1, arq2 if os.path.exists(arq2) else None)

            log = buf.getvalue()
            inseridos   = 0
            atualizados = 0
            ignorados   = 0
            for line in log.splitlines():
                if "Inseridos:" in line:
                    try: inseridos   = int(line.split(":")[1].strip())
                    except Exception: pass
                elif "Atualizados:" in line:
                    try: atualizados = int(line.split(":")[1].strip())
                    except Exception: pass
                elif "Ignorados:" in line:
                    try: ignorados   = int(line.split(":")[1].strip())
                    except Exception: pass

            json_resp(self, 200, {
                "ok": True,
                "inseridos":   inseridos,
                "atualizados": atualizados,
                "ignorados":   ignorados,
                "log":         log,
            })
        except Exception as ex:
            json_resp(self, 500, {"erro": f"Erro ao reimportar: {ex}"})

    def servir_arquivo(self, nome, content_type):
        caminho = os.path.join(DIR_BASE, nome)
        if not os.path.exists(caminho):
            self.send_error(404, f"Arquivo não encontrado: {nome}")
            return
        with open(caminho, "rb") as f:
            conteudo = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", len(conteudo))
        self.end_headers()
        self.wfile.write(conteudo)


# ─────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    # Utilitário: adicionar usuário
    if "--adduser" in sys.argv:
        idx   = sys.argv.index("--adduser")
        login = sys.argv[idx+1]
        senha = sys.argv[idx+2]
        nome  = sys.argv[idx+3] if len(sys.argv) > idx+3 else login
        h     = hashlib.sha256(senha.encode()).hexdigest()
        print(f'\n  Adicione ao dict USUARIOS em servidor.py:\n')
        print(f'  "{login}": {{"senha_hash": "{h}", "nome": "{nome}"}},\n')
        sys.exit(0)

    import socket

    print("\n  Sistema de Laudos SBK")
    print("  " + "─"*34)
    criar_tabelas()

    # Descobrir IP local para exibir o endereço de acesso na rede
    try:
        ip_local = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip_local = "SEU_IP"

    # "0.0.0.0" faz o servidor aceitar conexões de qualquer interface de rede
    # incluindo VPN — o controle de acesso é feito pelo login/senha
    httpd = HTTPServer(("0.0.0.0", PORTA), Handler)

    print(f"  Acesso local:    http://localhost:{PORTA}")
    print(f"  Acesso na rede:  http://{ip_local}:{PORTA}")
    print(f"  (Compartilhe o endereço da rede com quem acessa via VPN)")
    print("  Pressione Ctrl+C para encerrar.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Servidor encerrado.")
