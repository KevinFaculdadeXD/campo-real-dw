"""Executa os scripts SQL do data warehouse na ordem e registra a execucao em qualidade.log_execucao.

Uso (na raiz do projeto):  python -m src.dw.carregar [--config caminho]
Pre-requisitos: extracao (PLD e clima) e qualidade (python -m src.qualidade.executar) ja executadas.
Cada arquivo roda numa transacao: se um falhar, ele e desfeito e o processo para com o erro no log.
"""
import argparse
import logging
import sys
from pathlib import Path

from src.common.config import carregar_config
from src.common.db import Execucao, conectar

log = logging.getLogger(__name__)
PASTA = Path(__file__).resolve().parents[2] / "sql" / "04_dw"
ARQUIVOS = ["01_ddl_dw.sql", "02_carga_dimensoes.sql", "03_limpeza_medicao.sql", "04_carga_fatos.sql"]
TABELAS = ["dim_tempo", "dim_usina", "dim_fonte", "dim_submercado", "dim_tipo_parada",
           "fato_geracao", "fato_pld", "fato_clima", "fato_parada_hora"]


def main(argv=None):
    p = argparse.ArgumentParser(description="Carga do data warehouse")
    p.add_argument("--config")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = carregar_config(a.config)
    conn = conectar(cfg)
    try:
        with Execucao(cfg, "dw_carga", "DW", "dw_campo_real") as exe:
            exe.lidas = len(ARQUIVOS)
            for nome in ARQUIVOS:
                texto = (PASTA / nome).read_text(encoding="utf-8")
                log.info("Executando %s ...", nome)
                try:
                    with conn.cursor() as cur:
                        cur.execute(texto)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    log.error("Falhou em %s (transacao desfeita)", nome)
                    raise
            with conn.cursor() as cur:
                for t in TABELAS:
                    cur.execute(f"SELECT count(*) FROM dw_campo_real.{t}")
                    n = cur.fetchone()[0]
                    exe.detalhes[t] = n
                    log.info("%-18s %s linhas", t, f"{n:,}".replace(",", "."))
                exe.gravadas = exe.detalhes["fato_geracao"] + exe.detalhes["fato_pld"]
            conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
