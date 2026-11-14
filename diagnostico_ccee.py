"""Diagnostico do HTTP 403 da CCEE. Rode na raiz do projeto:  python diagnostico_ccee.py
Testa a API com 3 User-Agents e mostra o que o portal responde. Nao grava nada no banco."""
import requests

BASE = "https://dadosabertos.ccee.org.br/api/3/action"
URLS = [
    (f"{BASE}/package_show", {"id": "pld_horario"}),
    (f"{BASE}/datastore_search", {"resource_id": "2a180a6b-f092-43eb-9f82-a48798b803dc", "limit": 2}),
]
AGENTES = {
    "padrao do requests": None,
    "navegador": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/124.0 Safari/537.36",
    "custom (versao antiga)": "campo-real-dw/1.0 (trabalho academico)",
}
for nome, ua in AGENTES.items():
    print(f"\n=== User-Agent: {nome} ===")
    for url, params in URLS:
        s = requests.Session()
        if ua:
            s.headers["User-Agent"] = ua
        try:
            r = s.get(url, params=params, timeout=30)
            tipo = r.headers.get("Content-Type", "")
            print(f"{url.split('/')[-1]:18} HTTP {r.status_code}  {tipo[:30]}  server={r.headers.get('Server')}")
            print("   inicio:", r.text[:120].replace("\n", " "))
        except Exception as e:  # noqa: BLE001
            print(f"{url.split('/')[-1]:18} ERRO {type(e).__name__}: {e}")
