"""Contingencia: carga do PLD horario a partir do CSV publicado pela CCEE.

Usar SOMENTE quando a API do portal estiver bloqueada (HTTP 403), situacao confirmada
com a professora. Grava no MESMO raw (raw.ccee_pld_horario) e usa o MESMO tratamento do
extrator da API, entao o restante do pipeline nao muda.

O CSV pode vir de duas formas:
  --url      endereco do arquivo (campo "url" de cada recurso no package_show, ou o botao
             Baixar da pagina do recurso); o Python baixa e guarda uma copia em dados_brutos/
  --arquivo  arquivo ja baixado pelo navegador

Exemplos (na raiz do projeto):
    python -m src.extracao.ccee_pld_csv --ano 2025 --arquivo C:/caminho/pld_horario_2025.csv
    python -m src.extracao.ccee_pld_csv --ano 2026 --url https://pda-download.ccee.org.br/XXXX/content

Cada execucao registra o nome, tamanho e SHA-256 do arquivo em qualidade.log_execucao.
Fonte: CCEE - Dados Abertos, conjunto PLD_HORARIO (CC-BY 4.0).
"""
import argparse
import csv
import hashlib
import io
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from psycopg2.extras import Json

from src.common.config import RAIZ, carregar_config
from src.common.db import Execucao, conectar
from src.extracao.ccee_pld import (COLUNAS_ESPERADAS, COLUNAS_TECNICAS, _inserir_lotes, hash_registro,
                                   norm_chave, tratar_recurso)

log = logging.getLogger("ccee_pld_csv")
PASTA_BRUTOS = RAIZ / "dados_brutos"


def baixar(url, cfg):
    """Baixa o arquivo com tempo limite e novas tentativas. Retorna os bytes."""
    h = cfg["http"]
    tentativas, base = h.getint("max_tentativas", 5), h.getfloat("espera_base_s", 2)
    sessao = requests.Session()
    ua = h.get("user_agent", "").strip()
    if ua:
        sessao.headers["User-Agent"] = ua
    ultimo = None
    for n in range(1, tentativas + 1):
        try:
            r = sessao.get(url, timeout=max(h.getfloat("timeout_s", 60), 120))
            if r.status_code == 403:
                raise PermissionError("HTTP 403 ao baixar o CSV (bloqueio do portal). "
                                      "Baixe pelo navegador e use --arquivo.")
            if r.status_code >= 400 and r.status_code < 500:
                raise PermissionError(f"HTTP {r.status_code} ao baixar o CSV")
            if r.status_code == 200 and r.content:
                return r.content
            ultimo = f"HTTP {r.status_code}, {len(r.content)} bytes"
        except (requests.Timeout, requests.ConnectionError) as e:
            ultimo = f"{type(e).__name__}"
        if n < tentativas:
            espera = min(60, base * 2 ** (n - 1))
            log.warning("download tentativa %d/%d falhou (%s); nova tentativa em %.0fs", n, tentativas, ultimo, espera)
            time.sleep(espera)
    raise RuntimeError(f"download falhou apos {tentativas} tentativas (ultimo: {ultimo})")


def decodificar(conteudo):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return conteudo.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ValueError("nao foi possivel decodificar o arquivo")


def ler_csv(texto):
    """Retorna (linhas como dict de texto, delimitador, colunas). Aceita ',' ou ';'."""
    primeira = texto.splitlines()[0] if texto.strip() else ""
    delim = ";" if primeira.count(";") > primeira.count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto, newline=""), delimiter=delim)
    colunas = [c.strip() for c in (leitor.fieldnames or [])]
    leitor.fieldnames = colunas
    linhas = [{k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None}
              for row in leitor if any((v or "").strip() for v in row.values() if isinstance(v, str))]
    return linhas, delim, colunas


def carregar(cfg, ano, url=None, arquivo=None, resource_id=None, tratar=True):
    if bool(url) == bool(arquivo):
        raise SystemExit("Informe exatamente um entre --url e --arquivo")
    rid = resource_id or f"csv_pld_horario_{ano}"
    conn = conectar(cfg)
    try:
        with Execucao(cfg, "ccee_pld_csv_extracao", "CCEE", rid) as exe:
            if url:
                conteudo = baixar(url, cfg)
                PASTA_BRUTOS.mkdir(exist_ok=True)
                nome = f"pld_horario_{ano}_{datetime.now():%Y%m%d_%H%M%S}.csv"
                (PASTA_BRUTOS / nome).write_bytes(conteudo)  # copia do que foi baixado
                origem = url
            else:
                caminho = Path(arquivo)
                conteudo, nome, origem = caminho.read_bytes(), caminho.name, f"arquivo:{caminho.name}"

            texto, enc = decodificar(conteudo)
            linhas, delim, colunas = ler_csv(texto)
            exe.detalhes.update({"arquivo": nome, "bytes": len(conteudo), "encoding": enc, "delimitador": delim,
                                 "sha256": hashlib.sha256(conteudo).hexdigest(), "colunas": colunas,
                                 "modo": "CSV (contingencia: API bloqueada)"})
            exe.aviso("carga por CSV (contingencia): API da CCEE bloqueada com HTTP 403")
            if not linhas:
                raise ValueError("o CSV nao tem linhas de dados")

            chaves = {norm_chave(c) for c in colunas} - COLUNAS_TECNICAS
            faltando, extras = COLUNAS_ESPERADAS - chaves, chaves - COLUNAS_ESPERADAS
            if extras:
                exe.aviso(f"colunas novas no CSV (ignoradas no tratamento): {sorted(extras)}")
            if faltando:
                raise ValueError(f"colunas esperadas ausentes no CSV: {sorted(faltando)} (encontradas: {colunas})")

            sql = ("INSERT INTO raw.ccee_pld_horario "
                   "(id_execucao, resource_id, ano_recurso, fonte_url, row_hash, payload) VALUES %s "
                   "ON CONFLICT (resource_id, row_hash) DO NOTHING")
            registros = [(exe.id, rid, ano, origem, hash_registro(r), Json(r)) for r in linhas]
            with conn.cursor() as cur:
                for i in range(0, len(registros), 5000):
                    exe.gravadas += _inserir_lotes(cur, sql, registros[i:i + 5000], 1000)
                    conn.commit()
            exe.lidas = len(linhas)
            log.info("CSV %s: %d linhas lidas, %d novas no raw", nome, exe.lidas, exe.gravadas)

        if tratar:
            with Execucao(cfg, "ccee_pld_tratamento", "CCEE", rid) as exe:
                tratar_recurso(cfg, conn, exe, rid, ano)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv=None):
    p = argparse.ArgumentParser(description="Carga do PLD horario a partir do CSV da CCEE (contingencia)")
    p.add_argument("--ano", type=int, required=True)
    p.add_argument("--url")
    p.add_argument("--arquivo")
    p.add_argument("--resource-id", help="opcional; padrao: csv_pld_horario_<ano>")
    p.add_argument("--sem-tratar", action="store_true")
    p.add_argument("--config")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    carregar(carregar_config(a.config), a.ano, a.url, a.arquivo, a.resource_id, not a.sem_tratar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
