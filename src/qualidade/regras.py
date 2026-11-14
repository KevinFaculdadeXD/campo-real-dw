"""Regras de qualidade reutilizaveis.

Cada fabrica abaixo devolve uma funcao medir(cur) -> (registros_avaliados, registros_com_falha).
Os nomes de tabela e as condicoes sao passados por quem monta o catalogo (catalogo.py), entao a
mesma fabrica serve para varias tabelas. Nada aqui altera dados: so le e conta.
"""
from dataclasses import dataclass
from typing import Callable

DIMENSOES = ("completude", "unicidade", "validade", "consistencia", "acuracia",
             "integridade_referencial", "atualidade")
DECISOES = ("corrigir", "descartar", "quarentena", "sinalizar")


@dataclass(frozen=True)
class Regra:
    id: str
    dimensao: str
    tabela: str
    problema: str
    medir: Callable
    decisao: str
    justificativa: str

    def __post_init__(self):
        assert self.dimensao in DIMENSOES, f"{self.id}: dimensao invalida {self.dimensao}"
        assert self.decisao in DECISOES, f"{self.id}: decisao invalida {self.decisao}"
        assert self.justificativa.strip(), f"{self.id}: decisao sem justificativa"


def _um(cur, sql):
    cur.execute(sql)
    return int(cur.fetchone()[0] or 0)


def _par(cur, sql):
    cur.execute(sql)
    a, b = cur.fetchone()
    return int(a or 0), int(b or 0)


# ---------------------------------------------------------------- fabricas genericas
def condicao(de, falha, base="TRUE"):
    """Avaliados = linhas de `de` que satisfazem `base`; falhas = as que tambem satisfazem `falha`."""
    def medir(cur):
        av = _um(cur, f"SELECT count(*) FROM {de} WHERE ({base})")
        fa = _um(cur, f"SELECT count(*) FROM {de} WHERE ({base}) AND ({falha})")
        return av, fa
    return medir


def nulos(tabela, coluna, base="TRUE", considerar_vazio=False):
    cond = f"{coluna} IS NULL"
    if considerar_vazio:
        cond += f" OR btrim({coluna}::text) = ''"
    return condicao(tabela, cond, base)


def duplicados(tabela, chaves, base="TRUE"):
    """Falhas = linhas excedentes: total - numero de grupos distintos da chave."""
    def medir(cur):
        av = _um(cur, f"SELECT count(*) FROM {tabela} WHERE ({base})")
        grupos = _um(cur, f"SELECT count(*) FROM (SELECT 1 FROM {tabela} WHERE ({base}) GROUP BY {chaves}) g")
        return av, av - grupos
    return medir


def orfaos(filho, col, pai, col_pai, base="TRUE"):
    """Integridade referencial: valor preenchido em `col` que nao existe em pai.col_pai."""
    def medir(cur):
        av = _um(cur, f"SELECT count(*) FROM {filho} f WHERE f.{col} IS NOT NULL AND ({base})")
        fa = _um(cur, f"SELECT count(*) FROM {filho} f WHERE f.{col} IS NOT NULL AND ({base}) "
                      f"AND NOT EXISTS (SELECT 1 FROM {pai} p WHERE p.{col_pai} = f.{col})")
        return av, fa
    return medir


def lacunas_horarias(de, chave, ts, inicio=None, fim=None, base="TRUE"):
    """Horas que deveriam existir (entidades x horas do periodo) e quantas nao existem.

    Sem inicio/fim, o periodo vai da menor a maior hora encontrada em `de`."""
    lim = (f"SELECT '{inicio}'::timestamp AS ini, '{fim}'::timestamp AS fim" if inicio
           else "SELECT min(t) AS ini, max(t) AS fim FROM base")

    def medir(cur):
        return _par(cur, f"""
            WITH base AS (SELECT {chave} AS k, {ts} AS t FROM {de}
                          WHERE ({base}) AND {chave} IS NOT NULL AND {ts} IS NOT NULL),
                 lim AS ({lim}),
                 esp AS (SELECT (SELECT count(DISTINCT k) FROM base)
                                * ((EXTRACT(EPOCH FROM (lim.fim - lim.ini)) / 3600)::bigint + 1) AS n FROM lim),
                 pres AS (SELECT count(*) AS n FROM (SELECT DISTINCT k, t FROM base, lim
                                                     WHERE t BETWEEN lim.ini AND lim.fim) d)
            SELECT esp.n, esp.n - pres.n FROM esp, pres""")
    return medir


def sequencia_repetida(origem, min_horas=6):
    """Medidor travado: `min_horas` ou mais leituras consecutivas iguais e maiores que zero."""
    def medir(cur):
        return _par(cur, f"""
            WITH d AS (SELECT DISTINCT ON (m.id_usina, m.data_hora) m.id_usina, m.data_hora, m.energia_mwh
                       FROM {origem}.medicao_geracao m JOIN {origem}.usina u ON u.id_usina = m.id_usina
                       WHERE m.energia_mwh IS NOT NULL AND m.data_hora IS NOT NULL
                       ORDER BY m.id_usina, m.data_hora, m.id_medicao),
                 x AS (SELECT id_usina, data_hora, energia_mwh,
                              (energia_mwh IS DISTINCT FROM lag(energia_mwh) OVER w) AS muda
                       FROM d WINDOW w AS (PARTITION BY id_usina ORDER BY data_hora)),
                 g AS (SELECT id_usina, energia_mwh,
                              sum(muda::int) OVER (PARTITION BY id_usina ORDER BY data_hora) AS grp FROM x),
                 r AS (SELECT count(*) AS n FROM g WHERE energia_mwh > 0
                       GROUP BY id_usina, grp HAVING count(*) >= {int(min_horas)})
            SELECT (SELECT count(*) FROM d WHERE energia_mwh > 0), (SELECT coalesce(sum(n), 0) FROM r)""")
    return medir


def outlier_robusto(origem, k=6):
    """Desvio acima de k x MAD (escala 1,4826) da mediana da mesma usina, no mesmo mes e hora do dia.

    So avalia horas com geracao positiva: zero (parada, noite, termica desligada) nao e outlier."""
    def medir(cur):
        return _par(cur, f"""
            WITH d AS (SELECT DISTINCT ON (m.id_usina, m.data_hora) m.id_usina, m.data_hora, m.energia_mwh,
                              EXTRACT(MONTH FROM m.data_hora) AS mes, EXTRACT(HOUR FROM m.data_hora) AS h
                       FROM {origem}.medicao_geracao m JOIN {origem}.usina u ON u.id_usina = m.id_usina
                       WHERE m.energia_mwh > 0 AND m.data_hora IS NOT NULL
                       ORDER BY m.id_usina, m.data_hora, m.id_medicao),
                 s AS (SELECT id_usina, mes, h, percentile_cont(0.5) WITHIN GROUP (ORDER BY energia_mwh) AS med
                       FROM d GROUP BY id_usina, mes, h),
                 dev AS (SELECT d.id_usina, d.mes, d.h, abs(d.energia_mwh - s.med) AS ad
                         FROM d JOIN s ON s.id_usina = d.id_usina AND s.mes = d.mes AND s.h = d.h),
                 m AS (SELECT id_usina, mes, h, percentile_cont(0.5) WITHIN GROUP (ORDER BY ad) AS mad
                       FROM dev GROUP BY id_usina, mes, h)
            SELECT count(*) FILTER (WHERE m.mad > 0),
                   count(*) FILTER (WHERE m.mad > 0 AND dev.ad > {float(k)} * 1.4826 * m.mad)
            FROM dev JOIN m ON m.id_usina = dev.id_usina AND m.mes = dev.mes AND m.h = dev.h""")
    return medir


def pld_vs_submercados(tabela, fator=5):
    """PLD maior que `fator` x mediana dos submercados na MESMA hora.

    Os submercados costumam andar acoplados; a mediana mensal nao serve porque, em meses de piso, a
    mediana e o proprio piso e qualquer pico normal passaria do fator."""
    def medir(cur):
        return _par(cur, f"""
            WITH med AS (SELECT data_hora, percentile_cont(0.5) WITHIN GROUP (ORDER BY pld_rs_mwh) AS mediana
                         FROM {tabela} GROUP BY data_hora)
            SELECT count(*), count(*) FILTER (WHERE t.pld_rs_mwh > {float(fator)} * m.mediana)
            FROM {tabela} t JOIN med m ON m.data_hora = t.data_hora""")
    return medir


def usinas_sem_dados_recentes(origem, ate, tolerancia_horas=24):
    """Atualidade: usinas cuja ultima hora medida esta mais de `tolerancia_horas` atras da mais recente."""
    def medir(cur):
        return _par(cur, f"""
            WITH u AS (SELECT m.id_usina, max(m.data_hora) AS mx
                       FROM {origem}.medicao_geracao m JOIN {origem}.usina c ON c.id_usina = m.id_usina
                       WHERE m.data_hora < '{ate}' GROUP BY m.id_usina)
            SELECT count(*), count(*) FILTER (WHERE mx < (SELECT max(mx) FROM u) - interval '{int(tolerancia_horas)} hours')
            FROM u""")
    return medir


def horas_pld_sem_clima(pld, clima):
    """Horas distintas do PLD posteriores a ultima hora de clima carregada."""
    def medir(cur):
        return _par(cur, f"""
            SELECT count(DISTINCT data_hora),
                   count(DISTINCT data_hora) FILTER (WHERE data_hora > (SELECT max(data_hora) FROM {clima}))
            FROM {pld}""")
    return medir


def anos_sem_feriados(pld, feriados):
    """Anos presentes no PLD que nao tem nenhum feriado cadastrado."""
    def medir(cur):
        return _par(cur, f"""
            WITH a AS (SELECT DISTINCT EXTRACT(YEAR FROM data_hora)::int AS ano FROM {pld})
            SELECT count(*), count(*) FILTER (WHERE NOT EXISTS
                (SELECT 1 FROM {feriados} f WHERE EXTRACT(YEAR FROM f.data) = a.ano))
            FROM a""")
    return medir
