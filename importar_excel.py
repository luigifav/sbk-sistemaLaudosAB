"""
importar_excel.py — Importador de planilhas Excel para o banco SQLite.

Uso:
    python importar_excel.py <arq1.xlsx> [arq2.xlsx]

arq1: planilha principal (lista básica de processos/contratos)
arq2: planilha complementar com todos os campos de MAPA_PLANILHA_PARA_BANCO
"""

import os
import re
import sqlite3
import sys
from datetime import datetime

try:
    import openpyxl
except ImportError:
    print("Erro: openpyxl nao instalado. Execute: pip install openpyxl")
    sys.exit(1)

from mapa_colunas import MAPA_PLANILHA_PARA_BANCO, COLUNAS_SEM_CAMPO

DB_ARQUIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banco_laudos.db")

# Mapeamento completo para arq2: colunas da planilha → campos do banco
MAPA_PROD_ARQ2: dict[str, str] = {
    **MAPA_PLANILHA_PARA_BANCO,
    **{col_plan: col_banco for col_plan, col_banco in COLUNAS_SEM_CAMPO},
}

# Banco field names por categoria de conversão
CAMPOS_MONETARIOS  = {"vl_condenacao", "vl_causa", "vl_descontos", "vl_beneficio"}
CAMPOS_INTEIROS    = {"qt_acoes", "qt_beneficio", "duracao_meses"}
CAMPOS_FLAG_SIMRAO = {"fl_adv_agressor", "fl_falecido"}

# Campos editados pelo analista: não sobrescrever quando resumo_causa já preenchido
CAMPOS_ANALISTA = {
    "causa_raiz", "resultado_tipo", "subsidios_fav", "observacoes", "responsavel",
}


# ── Helpers de conversão ──────────────────────────────────────────────────────

def _limpar_monetario(valor):
    """Remove separadores de milhar/vírgula e converte para float. Retorna None se não conversível."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip()
    if not s or s in ("None", "nan", "#N/D", "#VALUE!", "#REF!"):
        return None
    s = re.sub(r"[R$\s]", "", s)
    if "," in s and "." in s:
        # Formato BR: "1.234,56" → "1234.56"
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # Vírgula como separador decimal: "1234,56" → "1234.56"
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _limpar_inteiro(valor):
    """Converte para int. Retorna None se não conversível."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return int(valor)
    s = str(valor).strip()
    if not s or s in ("None", "nan"):
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        try:
            return int(float(s.replace(".", "").replace(",", ".")))
        except (ValueError, TypeError):
            return None


def _flag_simrao(valor):
    """Converte 1/True → 'Sim', 0/False → 'Não'. Retorna None se não conversível."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    try:
        n = int(float(str(valor).strip()))
        return "Sim" if n == 1 else "Não" if n == 0 else None
    except (ValueError, TypeError):
        return None


def _ler_xlsx(caminho):
    """Lê planilha Excel e retorna (headers_originais, [dict_row]).
    Retorna ([], []) se o arquivo não existir ou não for um xlsx válido."""
    if not os.path.exists(caminho):
        return [], []
    try:
        wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    except Exception as exc:
        print(f"Aviso: nao foi possivel ler '{caminho}': {exc}")
        return [], []
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    headers_orig = [str(h).strip() if h is not None else "" for h in rows[0]]
    result = []
    for row in rows[1:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        result.append(dict(zip(headers_orig, list(row))))
    return headers_orig, result


def _agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Função principal ──────────────────────────────────────────────────────────

def importar(arq1, arq2=None):
    conn = sqlite3.connect(DB_ARQUIVO)
    conn.row_factory = sqlite3.Row

    inseridos   = 0
    atualizados = 0
    ignorados   = 0

    # ── arq1: planilha básica (processo, pasta, CPF, escritório, data) ────────
    if arq1:
        _, rows1 = _ler_xlsx(arq1)
        for row in rows1:
            row_low = {k.strip().lower(): v for k, v in row.items()}
            numero = str(row_low.get("processo", "") or "").strip()
            if not numero:
                ignorados += 1
                continue

            pasta = str(row_low.get("pasta", "") or "").strip()
            cpf_cnpj = str(
                row_low.get("cpf do adverso", "")
                or row_low.get("nr_cpf_cnpj", "")
                or row_low.get("cpf", "")
                or ""
            ).strip()
            escritorio = str(
                row_low.get("escritorio", "")
                or row_low.get("nm_escritorio", "")
                or ""
            ).strip()
            dt_inclusao = str(
                row_low.get("data entrada", "")
                or row_low.get("dt_inclusao", "")
                or row_low.get("data", "")
                or ""
            ).strip()

            existing = conn.execute(
                "SELECT id FROM processos WHERE processo = ?", [numero]
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE processos
                       SET pasta=?, nr_cpf_cnpj=?, nm_escritorio=?,
                           dt_inclusao=?, dt_atualizacao=?
                       WHERE id=?""",
                    [pasta, cpf_cnpj, escritorio, dt_inclusao, _agora(), existing["id"]],
                )
                atualizados += 1
            else:
                conn.execute(
                    """INSERT INTO processos
                       (processo, pasta, nr_cpf_cnpj, nm_escritorio,
                        dt_inclusao, status, dt_atualizacao)
                       VALUES (?,?,?,?,?,?,?)""",
                    [numero, pasta, cpf_cnpj, escritorio,
                     dt_inclusao, "em_andamento", _agora()],
                )
                inseridos += 1

    # ── arq2: planilha complementar com todos os campos do MAPA_PLANILHA_PARA_BANCO ──
    if arq2:
        _, rows2 = _ler_xlsx(arq2)
        for row in rows2:
            row_low = {k.strip().lower(): v for k, v in row.items()}

            # Obter número de processo usando o mapeamento
            numero = str(row_low.get("processo", "") or "").strip()
            if not numero:
                ignorados += 1
                continue

            # Construir dict {campo_banco: valor_convertido} para todos os mapeamentos
            campos: dict = {}
            for col_plan_orig, col_banco in MAPA_PROD_ARQ2.items():
                if col_banco == "processo":
                    continue
                col_plan_low = col_plan_orig.strip().lower()
                if col_plan_low not in row_low:
                    continue
                valor_raw = row_low[col_plan_low]

                if col_banco in CAMPOS_FLAG_SIMRAO:
                    campos[col_banco] = _flag_simrao(valor_raw)
                elif col_banco in CAMPOS_MONETARIOS:
                    campos[col_banco] = _limpar_monetario(valor_raw)
                elif col_banco in CAMPOS_INTEIROS:
                    campos[col_banco] = _limpar_inteiro(valor_raw)
                else:
                    v = str(valor_raw).strip() if valor_raw is not None else None
                    campos[col_banco] = v if v and v not in ("None", "nan") else None

            if not campos:
                ignorados += 1
                continue

            existing = conn.execute(
                "SELECT id, resumo_causa FROM processos WHERE processo = ?", [numero]
            ).fetchone()

            if existing:
                resumo_preenchido = bool(
                    existing["resumo_causa"]
                    and str(existing["resumo_causa"]).strip()
                )
                if resumo_preenchido:
                    # Não sobrescreve campos que o analista pode ter editado
                    campos_upd = {k: v for k, v in campos.items()
                                  if k not in CAMPOS_ANALISTA}
                else:
                    campos_upd = campos

                if campos_upd:
                    sets    = ", ".join(f"{c}=?" for c in campos_upd)
                    valores = list(campos_upd.values())
                    conn.execute(
                        f"UPDATE processos SET {sets}, dt_atualizacao=? WHERE id=?",
                        valores + [_agora(), existing["id"]],
                    )
                atualizados += 1
            else:
                campos["status"]         = "em_andamento"
                campos["dt_atualizacao"] = _agora()
                cols         = ", ".join(campos.keys())
                placeholders = ", ".join("?" * len(campos))
                conn.execute(
                    f"INSERT INTO processos ({cols}) VALUES ({placeholders})",
                    list(campos.values()),
                )
                inseridos += 1

    conn.commit()
    conn.close()

    print(f"Inseridos:   {inseridos}")
    print(f"Atualizados: {atualizados}")
    print(f"Ignorados:   {ignorados}")


# ── Ponto de entrada ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python importar_excel.py <arq1.xlsx> [arq2.xlsx]")
        sys.exit(1)

    a1 = sys.argv[1]
    a2 = sys.argv[2] if len(sys.argv) > 2 else None
    importar(a1, a2)
