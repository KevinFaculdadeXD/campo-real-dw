-- Etapa 2 · Qualidade de dados: tabelas de metricas, decisoes, perfil e limites regulatorios.
-- Pode rodar mais de uma vez. Pelo DBeaver: abrir o arquivo e Alt+X.

CREATE SCHEMA IF NOT EXISTS qualidade;

-- Limites regulatorios do PLD (R$/MWh), por ano. Fonte: ANEEL.
CREATE TABLE IF NOT EXISTS qualidade.limites_pld (
    ano             SMALLINT      PRIMARY KEY,
    piso            NUMERIC(10,2) NOT NULL,
    teto_estrutural NUMERIC(10,2) NOT NULL,
    teto_horario    NUMERIC(10,2) NOT NULL,
    fonte           TEXT          NOT NULL
);
INSERT INTO qualidade.limites_pld (ano, piso, teto_estrutural, teto_horario, fonte) VALUES
  (2025, 58.60, 751.73, 1542.23, 'ANEEL - limites do PLD 2025 (DOU de 17/12/2024)'),
  (2026, 57.31, 785.27, 1611.04, 'ANEEL - Despacho 3.850/2025 (DOU de 23/12/2025)')
ON CONFLICT (ano) DO UPDATE SET piso = EXCLUDED.piso, teto_estrutural = EXCLUDED.teto_estrutural,
    teto_horario = EXCLUDED.teto_horario, fonte = EXCLUDED.fonte;

-- Uma linha por regra e por execucao
CREATE TABLE IF NOT EXISTS qualidade.metricas (
    id_metrica          BIGSERIAL    PRIMARY KEY,
    id_execucao         BIGINT       NOT NULL REFERENCES qualidade.log_execucao (id_execucao),
    regra               TEXT         NOT NULL,
    dimensao            TEXT         NOT NULL CHECK (dimensao IN ('completude','unicidade','validade',
                                     'consistencia','acuracia','integridade_referencial','atualidade')),
    tabela              TEXT         NOT NULL,
    registros_avaliados BIGINT,
    registros_com_falha BIGINT,
    percentual_falha    NUMERIC(9,4),
    status              TEXT         NOT NULL CHECK (status IN ('OK','FALHA','ERRO')),
    erro                TEXT,
    executado_em        TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_metricas_exec ON qualidade.metricas (id_execucao, dimensao);

-- Decisao justificada para cada regra (corrigir, descartar, quarentena ou sinalizar)
CREATE TABLE IF NOT EXISTS qualidade.decisoes (
    regra         TEXT PRIMARY KEY,
    dimensao      TEXT NOT NULL,
    tabela        TEXT NOT NULL,
    problema      TEXT NOT NULL,
    decisao       TEXT NOT NULL CHECK (decisao IN ('corrigir','descartar','quarentena','sinalizar')),
    justificativa TEXT NOT NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Profiling por coluna
CREATE TABLE IF NOT EXISTS qualidade.perfil_colunas (
    id_perfil    BIGSERIAL   PRIMARY KEY,
    id_execucao  BIGINT      NOT NULL REFERENCES qualidade.log_execucao (id_execucao),
    esquema      TEXT        NOT NULL,
    tabela       TEXT        NOT NULL,
    coluna       TEXT        NOT NULL,
    tipo         TEXT        NOT NULL,
    linhas       BIGINT,
    nulos        BIGINT,
    distintos    BIGINT,
    minimo       TEXT,
    maximo       TEXT,
    media        NUMERIC,
    distribuicao JSONB,
    executado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_perfil_exec ON qualidade.perfil_colunas (id_execucao, tabela);

CREATE OR REPLACE VIEW qualidade.v_metricas_ultimo_lote AS
SELECT m.id_execucao, m.regra, m.dimensao, m.tabela, m.registros_avaliados, m.registros_com_falha,
       m.percentual_falha, m.status, m.erro, m.executado_em, d.decisao, d.problema
FROM qualidade.metricas m
LEFT JOIN qualidade.decisoes d ON d.regra = m.regra
WHERE m.id_execucao = (SELECT max(id_execucao) FROM qualidade.metricas);

-- Indice simples: 100 x (1 - falhas / avaliados), somando as regras de cada dimensao e tabela
CREATE OR REPLACE VIEW qualidade.v_indice_qualidade AS
SELECT dimensao, tabela,
       sum(registros_avaliados)  AS avaliados,
       sum(registros_com_falha)  AS falhas,
       round(100.0 * (1 - sum(registros_com_falha)::numeric / nullif(sum(registros_avaliados), 0)), 2) AS indice_pct
FROM qualidade.v_metricas_ultimo_lote
WHERE status <> 'ERRO'
GROUP BY dimensao, tabela;
