"""Leitura de configuracao. Nenhuma credencial ou caminho fixo no codigo."""
import configparser
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def carregar_config(caminho=None) -> configparser.ConfigParser:
    caminho = Path(caminho or os.environ.get("CRE_CONFIG") or RAIZ / "config.ini")
    if not caminho.exists():
        raise FileNotFoundError(
            f"Arquivo de configuracao nao encontrado: {caminho}. "
            "Copie config.example.ini para config.ini e preencha."
        )
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(caminho, encoding="utf-8")
    if os.environ.get("CRE_PG_PASSWORD"):
        cfg["postgres"]["password"] = os.environ["CRE_PG_PASSWORD"]
    return cfg
