/* =====================================================================
   ETAPA 1 - DDL da extracao (PostgreSQL / Neon)
   Idempotente: pode ser executado mais de uma vez.

   Camadas
     raw        dado exatamente como chegou da fonte (jsonb) + metadados
     stg        dado tratado, tipado, com chave e grao definidos
     qualidade  log de execucoes (e, na etapa 2, metricas de qualidade)

   Execute pelo DBeaver (Alt+X) ou: psql -f sql/02_extracao/01_ddl_extracao.sql
   ===================================================================== */

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS qualidade;


/* ---------------------------------------------------------------------
   LOG DE EXECUCAO (uma linha por execucao de cada processo)
   --------------------------------------------------------------------- */
CREATE TABLE IF NOT EXISTS qualidade.log_execucao (
    id_execucao      BIGSERIAL    PRIMARY KEY,
    processo         TEXT         NOT NULL,            -- ex.: ccee_pld_extracao, ccee_pld_tratamento
    fonte            TEXT         NOT NULL,            -- CCEE | OPEN_METEO
    recurso          TEXT,                              -- resource_id, usina etc.
    inicio           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    fim              TIMESTAMPTZ,
    linhas_lidas     INTEGER      NOT NULL DEFAULT 0,
    linhas_gravadas  INTEGER      NOT NULL DEFAULT 0,
    status           TEXT         NOT NULL DEFAULT 'EXECUTANDO'
                     CHECK (status IN ('EXECUTANDO','OK','OK_COM_AVISOS','ERRO','VAZIO')),
    erro             TEXT,
    detalhes         JSONB
);
CREATE INDEX IF NOT EXISTS ix_log_execucao_processo ON qualidade.log_execucao (processo, inicio DESC);


/* ---------------------------------------------------------------------
   CCEE - PLD HORARIO
   RAW   grao: 1 registro devolvido pela API (um submercado x uma hora)
         payload = registro CKAN sem alteracao; row_hash evita duplicar
         o que ja foi baixado em execucoes anteriores.
   STG   grao: 1 submercado x 1 hora (inicio da hora, horario de Brasilia)
   --------------------------------------------------------------------- */
CREATE TABLE IF NOT EXISTS raw.ccee_pld_horario (
    id_raw        BIGSERIAL    PRIMARY KEY,
    id_execucao   BIGINT       NOT NULL REFERENCES qualidade.log_execucao (id_execucao),
    resource_id   TEXT         NOT NULL,
    ano_recurso   SMALLINT,
    fonte_url     TEXT         NOT NULL,
    extraido_em   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    row_hash      TEXT         NOT NULL,
    payload       JSONB        NOT NULL,
    UNIQUE (resource_id, row_hash)
);
CREATE INDEX IF NOT EXISTS ix_raw_ccee_resource ON raw.ccee_pld_horario (resource_id);

CREATE TABLE IF NOT EXISTS stg.pld_horario_tratado (
    cod_submercado           CHAR(2)       NOT NULL
                             REFERENCES campo_real_energia.submercado (cod_submercado),
    data_hora                TIMESTAMP     NOT NULL,   -- inicio da hora, horario de Brasilia
    mes_referencia           CHAR(6)       NOT NULL,   -- AAAAMM
    periodo_comercializacao  SMALLINT      NOT NULL,   -- 1..(24 x dias do mes)
    pld_rs_mwh               NUMERIC(10,2) NOT NULL,   -- sinal/faixa NAO sao validados aqui (etapa 2)
    ano_recurso              SMALLINT      NOT NULL,
    id_raw                   BIGINT        NOT NULL REFERENCES raw.ccee_pld_horario (id_raw),
    id_execucao              BIGINT        NOT NULL REFERENCES qualidade.log_execucao (id_execucao),
    carregado_em             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (cod_submercado, data_hora)
);

-- Registros que nao puderam ser interpretados (nao sao descartados: ficam aqui)
CREATE TABLE IF NOT EXISTS stg.pld_horario_quarentena (
    id_quarentena BIGSERIAL    PRIMARY KEY,
    id_raw        BIGINT       NOT NULL REFERENCES raw.ccee_pld_horario (id_raw),
    id_execucao   BIGINT       NOT NULL REFERENCES qualidade.log_execucao (id_execucao),
    motivo        TEXT         NOT NULL,
    registrado_em TIMESTAMPTZ  NOT NULL DEFAULT now()
);


/* ---------------------------------------------------------------------
   OPEN-METEO - CLIMA HORARIO POR USINA
   RAW   grao: 1 resposta da API (uma usina x um intervalo de datas)
   STG   grao: 1 usina x 1 hora
   --------------------------------------------------------------------- */
CREATE TABLE IF NOT EXISTS raw.openmeteo_resposta (
    id_raw        BIGSERIAL    PRIMARY KEY,
    id_execucao   BIGINT       NOT NULL REFERENCES qualidade.log_execucao (id_execucao),
    id_usina      INTEGER      NOT NULL,
    cod_usina     TEXT,
    latitude      NUMERIC(9,6) NOT NULL,   -- coordenada enviada (vinda do cadastro)
    longitude     NUMERIC(9,6) NOT NULL,
    data_inicio   DATE         NOT NULL,
    data_fim      DATE         NOT NULL,
    fonte_url     TEXT         NOT NULL,
    parametros    JSONB        NOT NULL,
    http_status   SMALLINT     NOT NULL,
    extraido_em   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    payload       JSONB        NOT NULL,
    UNIQUE (id_usina, data_inicio, data_fim)
);

CREATE TABLE IF NOT EXISTS stg.clima_horario (
    id_usina             INTEGER      NOT NULL,
    data_hora            TIMESTAMP    NOT NULL,   -- horario local (America/Sao_Paulo)
    temperatura_c        NUMERIC(5,2),
    vento_10m_ms         NUMERIC(6,2),
    vento_100m_ms        NUMERIC(6,2),
    radiacao_wm2         NUMERIC(7,2),            -- radiacao de onda curta
    chuva_mm             NUMERIC(6,2),
    id_raw               BIGINT       NOT NULL REFERENCES raw.openmeteo_resposta (id_raw),
    id_execucao          BIGINT       NOT NULL REFERENCES qualidade.log_execucao (id_execucao),
    carregado_em         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (id_usina, data_hora)
);
