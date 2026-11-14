"""Gera docs/relatorio_qualidade.md a partir das tabelas do banco (metricas, decisoes e antes x depois).

Uso: python -m src.qualidade.relatorio   (depois de qualidade.executar e dw.carregar)
"""
import logging
import sys
from pathlib import Path

from src.common.config import carregar_config
from src.common.db import conectar

SAIDA = Path(__file__).resolve().parents[2] / "docs" / "relatorio_qualidade.md"
ORDEM = ["completude", "unicidade", "validade", "consistencia", "acuracia", "integridade_referencial", "atualidade"]


def _n(v, casas=0):
    if v is None:
        return "-"
    return f"{float(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    logging.basicConfig(level=logging.INFO)
    conn = conectar(carregar_config())
    cur = conn.cursor()
    cur.execute("""SELECT m.regra, m.dimensao, m.tabela, d.problema, m.registros_avaliados, m.registros_com_falha,
                          m.percentual_falha, m.status, d.decisao, d.justificativa
                   FROM qualidade.v_metricas_ultimo_lote m LEFT JOIN qualidade.decisoes d ON d.regra = m.regra
                   ORDER BY m.regra""")
    regras = cur.fetchall()
    cur.execute("SELECT dimensao, round(avg(indice_pct), 2) FROM dw_campo_real.qualidade_indice GROUP BY 1")
    indices = dict(cur.fetchall())
    cur.execute("""SELECT cod_usina, usina, geracao_antes_mwh, geracao_depois_mwh, receita_antes_rs, receita_depois_rs,
                          delta_receita_pct, preco_capturado_antes, preco_capturado_depois
                   FROM dw_campo_real.qualidade_antes_depois ORDER BY (cod_usina = 'TOTAL') DESC, cod_usina""")
    ad = cur.fetchall()
    cur.execute("SELECT tratamento, destino, linhas, energia_original_mwh, energia_final_mwh "
                "FROM dw_campo_real.qualidade_impacto_tratamento ORDER BY linhas DESC")
    imp = cur.fetchall()
    conn.close()

    L = ["# Relatório de qualidade de dados", "",
         "Gerado automaticamente a partir de `qualidade.metricas`, `qualidade.decisoes` e das tabelas "
         "`qualidade_antes_depois` e `qualidade_impacto_tratamento` do DW.", "",
         "## Índice por dimensão (100 × (1 − falhas / avaliados))", "",
         "| Dimensão | Índice (%) |", "|---|---|"]
    L += [f"| {d} | {_n(indices.get(d), 2)} |" for d in ORDEM if d in indices]
    L += ["", "## Problemas por dimensão, decisão e justificativa", ""]
    for dim in ORDEM:
        linhas = [r for r in regras if r[1] == dim]
        if not linhas:
            continue
        L += [f"### {dim.replace('_', ' ').capitalize()}", "",
              "| Regra | Tabela | Problema | Avaliados | Falhas | % | Decisão | Justificativa |", "|---|---|---|---|---|---|---|---|"]
        for r in linhas:
            L.append(f"| {r[0]} | {r[2]} | {r[3]} | {_n(r[4])} | {_n(r[5])} | {_n(r[6], 3)} | "
                     f"{r[8]} | {(r[9] or '').replace('|', '/')} |")
        L.append("")
    L += ["## Impacto na geração (o que aconteceu com cada leitura de origem)", "",
          "| Tratamento | Destino | Linhas | Energia original (MWh) | Energia final (MWh) |", "|---|---|---|---|---|"]
    L += [f"| {r[0]} | {r[1]} | {_n(r[2])} | {_n(r[3], 1)} | {_n(r[4], 1)} |" for r in imp]
    L += ["", "## Antes × depois da limpeza (valoração ao PLD)", "",
          "Antes = leituras de origem como chegam, valoradas ao PLD do submercado da usina. "
          "Depois = fato_geracao do DW.", "",
          "| Usina | Geração antes (MWh) | Geração depois (MWh) | Receita antes (R$) | Receita depois (R$) | Δ receita % | Preço capt. antes | Preço capt. depois |",
          "|---|---|---|---|---|---|---|---|"]
    L += [f"| {r[1]} | {_n(r[2], 1)} | {_n(r[3], 1)} | {_n(r[4], 2)} | {_n(r[5], 2)} | {_n(r[6], 2)} | "
          f"{_n(r[7], 2)} | {_n(r[8], 2)} |" for r in ad]
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Relatório gravado em {SAIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
