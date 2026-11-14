"""Cliente HTTP com tempo limite, nova tentativa com espera exponencial e limite de requisicoes."""
import logging
import random
import time

import requests

log = logging.getLogger(__name__)


class ErroPermanente(Exception):
    """Erro que nao adianta tentar de novo (ex.: 400/404, resposta de erro da API)."""


class ErroTransitorioEsgotado(Exception):
    """Todas as tentativas falharam (tempo limite, 5xx, 429, JSON invalido)."""


def nova_sessao(cfg=None):
    """User-Agent: usa [http] user_agent do config; se vazio, mantem o padrao do requests
    (o mesmo do exemplo da professora)."""
    s = requests.Session()
    ua = cfg["http"].get("user_agent", "").strip() if cfg is not None and cfg.has_section("http") else ""
    if ua:
        s.headers["User-Agent"] = ua
    return s


def get_json(sessao, url, params, cfg, rotulo=""):
    h = cfg["http"]
    timeout = h.getfloat("timeout_s", 60)
    max_t = h.getint("max_tentativas", 5)
    base = h.getfloat("espera_base_s", 2)
    teto = h.getfloat("espera_max_s", 60)
    ultimo = None

    for n in range(1, max_t + 1):
        espera = min(teto, base * 2 ** (n - 1)) + random.uniform(0, 1)
        try:
            r = sessao.get(url, params=params, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            ultimo = f"{type(e).__name__}: {e}"
        else:
            if r.status_code == 429:
                ra = r.headers.get("Retry-After")
                espera = min(teto * 2, float(ra)) if ra and ra.isdigit() else max(espera, 30)
                ultimo = "HTTP 429 (limite de requisicoes)"
            elif r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}"
            elif r.status_code >= 400:
                # Open-Meteo/CKAN devolvem o motivo no corpo; guardamos para o log
                corpo = r.text.strip()
                if corpo.startswith("<"):
                    corpo = "resposta HTML (possivel bloqueio de acesso/WAF do portal)"
                raise ErroPermanente(f"HTTP {r.status_code} em {rotulo or url}: {corpo[:200]}")
            else:
                try:
                    return r.status_code, r.json(), r.url
                except ValueError:
                    ultimo = "resposta nao e JSON valido"
        if n < max_t:
            log.warning("%s tentativa %d/%d falhou (%s); nova tentativa em %.1fs",
                        rotulo or url, n, max_t, ultimo, espera)
            time.sleep(espera)
    raise ErroTransitorioEsgotado(f"{rotulo or url}: {max_t} tentativas falharam (ultimo: {ultimo})")
