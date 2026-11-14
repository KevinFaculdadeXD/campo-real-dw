"""Extracao do PLD horario da CCEE pela API CKAN do portal de dados abertos.

Fluxo
  1. Descobre o resource_id de cada ano (package_show). Pode ser fixado no config.ini.
  2. Pagina o datastore_search (limit/offset, ordenado por _id) ate a resposta vir vazia
     ou o offset alcancar o total informado pela API.
  3. Grava cada registro EXATAMENTE como chegou em raw.ccee_pld_horario (jsonb), com
     data/hora da extracao, URL de origem e resource_id.
  4. Trata o que esta no raw -> stg.pld_horario_tratado (tipos, chave e grao definidos);
     o que nao puder ser interpretado vai para stg.pld_horario_quarentena.
  5. Cada etapa registra uma linha em qualidade.log_execucao.

Execucao (na raiz do projeto):
    python -m src.extracao.ccee_pld                 # extrai e trata
    python -m src.extracao.ccee_pld --anos 2026     # so um ano
    python -m src.extracao.ccee_pld --full          # ignora o que ja foi baixado
    python -m src.extracao.ccee_pld --so-tratar     # nao chama a API
    python -m src.extracao.ccee_pld --sem-tratar    # so raw

Fonte: CCEE - Dados Abertos, conjunto PLD_HORARIO (CC-BY 4.0).
"""
import argparse
import hashlib
import json
import logging
import re
import sys
import unicodedata
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from psycopg2.extras import Json, execute_values

from src.common.config import carregar_config
from src.common.db import Execucao, conectar
from src.common.http import ErroPermanente, get_json, nova_sessao

log = logging.getLogger("ccee_pld")

COLUNAS_ESPERADAS = {"mes_referencia", "submercado", "periodo_comercializacao", "dia", "hora", "pld_hora"}
COLUNAS_TECNICAS = {"_id", "_full_text"}
# resource_id do PLD 2025 citado no script da professora (usado so se a descoberta falhar)
RESOURCE_FALLBACK = {2025: "2a180a6b-f092-43eb-9f82-a48798b803dc"}
MAX_PAGINAS = 2000  # trava de seguranca contra paginacao infinita

SUBMERCADOS = {
    "SE": "SE", "SUDESTE": "SE", "SE/CO": "SE", "SUDESTE/CENTRO-OESTE": "SE", "SUDESTE/CENTRO OESTE": "SE",
    "S": "S", "SUL": "S",
    "NE": "NE", "NORDESTE": "NE",
    "N": "N", "NORTE": "N",
}


# --------------------------------------------------------------------------
# Utilidades de interpretacao (funcoes puras, testaveis)
# --------------------------------------------------------------------------
def norm_chave(k):
    return str(k).strip().lower()


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalizar_registro(rec):
    return {norm_chave(k): v for k, v in rec.items()}


def hash_registro(rec):
    return hashlib.md5(json.dumps(rec, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def parse_submercado(v):
    if v is None:
        return None
    return SUBMERCADOS.get(_sem_acento(str(v)).strip().upper())


def parse_dia(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip() if v is not None else ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_dia_com_mes(dia, mes_referencia):
    """O CSV/API real traz DIA como numero do dia (1-31) e MES_REFERENCIA como AAAAMM.
    Se DIA ja for uma data completa, usa parse_dia."""
    s = str(dia).strip() if dia is not None else ""
    if re.fullmatch(r"\d{1,2}", s):
        m = re.fullmatch(r"(\d{4})(\d{2})", str(mes_referencia or "").strip())
        if not m:
            return None
        try:
            return date(int(m.group(1)), int(m.group(2)), int(s))
        except ValueError:  # ex.: dia 31 em mes de 30 dias
            return None
    return parse_dia(dia)


def parse_inteiro(v):
    try:
        f = float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else None


def parse_decimal(v):
    """Aceita numero JSON, '1234.56' ou '1.234,56' (formato brasileiro)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        s = repr(v)
    else:
        s = str(v).strip().replace("\r", "")
        if s == "":
            return None
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    return d.quantize(Decimal("0.01"))


def parse_registro(rec, desloc_hora=0):
    """Converte um registro cru em linha tratada. Retorna (linha | None, motivo | None)."""
    r = normalizar_registro(rec)
    sub = parse_submercado(r.get("submercado"))
    if sub is None:
        return None, f"submercado desconhecido: {r.get('submercado')!r}"
    dia = parse_dia_com_mes(r.get("dia"), r.get("mes_referencia"))
    if dia is None:
        return None, f"data invalida: dia={r.get('dia')!r} mes_referencia={r.get('mes_referencia')!r}"
    hora = parse_inteiro(r.get("hora"))
    if hora is None:
        return None, f"hora invalida: {r.get('hora')!r}"
    hora -= desloc_hora
    if not 0 <= hora <= 23:
        return None, f"hora fora de 0-23: {r.get('hora')!r}"
    pld = parse_decimal(r.get("pld_hora"))
    if pld is None:
        return None, f"PLD ausente ou nao numerico: {r.get('pld_hora')!r}"
    if abs(pld) >= Decimal("100000000"):
        return None, f"PLD fora da faixa do tipo NUMERIC(10,2): {pld}"

    data_hora = datetime.combine(dia, time(hora))
    mes = str(r.get("mes_referencia") or "").strip()
    if not re.fullmatch(r"\d{6}", mes):
        mes = data_hora.strftime("%Y%m")
    periodo = parse_inteiro(r.get("periodo_comercializacao"))
    if periodo is None:
        periodo = (dia.day - 1) * 24 + hora + 1
    return {
        "cod_submercado": sub, "data_hora": data_hora, "mes_referencia": mes,
        "periodo_comercializacao": periodo, "pld_rs_mwh": pld,
    }, None


def ano_do_recurso(res):
    texto = " ".join(str(res.get(k) or "") for k in ("name", "description", "url"))
    anos = re.findall(r"(?<!\d)(20\d{2})(?!\d)", texto)
    return int(anos[0]) if anos else None


# --------------------------------------------------------------------------
# Acesso a API
# --------------------------------------------------------------------------
def descobrir_recursos(sessao, cfg, anos):
    """Retorna ({ano: resource_id}, [avisos])."""
    c = cfg["ccee"]
    base = c["api_base"].rstrip("/")
    avisos, achados = [], {}

    for ano in anos:  # 1) fixados no config
        fixo = c.get(f"resource_id_{ano}", "").strip()
        if fixo:
            achados[ano] = fixo

    faltam = [a for a in anos if a not in achados]
    if faltam:  # 2) descoberta automatica
        try:
            _, corpo, _ = get_json(sessao, f"{base}/package_show", {"id": c.get("dataset", "pld_horario")},
                                   cfg, "package_show")
            if not corpo.get("success"):
                raise ErroPermanente(f"package_show sem sucesso: {str(corpo)[:200]}")
            for res in corpo["result"].get("resources", []):
                a = ano_do_recurso(res)
                if a in faltam and a not in achados and res.get("datastore_active", True):
                    achados[a] = res["id"]
        except Exception as e:  # noqa: BLE001 - qualquer falha cai no fallback
            avisos.append(f"descoberta via package_show falhou ({e}); usando fallback/config")

    for ano in anos:  # 3) fallback conhecido
        if ano not in achados and ano in RESOURCE_FALLBACK:
            achados[ano] = RESOURCE_FALLBACK[ano]
            avisos.append(f"resource_id de {ano} veio do fallback do script da professora")
    return achados, avisos


def _pagina(sessao, cfg, resource_id, offset, limit, ordenar=True):
    base = cfg["ccee"]["api_base"].rstrip("/")
    params = {"resource_id": resource_id, "limit": limit, "offset": offset}
    if ordenar:
        params["sort"] = "_id asc"
    _, corpo, url = get_json(sessao, f"{base}/datastore_search", params, cfg,
                             f"datastore_search {resource_id[:8]} offset={offset}")
    if not corpo.get("success"):
        raise ErroPermanente(f"datastore_search sem sucesso: {str(corpo.get('error'))[:300]}")
    return corpo["result"], url


def _inserir_lotes(cur, sql, linhas, tamanho=1000):
    total = 0
    for i in range(0, len(linhas), tamanho):
        lote = linhas[i:i + tamanho]
        execute_values(cur, sql, lote, page_size=len(lote))
        total += cur.rowcount
    return total


# --------------------------------------------------------------------------
# Etapa A: extracao -> raw
# --------------------------------------------------------------------------
def extrair_recurso(sessao, cfg, conn, exe, resource_id, ano, full=False):
    limit = cfg["ccee"].getint("page_size", 5000)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw.ccee_pld_horario WHERE resource_id = %s", (resource_id,))
        ja_baixados = cur.fetchone()[0]

    offset = 0 if full else ja_baixados
    ordenar = True
    if offset:
        log.info("%s: %d registros ja estao no raw; retomando do offset %d", ano, ja_baixados, offset)

    sql = ("INSERT INTO raw.ccee_pld_horario "
           "(id_execucao, resource_id, ano_recurso, fonte_url, row_hash, payload) VALUES %s "
           "ON CONFLICT (resource_id, row_hash) DO NOTHING")
    primeira, paginas, total_api = True, 0, None

    while paginas < MAX_PAGINAS:
        try:
            resultado, url = _pagina(sessao, cfg, resource_id, offset, limit, ordenar)
        except ErroPermanente as e:
            if primeira and ordenar:  # servidor recusou o 'sort': tenta sem ordenar, do zero
                exe.aviso(f"{ano}: API recusou sort por _id ({e}); extraindo sem ordenacao, offset 0")
                ordenar, offset = False, 0
                continue
            raise
        registros = resultado.get("records") or []
        total_api = resultado.get("total", total_api)

        if primeira:
            primeira = False
            if total_api is not None and offset > int(total_api):
                exe.aviso(f"{ano}: offset {offset} maior que o total da API ({total_api}); reiniciando do 0")
                offset = 0
                continue
            if registros:
                chaves = {norm_chave(k) for k in registros[0]} - COLUNAS_TECNICAS
                faltando, extras = COLUNAS_ESPERADAS - chaves, chaves - COLUNAS_ESPERADAS
                exe.detalhes[f"campos_{ano}"] = [f.get("id") for f in resultado.get("fields", [])]
                if extras:
                    exe.aviso(f"{ano}: colunas novas na API (ignoradas no tratamento): {sorted(extras)}")
                if faltando:
                    raise ErroPermanente(f"{ano}: colunas esperadas ausentes na API: {sorted(faltando)}")

        if not registros:  # resposta vazia: fim da paginacao
            break

        linhas = [(exe.id, resource_id, ano, url, hash_registro(r), Json(r)) for r in registros]
        with conn.cursor() as cur:
            novos = _inserir_lotes(cur, sql, linhas, tamanho=len(linhas))
        conn.commit()  # progresso preservado se uma pagina futura falhar

        exe.lidas += len(registros)
        exe.gravadas += novos
        offset += len(registros)
        paginas += 1
        log.info("%s: pagina %d ok (%d lidos, %d novos; offset=%d/%s)",
                 ano, paginas, len(registros), novos, offset, total_api)
        if total_api is not None and offset >= int(total_api):
            break
    else:
        exe.aviso(f"{ano}: interrompido pela trava de {MAX_PAGINAS} paginas")

    exe.detalhes[f"total_api_{ano}"] = total_api
    exe.detalhes[f"paginas_{ano}"] = paginas
    if exe.lidas == 0 and ja_baixados == 0:
        exe.aviso(f"{ano}: a API respondeu sem registros")


# --------------------------------------------------------------------------
# Etapa B: raw -> stg (tratamento)
# --------------------------------------------------------------------------
def detectar_deslocamento_hora(conn, resource_id, exe):
    """Se a hora varia de 1 a 24, desloca -1 (mesma regra do script da professora)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT min(e.v::int), max(e.v::int) FROM raw.ccee_pld_horario r, "
            "LATERAL jsonb_each_text(r.payload) AS e(k, v) "
            "WHERE r.resource_id = %s AND lower(trim(e.k)) = 'hora' AND e.v ~ '^[0-9]+$'",
            (resource_id,))
        mn, mx = cur.fetchone()
    if mx == 24 and mn is not None and mn >= 1:
        exe.aviso(f"{resource_id[:8]}: HORA vai de {mn} a {mx}; aplicando deslocamento de -1h")
        return 1
    if mx == 24:
        exe.aviso(f"{resource_id[:8]}: HORA mistura 0 e 24; registros com 24 irao para quarentena")
    return 0


def tratar_recurso(cfg, conn, exe, resource_id, ano):
    desloc = detectar_deslocamento_hora(conn, resource_id, exe)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT r.id_raw, r.payload FROM raw.ccee_pld_horario r "
            "WHERE r.resource_id = %s "
            "  AND NOT EXISTS (SELECT 1 FROM stg.pld_horario_tratado t WHERE t.id_raw = r.id_raw) "
            "  AND NOT EXISTS (SELECT 1 FROM stg.pld_horario_quarentena q WHERE q.id_raw = r.id_raw) "
            "ORDER BY r.id_raw", (resource_id,))
        pendentes = cur.fetchall()

    exe.lidas = len(pendentes)
    boas, ruins, duplicadas = {}, [], 0
    for id_raw, payload in pendentes:
        linha, motivo = parse_registro(payload, desloc)
        if linha is None:
            ruins.append((id_raw, exe.id, motivo[:500]))
            continue
        chave = (linha["cod_submercado"], linha["data_hora"])
        if chave in boas:
            # repetido para o mesmo submercado/hora: o id_raw maior (mais recente) prevalece;
            # o anterior vai para a quarentena para que a decisao fique rastreavel
            duplicadas += 1
            ruins.append((boas[chave][6], exe.id, f"repetido para mesmo submercado/hora; prevaleceu id_raw {id_raw}"))
        boas[chave] = (linha["cod_submercado"], linha["data_hora"], linha["mes_referencia"],
                       linha["periodo_comercializacao"], linha["pld_rs_mwh"], ano, id_raw, exe.id)

    with conn.cursor() as cur:
        if ruins:
            _inserir_lotes(cur, "INSERT INTO stg.pld_horario_quarentena (id_raw, id_execucao, motivo) VALUES %s", ruins)
        exe.gravadas = _inserir_lotes(
            cur,
            "INSERT INTO stg.pld_horario_tratado (cod_submercado, data_hora, mes_referencia, "
            "periodo_comercializacao, pld_rs_mwh, ano_recurso, id_raw, id_execucao) VALUES %s "
            "ON CONFLICT (cod_submercado, data_hora) DO UPDATE SET "
            "mes_referencia = EXCLUDED.mes_referencia, periodo_comercializacao = EXCLUDED.periodo_comercializacao, "
            "pld_rs_mwh = EXCLUDED.pld_rs_mwh, ano_recurso = EXCLUDED.ano_recurso, "
            "id_raw = EXCLUDED.id_raw, id_execucao = EXCLUDED.id_execucao, carregado_em = now() "
            "WHERE EXCLUDED.id_raw > stg.pld_horario_tratado.id_raw",
            list(boas.values()))
    conn.commit()

    exe.detalhes.update({"ano": ano, "quarentena": len(ruins), "duplicadas_no_lote": duplicadas,
                         "deslocamento_hora": desloc})
    if ruins:
        exe.aviso(f"{ano}: {len(ruins)} registros enviados para a quarentena (ver stg.pld_horario_quarentena)")
    if duplicadas:
        exe.aviso(f"{ano}: {duplicadas} registros repetidos para o mesmo submercado/hora (prevaleceu o mais recente)")


# --------------------------------------------------------------------------
# Orquestracao
# --------------------------------------------------------------------------
def executar(cfg, anos, full=False, extrair=True, tratar=True):
    sessao = nova_sessao(cfg)
    conn = conectar(cfg)
    falhas = 0
    try:
        recursos, avisos_desc = ({}, [])
        if extrair:
            recursos, avisos_desc = descobrir_recursos(sessao, cfg, anos)
        else:  # so tratar: usa o que ja esta no raw
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT ano_recurso, resource_id FROM raw.ccee_pld_horario")
                recursos = {a: r for a, r in cur.fetchall() if a in anos}

        for ano in anos:
            rid = recursos.get(ano)
            if extrair:
                try:
                    with Execucao(cfg, "ccee_pld_extracao", "CCEE", rid or f"ano {ano}") as exe:
                        for a in avisos_desc:
                            exe.aviso(a)
                        if rid is None:
                            exe.aviso(f"{ano}: recurso nao encontrado no portal (ainda nao publicado?)")
                        else:
                            extrair_recurso(sessao, cfg, conn, exe, rid, ano, full)
                except Exception as e:  # noqa: BLE001 - registrado no log; segue para o proximo ano
                    conn.rollback()
                    falhas += 1
                    log.error("Extracao %s falhou: %s", ano, e)
            if tratar and rid is not None:
                try:
                    with Execucao(cfg, "ccee_pld_tratamento", "CCEE", rid) as exe:
                        tratar_recurso(cfg, conn, exe, rid, ano)
                except Exception as e:  # noqa: BLE001
                    conn.rollback()
                    falhas += 1
                    log.error("Tratamento %s falhou: %s", ano, e)
    finally:
        conn.close()
    return falhas


def main(argv=None):
    p = argparse.ArgumentParser(description="Extrai o PLD horario da CCEE (API CKAN)")
    p.add_argument("--anos", nargs="+", type=int, help="padrao: o definido em [ccee] anos")
    p.add_argument("--full", action="store_true", help="ignora o que ja esta no raw")
    p.add_argument("--so-tratar", action="store_true", help="nao chama a API; so raw -> stg")
    p.add_argument("--sem-tratar", action="store_true", help="so extrai para o raw")
    p.add_argument("--config", help="caminho do config.ini")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = carregar_config(a.config)
    anos = a.anos or [int(x) for x in cfg["ccee"]["anos"].split(",")]
    falhas = executar(cfg, anos, a.full, extrair=not a.so_tratar, tratar=not a.sem_tratar)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
