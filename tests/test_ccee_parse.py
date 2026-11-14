"""Testes das funcoes puras de interpretacao do PLD (rodar na raiz: PYTHONPATH=. python tests/test_ccee_parse.py  (ou python -m pytest tests -q))."""
from datetime import datetime
from decimal import Decimal

from src.extracao.ccee_pld import (ano_do_recurso, parse_decimal, parse_dia, parse_registro, parse_submercado)


def test_decimal_formatos():
    assert parse_decimal("1.234,56") == Decimal("1234.56")
    assert parse_decimal("58,6") == Decimal("58.60")
    assert parse_decimal("212.07") == Decimal("212.07")
    assert parse_decimal(205.5) == Decimal("205.50")
    assert parse_decimal("") is None and parse_decimal("abc") is None and parse_decimal("NaN") is None


def test_dia_formatos():
    assert parse_dia("01/02/2025").month == 2
    assert parse_dia("2026-01-05T00:00:00").day == 5
    assert parse_dia("32/13/2025") is None


def test_submercado():
    assert parse_submercado("Sudeste") == "SE" and parse_submercado(" nordeste ") == "NE"
    assert parse_submercado("SE/CO") == "SE" and parse_submercado("??") is None


def test_registro_hora_deslocada_e_chaves_maiusculas():
    rec = {"MES_REFERENCIA": "202601", "SUBMERCADO": "SUL", "DIA": "01/01/2026", "HORA": "24", "PLD_HORA": "100,5"}
    linha, motivo = parse_registro(rec, desloc_hora=1)
    assert motivo is None and linha["data_hora"] == datetime(2026, 1, 1, 23) and linha["periodo_comercializacao"] == 24
    assert parse_registro(rec, desloc_hora=0)[0] is None  # hora 24 sem deslocamento -> quarentena


def test_registro_formato_real_dia_numerico():
    rec = {"DIA": "31", "HORA": "0", "PLD_HORA": "205.25", "SUBMERCADO": "NORDESTE",
           "MES_REFERENCIA": "202512", "PERIODO_COMERCIALIZACAO": "721"}
    linha, motivo = parse_registro(rec)
    assert motivo is None and linha["data_hora"] == datetime(2025, 12, 31, 0)
    assert linha["cod_submercado"] == "NE" and linha["pld_rs_mwh"] == Decimal("205.25")
    assert parse_registro({**rec, "MES_REFERENCIA": "202511"})[0] is None  # 31/11 nao existe


def test_ano_do_recurso():
    assert ano_do_recurso({"name": "pld_horario_2026"}) == 2026
    assert ano_do_recurso({"name": "PLD horario", "url": "x/2025/y.csv"}) == 2025
    assert ano_do_recurso({"name": "sem ano"}) is None


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_"):
            fn(); print("ok", nome)
