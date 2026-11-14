"""Conexao com o PostgreSQL (Neon) e registro de execucoes na tabela de log."""
import json
import logging

import psycopg2

log = logging.getLogger(__name__)


def conectar(cfg):
    pg = cfg["postgres"]
    return psycopg2.connect(
        host=pg["host"],
        port=pg.get("port", "5432"),
        dbname=pg["database"],
        user=pg["user"],
        password=pg["password"],
        sslmode=pg.get("sslmode", "require"),
        connect_timeout=30,
        keepalives=1,
        keepalives_idle=30,
    )


class Execucao:
    """Registra inicio e fim de um processo em qualidade.log_execucao.

    Usa uma conexao propria em autocommit: se o processo falhar e a transacao
    de carga sofrer rollback, o registro da execucao (e do erro) permanece.
    """

    def __init__(self, cfg, processo, fonte, recurso=None):
        self.cfg, self.processo, self.fonte, self.recurso = cfg, processo, fonte, recurso
        self.id = None
        self.lidas = 0
        self.gravadas = 0
        self.detalhes = {}
        self.avisos = []

    def _log_conn(self):
        c = conectar(self.cfg)
        c.autocommit = True
        return c

    def __enter__(self):
        c = self._log_conn()
        try:
            with c.cursor() as cur:
                cur.execute(
                    "INSERT INTO qualidade.log_execucao (processo, fonte, recurso) "
                    "VALUES (%s, %s, %s) RETURNING id_execucao",
                    (self.processo, self.fonte, self.recurso),
                )
                self.id = cur.fetchone()[0]
        finally:
            c.close()
        log.info("Execucao %s iniciada (%s)", self.id, self.processo)
        return self

    def aviso(self, msg):
        log.warning(msg)
        self.avisos.append(msg)

    def _fechar(self, status, erro=None):
        if self.avisos:
            self.detalhes["avisos"] = self.avisos
        c = self._log_conn()
        try:
            with c.cursor() as cur:
                cur.execute(
                    "UPDATE qualidade.log_execucao SET fim = now(), linhas_lidas = %s, "
                    "linhas_gravadas = %s, status = %s, erro = %s, detalhes = %s "
                    "WHERE id_execucao = %s",
                    (self.lidas, self.gravadas, status, erro,
                     json.dumps(self.detalhes, default=str), self.id),
                )
        finally:
            c.close()

    def __exit__(self, tipo, exc, tb):
        if exc is not None:
            self._fechar("ERRO", f"{tipo.__name__}: {exc}"[:2000])
            log.error("Execucao %s terminou com ERRO: %s", self.id, exc)
            return False  # propaga a excecao
        if self.lidas == 0:
            status = "VAZIO"
        elif self.avisos:
            status = "OK_COM_AVISOS"
        else:
            status = "OK"
        self._fechar(status)
        log.info("Execucao %s: %s (lidas=%s, gravadas=%s)", self.id, status, self.lidas, self.gravadas)
        return False
