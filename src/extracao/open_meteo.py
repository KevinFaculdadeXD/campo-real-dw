"""Extracao do clima horario (Open-Meteo Historical Weather API) nas coordenadas das usinas.

Fonte complementar (Obrigatorio B). Uma chamada por usina e por intervalo:
  - 2025 inteiro (intervalo fechado: baixado uma unica vez);
  - 2026 ate (hoje - defasagem_dias) (intervalo aberto: refeito quando o fim muda).

O corpo da resposta e guardado sem alteracao em raw.openmeteo_resposta; o tratamento
desempacota o JSON para stg.clima_horario (grao: usina x hora).

As coordenadas vem do cadastro (campo_real_energia.usina) SEM correcao. Coordenadas
fora do Brasil geram aviso no log, mas sao enviadas como estao: corrigir cadastro e
decisao da etapa de qualidade, nao do extrator.

Execucao (na raiz do projeto):
    python -m src.extracao.open_meteo
    python -m src.extracao.open_meteo --full         # refaz mesmo o que ja existe
    python -m src.extracao.open_meteo --so-tratar

Fonte: Open-Meteo.com (CC-BY 4.0; uso nao comercial, citar a atribuicao).
"""
import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from psycopg2.extras import Json, execute_values

from src.common.config import carregar_config
from src.common.db import Execucao, conectar
from src.common.http import ErroPermanente, get_json, nova_sessao

log = logging.getLogger("open_meteo")

VARIAVEIS_STG = {  # variavel da API -> coluna em stg.clima_horario
    "temperature_2m": "temperatura_c",
    "wind_speed_10m": "vento_10m_ms",
    "wind_speed_100m": "vento_100m_ms",
    "shortwave_radiation": "radiacao_wm2",
    "precipitation": "chuva_mm",
}
LIMITE_BRASIL = {"lat": (-34.0, 5.5), "lon": (-74.5, -34.0)}


def coord_fora_do_brasil(lat, lon):
    return not (LIMITE_BRASIL["lat"][0] <= lat <= LIMITE_BRASIL["lat"][1]
                and LIMITE_BRASIL["lon"][0] <= lon <= LIMITE_BRASIL["lon"][1])


def intervalos(cfg, hoje=None):
    hoje = hoje or date.today()
    oc = cfg["open_meteo"]
    inicio = date.fromisoformat(oc["data_inicio"])
    fim = hoje - timedelta(days=oc.getint("defasagem_dias", 6))
    out = []
    for ano in range(inicio.year, fim.year + 1):
        ini = max(inicio, date(ano, 1, 1))
        f = min(fim, date(ano, 12, 31))
        if ini <= f:
            out.append((ini, f))
    return out


def _num(v):
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def desempacotar(payload, id_usina):
    """Converte o bloco 'hourly' da resposta em linhas (uma por hora)."""
    horario = payload.get("hourly") or {}
    tempos = horario.get("time") or []
    linhas = []
    for i, t in enumerate(tempos):
        vals = [_num(horario.get(var, [None] * len(tempos))[i]) for var in VARIAVEIS_STG]
        linhas.append((id_usina, datetime.fromisoformat(t), *vals))
    return linhas


def extrair(cfg, full=False):
    oc = cfg["open_meteo"]
    origem = cfg["schemas"].get("origem", "campo_real_energia")
    variaveis = [v.strip() for v in oc["variaveis"].split(",")]
    sessao, conn, falhas = nova_sessao(cfg), conectar(cfg), 0
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id_usina, cod_usina, latitude, longitude FROM {origem}.usina ORDER BY id_usina")
            usinas = cur.fetchall()

        with Execucao(cfg, "open_meteo_extracao", "OPEN_METEO", f"{len(usinas)} usinas") as exe:
            for id_usina, cod, lat, lon in usinas:
                if lat is None or lon is None:
                    exe.aviso(f"{cod}: sem coordenadas no cadastro; usina ignorada")
                    continue
                lat, lon = float(lat), float(lon)
                if coord_fora_do_brasil(lat, lon):
                    exe.aviso(f"{cod}: coordenadas ({lat}, {lon}) fora do Brasil; enviado como esta no cadastro")
                for ini, fim in intervalos(cfg):
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1 FROM raw.openmeteo_resposta WHERE id_usina=%s AND data_inicio=%s "
                                    "AND data_fim=%s", (id_usina, ini, fim))
                        if cur.fetchone() and not full:
                            log.info("%s %s..%s ja baixado; pulando", cod, ini, fim)
                            continue
                    params = {"latitude": lat, "longitude": lon, "start_date": ini.isoformat(),
                              "end_date": fim.isoformat(), "hourly": ",".join(variaveis),
                              "timezone": oc.get("timezone", "America/Sao_Paulo"), "wind_speed_unit": "ms"}
                    try:
                        status, corpo, url = get_json(sessao, oc["api_url"], params, cfg, f"open-meteo {cod} {ini}")
                    except ErroPermanente as e:
                        falhas += 1
                        exe.aviso(f"{cod} {ini}..{fim}: {e}")
                        continue
                    if corpo.get("error") or not (corpo.get("hourly") or {}).get("time"):
                        falhas += 1
                        exe.aviso(f"{cod} {ini}..{fim}: resposta vazia/erro: {str(corpo)[:200]}")
                        continue
                    faltando = [v for v in variaveis if v not in corpo["hourly"]]
                    if faltando:
                        exe.aviso(f"{cod}: variaveis ausentes na resposta: {faltando}")
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO raw.openmeteo_resposta (id_execucao, id_usina, cod_usina, latitude, "
                            "longitude, data_inicio, data_fim, fonte_url, parametros, http_status, payload) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                            "ON CONFLICT (id_usina, data_inicio, data_fim) DO UPDATE SET "
                            "id_execucao=EXCLUDED.id_execucao, fonte_url=EXCLUDED.fonte_url, "
                            "parametros=EXCLUDED.parametros, http_status=EXCLUDED.http_status, "
                            "payload=EXCLUDED.payload, extraido_em=now()",
                            (exe.id, id_usina, cod, lat, lon, ini, fim, url, Json(params), status, Json(corpo)))
                    conn.commit()
                    exe.lidas += len(corpo["hourly"]["time"])
                    exe.gravadas += 1
                    log.info("%s %s..%s: %d horas", cod, ini, fim, len(corpo["hourly"]["time"]))
                    time.sleep(oc.getfloat("pausa_entre_chamadas_s", 2))  # respeita o limite de requisicoes
            exe.detalhes["falhas"] = falhas
    finally:
        conn.close()
    return falhas


def tratar(cfg):
    conn = conectar(cfg)
    try:
        with Execucao(cfg, "open_meteo_tratamento", "OPEN_METEO") as exe:
            with conn.cursor() as cur:
                cur.execute("SELECT id_raw, id_usina, payload FROM raw.openmeteo_resposta ORDER BY id_raw")
                respostas = cur.fetchall()
            cols = ", ".join(VARIAVEIS_STG.values())
            sql = (f"INSERT INTO stg.clima_horario (id_usina, data_hora, {cols}, id_raw, id_execucao) VALUES %s "
                   "ON CONFLICT (id_usina, data_hora) DO UPDATE SET "
                   + ", ".join(f"{c}=EXCLUDED.{c}" for c in VARIAVEIS_STG.values())
                   + ", id_raw=EXCLUDED.id_raw, id_execucao=EXCLUDED.id_execucao, carregado_em=now() "
                   "WHERE EXCLUDED.id_raw >= stg.clima_horario.id_raw")
            for id_raw, id_usina, payload in respostas:
                linhas = [(*l, id_raw, exe.id) for l in desempacotar(payload, id_usina)]
                exe.lidas += len(linhas)
                with conn.cursor() as cur:
                    for i in range(0, len(linhas), 2000):
                        lote = linhas[i:i + 2000]
                        execute_values(cur, sql, lote, page_size=len(lote))
                        exe.gravadas += cur.rowcount
                conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv=None):
    p = argparse.ArgumentParser(description="Extrai clima horario do Open-Meteo para as usinas")
    p.add_argument("--full", action="store_true")
    p.add_argument("--so-tratar", action="store_true")
    p.add_argument("--sem-tratar", action="store_true")
    p.add_argument("--config")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = carregar_config(a.config)
    falhas = 0
    if not a.so_tratar:
        falhas = extrair(cfg, a.full)
    if not a.sem_tratar:
        tratar(cfg)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
