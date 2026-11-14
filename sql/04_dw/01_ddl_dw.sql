-- Etapa 3 · Data warehouse (star schema) no schema dw_campo_real.
-- DDL idempotente: pode rodar de novo sem perder as dimensoes (o historico SCD2 fica).
-- Ordem: 01_ddl_dw -> 02_carga_dimensoes -> 03_limpeza_medicao -> 04_carga_fatos
-- (ou: python -m src.dw.carregar)

CREATE SCHEMA IF NOT EXISTS dw_campo_real;
CREATE SCHEMA IF NOT EXISTS stg;

-- ============================================================ DIMENSOES
-- Todas tem chave substituta (sk_*) e o membro -1 "Desconhecido" para registros sem correspondencia.

CREATE TABLE IF NOT EXISTS dw_campo_real.dim_fonte (
    sk_fonte     SERIAL  PRIMARY KEY,
    id_fonte     INTEGER NOT NULL UNIQUE,
    cod_fonte    TEXT    NOT NULL,
    descricao    TEXT    NOT NULL,
    renovavel    BOOLEAN,
    intermitente BOOLEAN
);

CREATE TABLE IF NOT EXISTS dw_campo_real.dim_submercado (
    sk_submercado  SERIAL PRIMARY KEY,
    cod_submercado TEXT   NOT NULL UNIQUE,
    nome           TEXT   NOT NULL,
    regioes        TEXT
);

CREATE TABLE IF NOT EXISTS dw_campo_real.dim_tipo_parada (
    sk_tipo_parada SERIAL PRIMARY KEY,
    tipo           TEXT   NOT NULL UNIQUE
);

-- Dimensao de tempo construida pelo grupo: uma linha por hora (2025-01-01 a 2026-12-31)
CREATE TABLE IF NOT EXISTS dw_campo_real.dim_tempo (
    sk_tempo          INTEGER PRIMARY KEY,          -- AAAAMMDDHH (ex.: 2025031508); -1 = desconhecido
    data_hora         TIMESTAMP UNIQUE,
    data              DATE,
    ano               SMALLINT,
    trimestre         SMALLINT,
    mes               SMALLINT,
    nome_mes          TEXT,
    ano_mes           TEXT,                          -- AAAA-MM
    dia               SMALLINT,
    hora              SMALLINT,
    dia_semana        SMALLINT,                      -- 1 = segunda ... 7 = domingo
    nome_dia_semana   TEXT,
    eh_fim_de_semana  BOOLEAN,
    eh_feriado        BOOLEAN,
    nome_feriado      TEXT,
    tipo_feriado      TEXT,                          -- Feriado | Ponto facultativo
    eh_dia_util       BOOLEAN,
    estacao           TEXT,                          -- hemisferio sul
    patamar_carga     TEXT                           -- Leve | Media | Pesada (simplificado, ver docs/modelagem.md)
);

-- Usina com SCD tipo 2 (nome, potencia, situacao, fonte e submercado geram nova versao)
CREATE TABLE IF NOT EXISTS dw_campo_real.dim_usina (
    sk_usina              SERIAL  PRIMARY KEY,
    id_usina_origem       INTEGER NOT NULL,          -- id canonico no cadastro (apos o de-para de duplicatas)
    cod_usina             TEXT    NOT NULL,
    nome                  TEXT    NOT NULL,
    sk_fonte              INTEGER NOT NULL REFERENCES dw_campo_real.dim_fonte (sk_fonte),
    sk_submercado         INTEGER NOT NULL REFERENCES dw_campo_real.dim_submercado (sk_submercado),
    uf                    TEXT,
    municipio             TEXT,
    latitude              NUMERIC(9,6),
    longitude             NUMERIC(9,6),
    potencia_mw           NUMERIC(8,2),
    data_inicio_operacao  DATE,
    data_inicio_suspeita  BOOLEAN NOT NULL DEFAULT FALSE,
    situacao              TEXT,
    coordenada_corrigida  BOOLEAN NOT NULL DEFAULT FALSE,
    uf_corrigida          BOOLEAN NOT NULL DEFAULT FALSE,
    hash_scd2             TEXT    NOT NULL,
    vigente_de            TIMESTAMP NOT NULL,
    vigente_ate           TIMESTAMP NOT NULL DEFAULT '9999-12-31',
    atual                 BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_usina_atual ON dw_campo_real.dim_usina (id_usina_origem) WHERE atual;

-- ============================================================ APOIO (rastreabilidade das decisoes de qualidade)
CREATE TABLE IF NOT EXISTS dw_campo_real.ref_feriado (
    data      DATE PRIMARY KEY,
    descricao TEXT NOT NULL,
    tipo      TEXT NOT NULL,
    fonte     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dw_campo_real.ref_depara_usina (
    id_usina_origem  INTEGER PRIMARY KEY,
    id_usina_canonico INTEGER NOT NULL,
    motivo           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dw_campo_real.correcao_cadastro (
    cod_usina       TEXT NOT NULL,
    campo           TEXT NOT NULL,
    valor_original  TEXT NOT NULL,
    valor_corrigido TEXT NOT NULL,
    regra           TEXT NOT NULL,
    justificativa   TEXT NOT NULL,
    PRIMARY KEY (cod_usina, campo)
);

-- ============================================================ FATOS
-- GRAO fato_geracao: uma linha por usina (versao vigente) e por hora, somente leituras que passaram na qualidade.
CREATE TABLE IF NOT EXISTS dw_campo_real.fato_geracao (
    sk_tempo              INTEGER NOT NULL REFERENCES dw_campo_real.dim_tempo (sk_tempo),
    sk_usina              INTEGER NOT NULL REFERENCES dw_campo_real.dim_usina (sk_usina),
    sk_fonte              INTEGER NOT NULL REFERENCES dw_campo_real.dim_fonte (sk_fonte),
    sk_submercado         INTEGER NOT NULL REFERENCES dw_campo_real.dim_submercado (sk_submercado),
    energia_mwh           NUMERIC(12,3) NOT NULL,
    disponibilidade_mw    NUMERIC(8,2),
    energia_original_mwh  NUMERIC(12,3),
    corrigida             BOOLEAN NOT NULL DEFAULT FALSE,
    origem_medicao        TEXT,
    recebido_em           TIMESTAMP,
    horas_ate_recebimento NUMERIC(10,2),
    id_medicao_origem     BIGINT,
    PRIMARY KEY (sk_tempo, sk_usina)
);
CREATE INDEX IF NOT EXISTS ix_fato_geracao_sub ON dw_campo_real.fato_geracao (sk_submercado, sk_tempo);

-- GRAO fato_pld: uma linha por submercado e por hora (PLD horario da CCEE).
CREATE TABLE IF NOT EXISTS dw_campo_real.fato_pld (
    sk_tempo                INTEGER NOT NULL REFERENCES dw_campo_real.dim_tempo (sk_tempo),
    sk_submercado           INTEGER NOT NULL REFERENCES dw_campo_real.dim_submercado (sk_submercado),
    pld_rs_mwh              NUMERIC(10,2) NOT NULL,
    periodo_comercializacao INTEGER,
    mes_referencia          TEXT,
    PRIMARY KEY (sk_tempo, sk_submercado)
);

-- GRAO fato_clima: uma linha por usina e por hora, no ponto das coordenadas da usina (Open-Meteo).
-- A usina e o elo com o submercado; clima nao e associado a estacao INMET.
CREATE TABLE IF NOT EXISTS dw_campo_real.fato_clima (
    sk_tempo              INTEGER NOT NULL REFERENCES dw_campo_real.dim_tempo (sk_tempo),
    sk_usina              INTEGER NOT NULL REFERENCES dw_campo_real.dim_usina (sk_usina),
    temperatura_c         NUMERIC(6,2),
    vento_10m_ms          NUMERIC(6,2),
    vento_100m_ms         NUMERIC(6,2),
    radiacao_wm2          NUMERIC(8,2),
    chuva_mm              NUMERIC(8,2),
    ponto_clima_confiavel BOOLEAN NOT NULL,
    PRIMARY KEY (sk_tempo, sk_usina)
);

-- GRAO fato_parada_hora: uma linha por parada, usina e hora dentro da parada.
CREATE TABLE IF NOT EXISTS dw_campo_real.fato_parada_hora (
    sk_tempo             INTEGER NOT NULL REFERENCES dw_campo_real.dim_tempo (sk_tempo),
    sk_usina             INTEGER NOT NULL REFERENCES dw_campo_real.dim_usina (sk_usina),
    id_parada            INTEGER NOT NULL,
    sk_tipo_parada       INTEGER NOT NULL REFERENCES dw_campo_real.dim_tipo_parada (sk_tipo_parada),
    motivo               TEXT,
    energia_estimada_mwh NUMERIC(12,3),     -- NULL quando nao ha base para estimar
    base_estimativa      TEXT NOT NULL,
    pld_rs_mwh           NUMERIC(10,2),
    receita_estimada_rs  NUMERIC(16,2),
    PRIMARY KEY (sk_tempo, sk_usina, id_parada)
);
