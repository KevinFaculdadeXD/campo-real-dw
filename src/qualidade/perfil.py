"""Profiling por coluna: tipo, nulos, distintos, minimo, maximo, media e distribuicao (colunas de poucos valores)."""
import json
import logging

log = logging.getLogger(__name__)

COMPARAVEIS = {"integer", "smallint", "bigint", "numeric", "real", "double precision", "date",
               "timestamp without time zone", "timestamp with time zone", "character", "character varying", "text"}
NUMERICOS = {"integer", "smallint", "bigint", "numeric", "real", "double precision"}
MAX_CATEGORIAS = 12


def alvos(origem):
    tabelas_origem = ["submercado", "fonte_energia", "usina", "feriado_nacional",
                      "parada_usina", "medicao_geracao", "log_carga"]
    return [(origem, t) for t in tabelas_origem] + [("stg", "pld_horario_tratado"), ("stg", "clima_horario")]


def perfilar_tabela(cur, id_execucao, esquema, tabela):
    cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (esquema, tabela))
    colunas = cur.fetchall()
    n = 0
    for col, tipo in colunas:
        q = f'"{col}"'
        partes = ["count(*)", f"count({q})"]
        partes.append("NULL" if tipo == "json" else f"count(DISTINCT {q})")
        partes.append(f"min({q})::text" if tipo in COMPARAVEIS else "NULL")
        partes.append(f"max({q})::text" if tipo in COMPARAVEIS else "NULL")
        partes.append(f"avg({q})" if tipo in NUMERICOS else "NULL")
        cur.execute(f'SELECT {", ".join(partes)} FROM "{esquema}"."{tabela}"')
        linhas, nao_nulos, distintos, mn, mx, media = cur.fetchone()
        distribuicao = None
        if distintos is not None and 0 < distintos <= MAX_CATEGORIAS:
            cur.execute(f'SELECT {q}::text, count(*) FROM "{esquema}"."{tabela}" '
                        f'GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {MAX_CATEGORIAS}')
            distribuicao = json.dumps({str(k): v for k, v in cur.fetchall()})
        cur.execute(
            "INSERT INTO qualidade.perfil_colunas (id_execucao, esquema, tabela, coluna, tipo, linhas, nulos, "
            "distintos, minimo, maximo, media, distribuicao) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (id_execucao, esquema, tabela, col, tipo, linhas, linhas - nao_nulos, distintos, mn, mx, media,
             distribuicao))
        n += 1
    return n
