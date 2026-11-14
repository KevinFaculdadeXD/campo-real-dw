-- Carga das tabelas fato, views para o painel e copias das metricas de qualidade para dentro do DW.
-- Os fatos sao recarregados por completo (TRUNCATE + INSERT); as dimensoes preservam o historico SCD2.

TRUNCATE dw_campo_real.fato_geracao, dw_campo_real.fato_pld, dw_campo_real.fato_clima, dw_campo_real.fato_parada_hora;

-- ---------------------------------------------------------------- fato_geracao (so leituras aprovadas)
INSERT INTO dw_campo_real.fato_geracao
    (sk_tempo, sk_usina, sk_fonte, sk_submercado, energia_mwh, disponibilidade_mw, energia_original_mwh, corrigida,
     origem_medicao, recebido_em, horas_ate_recebimento, id_medicao_origem)
SELECT t.sk_tempo, u.sk_usina, u.sk_fonte, u.sk_submercado, c.energia_final_mwh, c.disponibilidade_mw,
       c.energia_original_mwh, c.corrigida, c.origem, c.recebido_em,
       round((EXTRACT(EPOCH FROM (c.recebido_em - c.data_hora)) / 3600)::numeric, 2), c.id_medicao
FROM stg.medicao_classificada c
JOIN dw_campo_real.dim_tempo t ON t.data_hora = c.data_hora
JOIN dw_campo_real.dim_usina u ON u.id_usina_origem = c.id_usina_canonico
                              AND c.data_hora >= u.vigente_de AND c.data_hora < u.vigente_ate
WHERE c.motivo_quarentena IS NULL;

-- ---------------------------------------------------------------- fato_pld
INSERT INTO dw_campo_real.fato_pld (sk_tempo, sk_submercado, pld_rs_mwh, periodo_comercializacao, mes_referencia)
SELECT t.sk_tempo, s.sk_submercado, p.pld_rs_mwh, p.periodo_comercializacao, p.mes_referencia
FROM stg.pld_horario_tratado p
JOIN dw_campo_real.dim_tempo t ON t.data_hora = p.data_hora
JOIN dw_campo_real.dim_submercado s ON s.cod_submercado = btrim(p.cod_submercado::text);

-- ---------------------------------------------------------------- fato_clima
-- So a usina canonica (a duplicada tem o mesmo ponto). Para usina com coordenada corrigida, o clima baixado
-- usou a coordenada errada: fica marcado como nao confiavel (ver regra V05).
INSERT INTO dw_campo_real.fato_clima
    (sk_tempo, sk_usina, temperatura_c, vento_10m_ms, vento_100m_ms, radiacao_wm2, chuva_mm, ponto_clima_confiavel)
SELECT t.sk_tempo, u.sk_usina, c.temperatura_c, c.vento_10m_ms, c.vento_100m_ms, c.radiacao_wm2, c.chuva_mm,
       NOT u.coordenada_corrigida
FROM stg.clima_horario c
JOIN dw_campo_real.ref_depara_usina dp ON dp.id_usina_origem = c.id_usina AND dp.id_usina_canonico = c.id_usina
JOIN dw_campo_real.dim_tempo t ON t.data_hora = c.data_hora
JOIN dw_campo_real.dim_usina u ON u.id_usina_origem = c.id_usina AND u.atual;

-- ---------------------------------------------------------------- fato_parada_hora
DROP TABLE IF EXISTS tmp_parada_horas;
CREATE TEMP TABLE tmp_parada_horas AS
SELECT p.id_parada, u.sk_usina, u.sk_submercado, t.sk_tempo, t.mes, t.hora,
       COALESCE(tp.sk_tipo_parada, -1) AS sk_tipo_parada, p.motivo
FROM campo_real_energia.parada_usina p
JOIN dw_campo_real.ref_depara_usina dp ON dp.id_usina_origem = p.id_usina
CROSS JOIN LATERAL generate_series(date_trunc('hour', p.inicio), date_trunc('hour', p.fim), interval '1 hour') AS g(h)
JOIN dw_campo_real.dim_tempo t ON t.data_hora = g.h
JOIN dw_campo_real.dim_usina u ON u.id_usina_origem = dp.id_usina_canonico
                              AND g.h >= u.vigente_de AND g.h < u.vigente_ate
LEFT JOIN dw_campo_real.dim_tipo_parada tp ON tp.tipo = btrim(p.tipo)
WHERE p.fim >= p.inicio;   -- V04: parada com fim antes do inicio fica na quarentena

-- Energia que a usina costuma gerar naquela hora e mes fora de paradas (media das leituras aprovadas)
DROP TABLE IF EXISTS tmp_media_mes_hora;
CREATE TEMP TABLE tmp_media_mes_hora AS
SELECT g.sk_usina, t.mes, t.hora, avg(g.energia_mwh) AS media
FROM dw_campo_real.fato_geracao g
JOIN dw_campo_real.dim_tempo t ON t.sk_tempo = g.sk_tempo
WHERE NOT EXISTS (SELECT 1 FROM tmp_parada_horas ph WHERE ph.sk_usina = g.sk_usina AND ph.sk_tempo = g.sk_tempo)
GROUP BY g.sk_usina, t.mes, t.hora;

INSERT INTO dw_campo_real.fato_parada_hora
    (sk_tempo, sk_usina, id_parada, sk_tipo_parada, motivo, energia_estimada_mwh, base_estimativa, pld_rs_mwh,
     receita_estimada_rs)
SELECT ph.sk_tempo, ph.sk_usina, ph.id_parada, ph.sk_tipo_parada, ph.motivo,
       round(m.media, 3),
       CASE WHEN m.media IS NULL THEN 'sem base (mes inteiro parado)' ELSE 'media da usina na mesma hora e mes' END,
       p.pld_rs_mwh,
       round(m.media * p.pld_rs_mwh, 2)
FROM tmp_parada_horas ph
LEFT JOIN tmp_media_mes_hora m ON m.sk_usina = ph.sk_usina AND m.mes = ph.mes AND m.hora = ph.hora
LEFT JOIN dw_campo_real.fato_pld p ON p.sk_tempo = ph.sk_tempo AND p.sk_submercado = ph.sk_submercado;

-- ---------------------------------------------------------------- views para o painel (o Tableau le so o DW)
DROP VIEW IF EXISTS dw_campo_real.vw_receita_horaria;
CREATE VIEW dw_campo_real.vw_receita_horaria AS
WITH pm AS (
    SELECT p.sk_submercado, t.ano, avg(p.pld_rs_mwh) AS pld_medio_ano
    FROM dw_campo_real.fato_pld p JOIN dw_campo_real.dim_tempo t ON t.sk_tempo = p.sk_tempo
    GROUP BY p.sk_submercado, t.ano
)
SELECT t.data_hora, t.data, t.ano, t.mes, t.nome_mes, t.ano_mes, t.hora, t.dia_semana, t.nome_dia_semana,
       t.eh_dia_util, t.eh_feriado, t.estacao, t.patamar_carga,
       u.cod_usina, u.nome AS usina, u.potencia_mw, u.municipio, u.uf,
       f.cod_fonte, f.descricao AS fonte, f.renovavel, f.intermitente,
       s.cod_submercado, s.nome AS submercado,
       g.energia_mwh, g.corrigida AS leitura_corrigida,
       p.pld_rs_mwh,
       g.energia_mwh * p.pld_rs_mwh AS receita_rs,
       pm.pld_medio_ano AS pld_medio_submercado_ano,
       g.energia_mwh * pm.pld_medio_ano AS energia_x_pld_medio_rs
FROM dw_campo_real.fato_geracao g
JOIN dw_campo_real.dim_tempo t ON t.sk_tempo = g.sk_tempo
JOIN dw_campo_real.dim_usina u ON u.sk_usina = g.sk_usina
JOIN dw_campo_real.dim_fonte f ON f.sk_fonte = g.sk_fonte
JOIN dw_campo_real.dim_submercado s ON s.sk_submercado = g.sk_submercado
LEFT JOIN dw_campo_real.fato_pld p ON p.sk_tempo = g.sk_tempo AND p.sk_submercado = g.sk_submercado
LEFT JOIN pm ON pm.sk_submercado = g.sk_submercado AND pm.ano = t.ano;

DROP VIEW IF EXISTS dw_campo_real.vw_pld_horario;
CREATE VIEW dw_campo_real.vw_pld_horario AS
SELECT t.data_hora, t.data, t.ano, t.mes, t.nome_mes, t.ano_mes, t.hora, t.dia_semana, t.eh_dia_util,
       t.estacao, t.patamar_carga, s.cod_submercado, s.nome AS submercado, p.pld_rs_mwh
FROM dw_campo_real.fato_pld p
JOIN dw_campo_real.dim_tempo t ON t.sk_tempo = p.sk_tempo
JOIN dw_campo_real.dim_submercado s ON s.sk_submercado = p.sk_submercado;

DROP VIEW IF EXISTS dw_campo_real.vw_paradas;
CREATE VIEW dw_campo_real.vw_paradas AS
SELECT t.data_hora, t.data, t.ano_mes, u.cod_usina, u.nome AS usina, f.descricao AS fonte, tp.tipo AS tipo_parada,
       h.id_parada, h.motivo, 1 AS horas_indisponiveis, h.energia_estimada_mwh, h.base_estimativa,
       h.pld_rs_mwh, h.receita_estimada_rs
FROM dw_campo_real.fato_parada_hora h
JOIN dw_campo_real.dim_tempo t ON t.sk_tempo = h.sk_tempo
JOIN dw_campo_real.dim_usina u ON u.sk_usina = h.sk_usina
JOIN dw_campo_real.dim_fonte f ON f.sk_fonte = u.sk_fonte
JOIN dw_campo_real.dim_tipo_parada tp ON tp.sk_tipo_parada = h.sk_tipo_parada;

DROP VIEW IF EXISTS dw_campo_real.vw_clima_geracao;
CREATE VIEW dw_campo_real.vw_clima_geracao AS
SELECT t.data_hora, t.data, t.ano_mes, t.hora, u.cod_usina, u.nome AS usina, f.cod_fonte, f.descricao AS fonte,
       c.radiacao_wm2, c.vento_10m_ms, c.vento_100m_ms, c.temperatura_c, c.chuva_mm,
       g.energia_mwh, p.pld_rs_mwh
FROM dw_campo_real.fato_clima c
JOIN dw_campo_real.fato_geracao g ON g.sk_tempo = c.sk_tempo AND g.sk_usina = c.sk_usina
JOIN dw_campo_real.dim_tempo t ON t.sk_tempo = c.sk_tempo
JOIN dw_campo_real.dim_usina u ON u.sk_usina = c.sk_usina
JOIN dw_campo_real.dim_fonte f ON f.sk_fonte = u.sk_fonte
LEFT JOIN dw_campo_real.fato_pld p ON p.sk_tempo = c.sk_tempo AND p.sk_submercado = u.sk_submercado
WHERE c.ponto_clima_confiavel;

-- ---------------------------------------------------------------- qualidade dentro do DW (painel le so o DW)
DROP TABLE IF EXISTS dw_campo_real.qualidade_metricas;
CREATE TABLE dw_campo_real.qualidade_metricas AS
SELECT regra, dimensao, tabela, registros_avaliados, registros_com_falha, percentual_falha, status, decisao, problema,
       executado_em
FROM qualidade.v_metricas_ultimo_lote;

DROP TABLE IF EXISTS dw_campo_real.qualidade_indice;
CREATE TABLE dw_campo_real.qualidade_indice AS
SELECT dimensao, tabela, avaliados, falhas, indice_pct FROM qualidade.v_indice_qualidade;

-- Relatorio antes x depois: valoracao ao PLD da origem "como chega" x depois da limpeza
DROP TABLE IF EXISTS dw_campo_real.qualidade_antes_depois;
CREATE TABLE dw_campo_real.qualidade_antes_depois AS
WITH antes AS (
    SELECT dp.id_usina_canonico AS id_usina, count(*) AS horas, sum(m.energia_mwh) AS mwh,
           sum(m.energia_mwh * p.pld_rs_mwh) AS receita
    FROM campo_real_energia.medicao_geracao m
    JOIN campo_real_energia.usina u ON u.id_usina = m.id_usina
    JOIN dw_campo_real.ref_depara_usina dp ON dp.id_usina_origem = u.id_usina
    JOIN stg.pld_horario_tratado p ON btrim(p.cod_submercado::text) = btrim(u.cod_submercado::text)
                                  AND p.data_hora = m.data_hora
    WHERE m.energia_mwh IS NOT NULL
    GROUP BY dp.id_usina_canonico
), depois AS (
    SELECT u.id_usina_origem AS id_usina, count(*) AS horas, sum(g.energia_mwh) AS mwh,
           sum(g.energia_mwh * p.pld_rs_mwh) AS receita
    FROM dw_campo_real.fato_geracao g
    JOIN dw_campo_real.dim_usina u ON u.sk_usina = g.sk_usina
    JOIN dw_campo_real.fato_pld p ON p.sk_tempo = g.sk_tempo AND p.sk_submercado = g.sk_submercado
    GROUP BY u.id_usina_origem
), x AS (
    SELECT cu.cod_usina, cu.nome AS usina, a.horas AS horas_antes, d.horas AS horas_depois,
           a.mwh AS geracao_antes_mwh, d.mwh AS geracao_depois_mwh,
           a.receita AS receita_antes_rs, d.receita AS receita_depois_rs
    FROM antes a
    FULL JOIN depois d ON d.id_usina = a.id_usina
    LEFT JOIN campo_real_energia.usina cu ON cu.id_usina = COALESCE(a.id_usina, d.id_usina)
), tot AS (
    SELECT cod_usina, usina, horas_antes, horas_depois, geracao_antes_mwh, geracao_depois_mwh,
           receita_antes_rs, receita_depois_rs FROM x
    UNION ALL
    SELECT 'TOTAL', 'Total geral', sum(horas_antes), sum(horas_depois), sum(geracao_antes_mwh),
           sum(geracao_depois_mwh), sum(receita_antes_rs), sum(receita_depois_rs) FROM x
)
SELECT tot.*,
       geracao_depois_mwh - geracao_antes_mwh AS delta_geracao_mwh,
       receita_depois_rs - receita_antes_rs AS delta_receita_rs,
       round(100.0 * (receita_depois_rs - receita_antes_rs) / nullif(receita_antes_rs, 0), 2) AS delta_receita_pct,
       round(receita_antes_rs / nullif(geracao_antes_mwh, 0), 2) AS preco_capturado_antes,
       round(receita_depois_rs / nullif(geracao_depois_mwh, 0), 2) AS preco_capturado_depois
FROM tot;

DROP TABLE IF EXISTS dw_campo_real.qualidade_impacto_tratamento;
CREATE TABLE dw_campo_real.qualidade_impacto_tratamento AS
SELECT COALESCE(c.motivo_quarentena,
                CASE WHEN c.corrigida THEN 'A02 corrigida (kWh para MWh)' ELSE 'Carregada sem alteracao' END) AS tratamento,
       CASE WHEN c.motivo_quarentena IS NOT NULL THEN 'quarentena ou descarte'
            WHEN c.corrigida THEN 'corrigida' ELSE 'mantida' END AS destino,
       count(*) AS linhas,
       sum(c.energia_original_mwh) AS energia_original_mwh,
       sum(c.energia_final_mwh) AS energia_final_mwh
FROM stg.medicao_classificada c
GROUP BY 1, 2;

ANALYZE dw_campo_real.fato_geracao;
ANALYZE dw_campo_real.fato_pld;
