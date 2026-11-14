"""Executa o profiling e todas as regras do catalogo e grava em qualidade.metricas / decisoes / perfil_colunas.

Uso (na raiz do projeto):  python -m src.qualidade.executar [--sem-perfil] [--so-perfil] [--config caminho]
Cada execucao fica registrada em qualidade.log_execucao. Uma regra que falha por erro de SQL vira
uma linha com status ERRO e as demais continuam.
"""
import argparse
import logging
import sys

from src.common.config import carregar_config
from src.common.db import Execucao, conectar
from .catalogo import construir_catalogo
from .perfil import alvos, perfilar_tabela

log = logging.getLogger(__name__)


def gravar_decisoes(cur, catalogo):
    for r in catalogo:
        cur.execute(
            "INSERT INTO qualidade.decisoes (regra, dimensao, tabela, problema, decisao, justificativa) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (regra) DO UPDATE SET dimensao = EXCLUDED.dimensao, "
            "tabela = EXCLUDED.tabela, problema = EXCLUDED.problema, decisao = EXCLUDED.decisao, "
            "justificativa = EXCLUDED.justificativa, atualizado_em = now()",
            (r.id, r.dimensao, r.tabela, r.problema, r.decisao, r.justificativa))


def rodar_regras(cur, exe, catalogo):
    resumo = []
    for r in catalogo:
        try:
            av, fa = r.medir(cur)
            pct = round(100.0 * fa / av, 4) if av else None
            status, erro = ("FALHA" if fa > 0 else "OK"), None
        except Exception as e:  # noqa: BLE001 - registra e segue para a proxima regra
            av = fa = pct = None
            status, erro = "ERRO", f"{type(e).__name__}: {e}"[:1000]
            log.error("Regra %s falhou: %s", r.id, erro)
        cur.execute(
            "INSERT INTO qualidade.metricas (id_execucao, regra, dimensao, tabela, registros_avaliados, "
            "registros_com_falha, percentual_falha, status, erro) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (exe.id, r.id, r.dimensao, r.tabela, av, fa, pct, status, erro))
        exe.gravadas += 1
        resumo.append((r.id, status, av, fa))
        if status == "ERRO":
            exe.aviso(f"{r.id}: {erro}")
    return resumo


def main(argv=None):
    p = argparse.ArgumentParser(description="Regras de qualidade e profiling")
    p.add_argument("--sem-perfil", action="store_true")
    p.add_argument("--so-perfil", action="store_true")
    p.add_argument("--config")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = carregar_config(a.config)
    origem = cfg["schemas"]["origem"]
    catalogo = construir_catalogo(origem)

    conn = conectar(cfg)
    conn.autocommit = True   # um erro de SQL em uma regra nao deve invalidar as demais
    try:
        with Execucao(cfg, "qualidade_regras", "QUALIDADE", f"{len(catalogo)} regras") as exe:
            exe.lidas = len(catalogo)
            with conn.cursor() as cur:
                gravar_decisoes(cur, catalogo)
                if not a.so_perfil:
                    resumo = rodar_regras(cur, exe, catalogo)
                    for rid, st, av, fa in resumo:
                        log.info("%-4s %-6s avaliados=%s falhas=%s", rid, st, av, fa)
                if not a.sem_perfil:
                    colunas = 0
                    for esq, tab in alvos(origem):
                        colunas += perfilar_tabela(cur, exe.id, esq, tab)
                    exe.detalhes["colunas_perfiladas"] = colunas
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
