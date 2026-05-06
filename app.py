"""
app.py — Sistema de Laudos SBK (Flask + Gunicorn)
"""

from dotenv import load_dotenv
load_dotenv()

import os
import sys

if "DATABASE_URL" not in os.environ:
    print("ERRO: DATABASE_URL nao configurado")
    sys.exit(1)

if "SECRET_KEY" not in os.environ:
    print("AVISO: SECRET_KEY nao configurado, usando chave temporaria insegura")

import io
import re
import json
import sqlite3
import hashlib
import base64
import uuid
import secrets
import importlib.util
from functools import wraps
from datetime import datetime, timedelta

import jwt
from flask import Flask, request, jsonify, send_from_directory, send_file, Response, abort

from servidor import (
    conectar,
    criar_tabelas,
    agora,
    USUARIOS,
    USE_POSTGRES,
    DATABASE_URL,
    DIR_BASE,
    ANEXOS_DIR,
    DB_ARQUIVO,
)

app = Flask(__name__)


# ─────────────────────────────────────────────
# JWT / AUTENTICAÇÃO
# ─────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    print("AVISO: SECRET_KEY não definida no ambiente. Usando valor temporário (apenas para desenvolvimento).")
    SECRET_KEY = secrets.token_hex(32)

JWT_ALGO = "HS256"
JWT_EXP_HOURS = 8


def gerar_token(login, nome, admin):
    payload = {
        "login": login,
        "nome": nome,
        "admin": bool(admin),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXP_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGO)


def requer_auth(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return json_response({"erro": "Não autorizado"}, 401)
        token = auth[7:].strip()
        if not token:
            return json_response({"erro": "Não autorizado"}, 401)
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGO])
        except jwt.PyJWTError:
            return json_response({"erro": "Não autorizado"}, 401)
        request.usuario_jwt = payload
        return func(*args, **kwargs)
    return wrapper


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def json_response(data, status=200):
    body = json.dumps(data, ensure_ascii=False)
    resp = Response(body, status=status, mimetype="application/json; charset=utf-8")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def get_body():
    if request.is_json:
        return request.get_json(silent=True) or {}
    raw = request.get_data()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


@app.after_request
def add_cors(resp):
    resp.headers.setdefault("Access-Control-Allow-Origin", "*")
    return resp


@app.route("/<path:any_path>", methods=["OPTIONS"])
@app.route("/", methods=["OPTIONS"])
def options_handler(any_path=None):
    resp = Response("", status=204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# ─────────────────────────────────────────────
# ROTAS — ARQUIVOS ESTÁTICOS
# ─────────────────────────────────────────────
@app.route("/", methods=["GET"])
@app.route("/index.html", methods=["GET"])
def index():
    html_name = "sistema_laudos_v2.html" if os.path.exists(
        os.path.join(DIR_BASE, "sistema_laudos_v2.html")
    ) else "sistema_laudos_layout.html"
    return send_from_directory(DIR_BASE, html_name)


@app.route("/<path:filename>", methods=["GET"])
def static_files(filename):
    if not (filename.endswith(".html") or filename.endswith(".js") or filename.endswith(".json")):
        abort(404)
    caminho = os.path.join(DIR_BASE, filename)
    if not os.path.exists(caminho):
        abort(404)
    if filename.endswith(".html"):
        mt = "text/html"
    elif filename.endswith(".js"):
        mt = "application/javascript"
    else:
        mt = "application/json"
    return send_from_directory(DIR_BASE, filename, mimetype=mt)


# ─────────────────────────────────────────────
# ROTAS API — GET
# ─────────────────────────────────────────────
@app.route("/api/contadores", methods=["GET"])
@requer_auth
def api_contadores():
    try:
        conn_lp = conectar()
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
    return json_response(cnt)


@app.route("/api/processos", methods=["GET"])
@requer_auth
def api_get_processos():
    qs = request.args
    status = qs.get("status")
    busca = qs.get("q")
    trabalhados = qs.get("trabalhados")
    sem_responsavel = qs.get("sem_responsavel")
    pagina = int(qs.get("pagina", "1"))
    por_pag = int(qs.get("por_pagina", "50"))

    where = []
    params = []
    if status:
        where.append("p.status = ?")
        params.append(status)
    if busca:
        like = f"%{busca}%"
        where.append("(p.processo LIKE ? OR p.nr_cpf_cnpj LIKE ? OR p.nm_escritorio LIKE ?)")
        params += [like, like, like]
    if trabalhados == "1":
        where.append("p.responsavel IS NOT NULL AND p.responsavel != ''")
    if sem_responsavel == "1":
        where.append("(p.responsavel IS NULL OR p.responsavel = '')")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    offset = (pagina - 1) * por_pag

    conn = conectar()
    total = conn.execute(
        f"SELECT COUNT(*) FROM processos p {where_sql}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT p.id, p.processo, p.pasta, p.nr_cpf_cnpj, p.nm_escritorio,
                   p.status, p.responsavel, p.dt_atualizacao, p.produto
            FROM processos p {where_sql}
            ORDER BY p.dt_atualizacao DESC, p.id ASC
            LIMIT ? OFFSET ?""",
        params + [por_pag, offset]
    ).fetchall()
    conn.close()

    return json_response({
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pag,
        "processos": [dict(r) for r in rows],
    })


@app.route("/api/processos/<path:numero>/pdf", methods=["GET"])
@requer_auth
def api_get_pdf(numero):
    conn = conectar()
    proc = conn.execute(
        "SELECT caminho_pdf FROM processos WHERE processo = ?", [numero]
    ).fetchone()
    conn.close()
    if not proc or not proc["caminho_pdf"]:
        return json_response({"erro": "PDF nao encontrado para este processo"}, 404)
    caminho = proc["caminho_pdf"]
    if not os.path.exists(caminho):
        return json_response({"erro": "Arquivo PDF nao encontrado no servidor"}, 404)
    nome_arquivo = f"laudo_{numero.replace('/', '_').replace(' ', '_')}.pdf"
    with open(caminho, "rb") as f:
        pdf_bytes = f.read()
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=nome_arquivo,
    )


@app.route("/api/processos/<path:numero>/anexos", methods=["GET"])
@requer_auth
def api_get_anexos(numero):
    conn = conectar()
    proc = conn.execute("SELECT id FROM processos WHERE processo=?", [numero]).fetchone()
    if not proc:
        conn.close()
        return json_response({"erro": "Processo nao encontrado"}, 404)
    rows = conn.execute(
        "SELECT id, app_id, nome, tipo FROM anexos WHERE processo_id=? ORDER BY app_id, id",
        [proc["id"]]
    ).fetchall()
    conn.close()
    return json_response({"anexos": [dict(r) for r in rows]})


@app.route("/api/processos/<path:numero>", methods=["GET"])
@requer_auth
def api_get_processo(numero):
    conn = conectar()
    proc = conn.execute("SELECT * FROM processos WHERE processo = ?", [numero]).fetchone()
    if not proc:
        conn.close()
        return json_response({"erro": "Processo não encontrado"}, 404)
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
    return json_response({
        **dict(proc),
        "contratos": [dict(c) for c in contratos],
        "historico": [dict(h) for h in historico],
    })


@app.route("/api/aguardando", methods=["GET"])
@requer_auth
def api_aguardando():
    qs = request.args
    busca = qs.get("q")
    analista = qs.get("analista")
    pagina = int(qs.get("pagina", "1"))
    por_pag = int(qs.get("por_pagina", "50"))
    where = ["p.status = 'aguardando'"]
    params = []
    if busca:
        like = f"%{busca}%"
        where.append("(p.processo LIKE ? OR p.autor LIKE ?)")
        params += [like, like]
    if analista:
        where.append("p.responsavel = ?")
        params.append(analista)
    where_sql = "WHERE " + " AND ".join(where)
    offset = (pagina - 1) * por_pag
    conn = conectar()
    total = conn.execute(f"SELECT COUNT(*) FROM processos p {where_sql}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT p.processo, p.autor, p.nr_cpf_cnpj, p.produto,
                   p.causa_raiz, p.responsavel, p.dt_inclusao, p.dt_atualizacao
            FROM processos p {where_sql}
            ORDER BY p.dt_atualizacao DESC LIMIT ? OFFSET ?""",
        params + [por_pag, offset]
    ).fetchall()
    conn.close()
    return json_response({"total": total, "pagina": pagina, "processos": [dict(r) for r in rows]})


@app.route("/api/analistas", methods=["GET"])
@requer_auth
def api_analistas():
    conn = conectar()
    rows = conn.execute(
        """SELECT DISTINCT responsavel FROM processos
           WHERE status = 'aguardando' AND responsavel IS NOT NULL AND responsavel != ''
           ORDER BY responsavel"""
    ).fetchall()
    conn.close()
    return json_response({"analistas": [r["responsavel"] for r in rows]})


@app.route("/api/admin/usuarios", methods=["GET"])
@requer_auth
def api_get_usuarios():
    conn = conectar()
    rows = conn.execute(
        "SELECT login, nome, admin, ativo FROM usuarios ORDER BY nome"
    ).fetchall()
    conn.close()
    return json_response({"usuarios": [dict(r) for r in rows]})


@app.route("/api/relatorios/produtividade", methods=["GET"])
@requer_auth
def api_relatorio_produtividade():
    conn = conectar()
    rows = conn.execute(
        """SELECT p.processo, p.status, p.dt_atualizacao as dt_conclusao,
                  p.responsavel, p.produto, p.autor
           FROM processos p
           WHERE p.status = 'concluido'
           ORDER BY p.dt_atualizacao DESC"""
    ).fetchall()
    conn.close()
    return json_response({"dados": [dict(r) for r in rows]})


@app.route("/api/relatorios/faturamento", methods=["GET"])
@requer_auth
def api_relatorio_faturamento():
    conn = conectar()
    rows = conn.execute(
        """SELECT p.processo, p.dt_atualizacao as dt_conclusao,
                  p.resultado_tipo, p.status
           FROM processos p
           WHERE p.status = 'concluido'
           ORDER BY p.dt_atualizacao DESC"""
    ).fetchall()
    conn.close()
    return json_response({"dados": [dict(r) for r in rows]})


@app.route("/api/anexos/<int:anexo_id>", methods=["GET"])
@requer_auth
def api_get_anexo_arquivo(anexo_id):
    conn = conectar()
    row = conn.execute(
        "SELECT caminho, nome, tipo, conteudo FROM anexos WHERE id=?", [anexo_id]
    ).fetchone()
    conn.close()
    if not row:
        return json_response({"erro": "Anexo nao encontrado"}, 404)
    if os.path.exists(row["caminho"]):
        with open(row["caminho"], "rb") as f:
            dados = f.read()
    elif row["conteudo"]:
        dados = bytes(row["conteudo"])
    else:
        return json_response({"erro": "Anexo nao encontrado"}, 404)
    tipo = row["tipo"] or "application/octet-stream"
    resp = send_file(
        io.BytesIO(dados),
        mimetype=tipo,
        as_attachment=False,
        download_name=row["nome"],
    )
    resp.headers["Content-Disposition"] = f'inline; filename="{row["nome"]}"'
    return resp


# ─────────────────────────────────────────────
# ROTAS API — POST
# ─────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def api_login():
    body = get_body()
    login = body.get("login", "").strip()
    senha = body.get("senha", "")
    conn = conectar()
    user = conn.execute(
        "SELECT login, nome, senha_hash, admin FROM usuarios WHERE login=? AND ativo=1",
        [login]
    ).fetchone()
    conn.close()
    if user and user["senha_hash"] == hashlib.sha256(senha.encode()).hexdigest():
        token = gerar_token(login, user["nome"], user["admin"])
        return json_response({"ok": True, "nome": user["nome"],
                              "login": login, "admin": bool(user["admin"]),
                              "token": token})
    return json_response({"ok": False, "erro": "Usuário ou senha inválidos"}, 401)


@app.route("/api/processos", methods=["POST"])
@requer_auth
def api_post_processo():
    body = get_body()
    numero = (body.get("processo") or "").strip()
    if not numero:
        return json_response({"erro": "Número de processo obrigatório"}, 400)
    conn = conectar()
    try:
        conn.execute(
            """INSERT INTO processos
               (processo, pasta, nr_cpf_cnpj, nm_escritorio, status, dt_atualizacao)
               VALUES (?,?,?,?,?,?)""",
            [numero, body.get("pasta", ""), body.get("nr_cpf_cnpj", ""),
             body.get("nm_escritorio", ""), "em_andamento", agora()]
        )
        conn.commit()
        return json_response({"ok": True}, 201)
    except sqlite3.IntegrityError:
        return json_response({"erro": "Processo já cadastrado"}, 409)
    except Exception:
        return json_response({"erro": "Processo já cadastrado"}, 409)
    finally:
        conn.close()


@app.route("/api/importar-casos", methods=["POST"])
@requer_auth
def api_importar_casos():
    try:
        import openpyxl
    except ImportError:
        return json_response({"erro": "openpyxl nao instalado. Execute: pip install openpyxl"}, 500)

    if "processos" not in request.files:
        return json_response({"erro": "Campo 'processos' obrigatorio"}, 400)

    def parse_xlsx(file_storage):
        data = file_storage.read()
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

    inseridos = 0
    atualizados = 0
    ignorados = 0
    log = []

    conn = conectar()
    try:
        _, rows_proc = parse_xlsx(request.files["processos"])

        for row in rows_proc:
            numero = row.get("processo", "").strip()
            if not numero:
                ignorados += 1
                log.append("Linha ignorada: campo 'processo' vazio")
                continue

            existing = conn.execute(
                "SELECT id FROM processos WHERE processo = ?", [numero]
            ).fetchone()

            pasta = row.get("pasta", "")
            cpf_cnpj = row.get("nr_cpf_cnpj", "") or row.get("cpf_cnpj", "") or row.get("cpf", "")
            escritorio = row.get("nm_escritorio", "") or row.get("escritorio", "")
            dt_inclusao = row.get("dt_inclusao", "") or row.get("data_inclusao", "") or row.get("data", "")

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

        if "contratos" in request.files:
            _, rows_cont = parse_xlsx(request.files["contratos"])
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
                nr_cont = row.get("nr_contrato", "") or row.get("contrato", "")
                ds_produto = row.get("ds_produto", "") or row.get("produto", "")
                dt_cont = row.get("dt_contrato", "") or row.get("data_contrato", "")
                vl_cont = row.get("vl_contrato", "") or row.get("valor", "")
                canal = row.get("canal", "")
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
        return json_response({"erro": f"Erro ao processar planilha: {ex}"}, 500)

    conn.close()
    return json_response({
        "ok": True,
        "inseridos": inseridos,
        "atualizados": atualizados,
        "ignorados": ignorados,
        "log": log,
    })


@app.route("/api/processos/<path:numero>/status", methods=["POST"])
@requer_auth
def api_post_status(numero):
    body = get_body()
    novo = body.get("status")
    usuario = body.get("usuario", "sistema")
    validos = {"pendente_validacao", "em_andamento", "aguardando", "sem_contrato", "concluido"}
    if novo not in validos:
        return json_response({"erro": f"Status inválido. Válidos: {validos}"}, 400)
    conn = conectar()
    proc = conn.execute("SELECT id, status FROM processos WHERE processo = ?", [numero]).fetchone()
    if not proc:
        conn.close()
        return json_response({"erro": "Processo não encontrado"}, 404)
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
    return json_response({"ok": True, "status_anterior": anterior, "status_novo": novo})


@app.route("/api/processos/<path:numero>/laudo", methods=["POST"])
@requer_auth
def api_post_laudo(numero):
    body = get_body()
    usuario = body.get("usuario", "sistema")

    campos = [
        "produto", "autor", "resumo_causa", "causa_raiz", "advogado_agressor",
        "adv_agressor",
        "nome_cliente", "endereco", "analfabeto", "testemunhas",
        "subsidios_fav", "estrategia", "resultado_tipo", "observacoes",
        # localização / contexto jurídico
        "motivo_ajuizamento", "comarca", "estado", "fase", "natureza",
        "filial", "advogado", "validacao_contrato", "validacao_obs",
        # flags e métricas
        "fl_ex_cliente", "fl_autor_contumaz", "qt_acoes",
        "fl_cumprimento_sentenca", "fl_relevante",
        "fl_falecido", "fl_adv_agressor", "duracao_meses", "qt_beneficio",
        # pessoas / organização
        "representante", "equipe", "motivo_relevancia", "categoria",
        "orgao", "juizo", "polo", "situacao_externa",
        "dt_encerramento", "motivo_encerramento",
        "departamento", "divisao",
        # valores editáveis pelo analista
        "vl_causa", "vl_descontos", "vl_beneficio", "nr_beneficio",
        "advogado_quarteirizado",
        # checklist
        "ck_bo", "ck_analfabeto", "ck_terceiros", "ck_primeira_tx",
        "ck_biometria_leg", "ck_biometria_ok", "ck_docs_ok", "ck_conta_agi",
        "ck_compras", "ck_compras_anormais", "ck_ted", "ck_saque_cartao",
        "ck_uso_cartao", "ck_pagamento_fatura", "ck_valor_conta", "ck_spc",
        "ck_procuracao", "ck_comprov_end", "ck_outras_acoes", "ck_passagens",
        # sistemas
        "appsmith_qtd", "conductor_qtd", "fraud_qtd", "ged_qtd",
        "matera_qtd", "recupera_qtd", "salesforce_qtd", "biometria_qtd",
    ]

    conn = conectar()
    proc = conn.execute("SELECT id FROM processos WHERE processo = ?", [numero]).fetchone()
    if not proc:
        conn.close()
        return json_response({"erro": "Processo não encontrado"}, 404)

    sets = ", ".join(f"{c}=?" for c in campos if c in body)
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

    if "contratos" in body and isinstance(body["contratos"], list):
        conn.execute("DELETE FROM contratos WHERE processo_id = ?", [proc["id"]])
        for ct in body["contratos"]:
            nr = ct.get("nr", "")
            prod = ct.get("prod", "")
            dt = ct.get("dt", "")
            canal = ct.get("canal", "")
            vl = ct.get("vl", "")
            if nr:
                conn.execute(
                    "INSERT INTO contratos (processo_id, nr_contrato, ds_produto, dt_contrato, vl_contrato, canal) VALUES (?,?,?,?,?,?)",
                    [proc["id"], nr, prod, dt, vl, canal]
                )

    conn.commit()
    conn.close()
    return json_response({"ok": True})


@app.route("/api/processos/<path:numero>/liberar", methods=["POST"])
@requer_auth
def api_post_liberar(numero):
    conn = conectar()
    proc = conn.execute("SELECT id FROM processos WHERE processo = ?", [numero]).fetchone()
    if not proc:
        conn.close()
        return json_response({"erro": "Processo nao encontrado"}, 404)
    conn.execute(
        "UPDATE processos SET responsavel=NULL, dt_abertura=NULL, status='em_andamento', dt_atualizacao=? WHERE processo=?",
        [agora(), numero]
    )
    conn.commit()
    conn.close()
    return json_response({"ok": True, "processo": numero})


@app.route("/api/processos/<path:numero>/gerar-laudo", methods=["POST"])
@requer_auth
def api_post_gerar_laudo(numero):
    body = get_body()

    conn = conectar()
    proc = conn.execute("SELECT * FROM processos WHERE processo = ?", [numero]).fetchone()
    cts = conn.execute("SELECT * FROM contratos WHERE processo_id = ?", [proc["id"]]).fetchall() if proc else []
    conn.close()

    if not proc:
        return json_response({"erro": "Processo nao encontrado"}, 404)

    dados = dict(proc)
    dados.update({k: v for k, v in body.items() if v is not None and v != ""})

    dados["data_dist"] = dados.get("data_dist") or dados.get("dt_inclusao", "")
    dados["autor"] = dados.get("autor") or dados.get("nome_cliente", "")
    dados["cpf"] = dados.get("cpf") or dados.get("nr_cpf_cnpj", "")
    dados["endereco"] = dados.get("endereco", "")
    dados["produto"] = dados.get("produto", "") or dados.get("produto_principal", "")
    dados["causa_raiz"] = dados.get("causa_raiz", "")
    dados["responsavel"] = dados.get("responsavel", "") or dados.get("usuario", "")

    dl = dados.get("data_laudo", "")
    if dl:
        if len(dl) == 10 and dl[4] == "-":
            dl = dl[8:10] + "/" + dl[5:7] + "/" + dl[0:4]
    else:
        dl = datetime.today().strftime("%d/%m/%Y")
    dados["data_laudo"] = dl

    for _ck in ["ck_bo", "ck_analfabeto", "ck_terceiros", "ck_primeira_tx",
                "ck_biometria_leg", "ck_biometria_ok", "ck_docs_ok", "ck_conta_agi",
                "ck_compras", "ck_compras_anormais", "ck_ted", "ck_saque_cartao",
                "ck_uso_cartao", "ck_pagamento_fatura", "ck_valor_conta", "ck_spc",
                "ck_procuracao", "ck_comprov_end", "ck_outras_acoes", "ck_passagens"]:
        if not dados.get(_ck):
            dados[_ck] = ""

    for _s in ["appsmith_qtd", "conductor_qtd", "fraud_qtd", "ged_qtd",
               "matera_qtd", "recupera_qtd", "salesforce_qtd", "biometria_qtd"]:
        if not dados.get(_s):
            dados[_s] = "0"

    if body.get("contratos"):
        dados["contratos"] = body["contratos"]
    else:
        dados["contratos"] = [
            {"nr": ct["nr_contrato"], "prod": ct["ds_produto"],
             "dt": ct["dt_contrato"], "vl": ct.get("vl_contrato", ""),
             "canal": ct.get("canal", "")}
            for ct in cts
        ]

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
                        b64 = "data:" + (row["tipo"] or "image/png") + ";base64," + base64.b64encode(raw).decode()
                        dados["anexos"][app_id].append({
                            "nome": row["nome"], "tipo": row["tipo"], "data": b64
                        })
            except Exception:
                if conn2:
                    try:
                        conn2.close()
                    except Exception:
                        pass

    script_path = os.path.join(DIR_BASE, "gerar_laudo_pdf.py")
    if not os.path.exists(script_path):
        return json_response({"erro": "gerar_laudo_pdf.py nao encontrado na pasta do sistema"}, 500)

    try:
        spec = importlib.util.spec_from_file_location("gerar_laudo_pdf", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        pdf_bytes = mod.gerar_pdf(dados, "buffer")
    except Exception as ex:
        return json_response({"erro": f"Erro ao gerar PDF: {ex}"}, 500)

    nome_arquivo = f"laudo_{numero.replace('/', '_').replace(' ', '_')}.pdf"

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
        pass

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=nome_arquivo,
    )


@app.route("/api/processos/<path:numero>/mover", methods=["POST"])
@requer_auth
def api_post_mover(numero):
    body = get_body()
    novo_status = body.get("status", "")
    usuario = body.get("usuario", "sistema")
    validos = {"pendente_validacao", "em_andamento", "aguardando", "concluido", "sem_contrato"}
    if novo_status not in validos:
        return json_response({"erro": f"Status invalido: {novo_status}"}, 400)
    conn = conectar()
    proc = conn.execute("SELECT id, status FROM processos WHERE processo=?", [numero]).fetchone()
    if not proc:
        conn.close()
        return json_response({"erro": "Processo nao encontrado"}, 404)
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
    return json_response({"ok": True, "processo": numero, "status": novo_status})


@app.route("/api/processos/<path:numero>/anexos", methods=["POST"])
@requer_auth
def api_post_salvar_anexo(numero):
    body = get_body()
    app_id = body.get("app_id", "")
    nome = body.get("nome", "anexo")
    tipo = body.get("tipo", "image/png")
    data = body.get("data", "")

    if not data:
        return json_response({"erro": "Dados do arquivo nao enviados"}, 400)

    conn = conectar()
    proc = conn.execute("SELECT id FROM processos WHERE processo=?", [numero]).fetchone()
    if not proc:
        conn.close()
        return json_response({"erro": "Processo nao encontrado"}, 404)

    try:
        b64 = data.split(",", 1)[1] if "," in data else data
        raw = base64.b64decode(b64)
    except Exception as e:
        conn.close()
        return json_response({"erro": f"Erro ao decodificar: {e}"}, 400)

    ext = ".png" if "png" in tipo else ".jpg" if "jp" in tipo else ".pdf"
    nome_arquivo = f"{numero.replace('/', '_')}_{app_id}_{uuid.uuid4().hex[:8]}{ext}"
    caminho = os.path.join(ANEXOS_DIR, nome_arquivo)
    with open(caminho, "wb") as f:
        f.write(raw)

    cur = conn.execute(
        "INSERT INTO anexos (processo_id, app_id, nome, tipo, caminho, conteudo, dt_criacao) VALUES (?,?,?,?,?,?,?)",
        [proc["id"], app_id, nome, tipo, caminho, raw, agora()]
    )
    anexo_id = cur.lastrowid
    conn.commit()
    conn.close()
    return json_response({"ok": True, "id": anexo_id})


@app.route("/api/anexos/<int:anexo_id>/deletar", methods=["POST"])
@requer_auth
def api_post_deletar_anexo(anexo_id):
    conn = conectar()
    row = conn.execute("SELECT caminho FROM anexos WHERE id=?", [anexo_id]).fetchone()
    if row:
        try:
            os.unlink(row["caminho"])
        except Exception:
            pass
        conn.execute("DELETE FROM anexos WHERE id=?", [anexo_id])
        conn.commit()
    conn.close()
    return json_response({"ok": True})


@app.route("/api/admin/usuarios", methods=["POST"])
@requer_auth
def api_post_criar_usuario():
    body = get_body()
    login = body.get("login", "").strip()
    nome = body.get("nome", "").strip()
    senha = body.get("senha", "")
    admin_v = int(body.get("admin", 0))

    if not login or not nome or not senha:
        return json_response({"erro": "Login, nome e senha sao obrigatorios"}, 400)

    conn = conectar()
    try:
        conn.execute(
            "INSERT INTO usuarios (login, nome, senha_hash, admin) VALUES (?,?,?,?)",
            [login, nome, hashlib.sha256(senha.encode()).hexdigest(), admin_v]
        )
        conn.commit()
        return json_response({"ok": True})
    except Exception:
        return json_response({"erro": f"Login ja existe: {login}"}, 400)
    finally:
        conn.close()


@app.route("/api/admin/usuarios/<path:login_u>", methods=["POST"])
@requer_auth
def api_post_editar_usuario(login_u):
    body = get_body()
    acao = body.get("acao", "")
    conn = conectar()
    try:
        if acao == "senha":
            nova = body.get("senha", "")
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
                         [int(body.get("valor", 0)), login_u])
        conn.commit()
        return json_response({"ok": True})
    except Exception as e:
        return json_response({"erro": str(e)}, 500)
    finally:
        conn.close()


@app.route("/api/admin/reimportar", methods=["POST"])
@requer_auth
def api_post_reimportar():
    arq1 = os.path.join(DIR_BASE, "data.xlsx")
    arq2 = os.path.join(DIR_BASE, "data (7).xlsx")

    if not os.path.exists(arq1):
        return json_response({"erro": "Arquivo não encontrado: data.xlsx"}, 404)

    try:
        import importar_excel as _mod_imp
        from contextlib import redirect_stdout

        _mod_imp.DB_ARQUIVO = DB_ARQUIVO

        buf = io.StringIO()
        with redirect_stdout(buf):
            _mod_imp.importar(arq1, arq2 if os.path.exists(arq2) else None)

        log = buf.getvalue()
        inseridos = 0
        atualizados = 0
        ignorados = 0
        for line in log.splitlines():
            if "Inseridos:" in line:
                try:
                    inseridos = int(line.split(":")[1].strip())
                except Exception:
                    pass
            elif "Atualizados:" in line:
                try:
                    atualizados = int(line.split(":")[1].strip())
                except Exception:
                    pass
            elif "Ignorados:" in line:
                try:
                    ignorados = int(line.split(":")[1].strip())
                except Exception:
                    pass

        return json_response({
            "ok": True,
            "inseridos": inseridos,
            "atualizados": atualizados,
            "ignorados": ignorados,
            "log": log,
        })
    except Exception as ex:
        return json_response({"erro": f"Erro ao reimportar: {ex}"}, 500)


# ─────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────
try:
    criar_tabelas()
except Exception as _e:
    import sys
    print(f"AVISO: falha ao inicializar tabelas no boot ({_e}). "
          "Workers continuarão; nova tentativa será feita sob demanda.",
          file=sys.stderr)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
