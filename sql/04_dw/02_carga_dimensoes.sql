-- Carga das dimensoes e tabelas de apoio. Roda inteiro numa sessao so (usa tabela temporaria).

-- ---------------------------------------------------------------- dim_fonte / dim_submercado / dim_tipo_parada
INSERT INTO dw_campo_real.dim_fonte (sk_fonte, id_fonte, cod_fonte, descricao, renovavel, intermitente)
VALUES (-1, -1, 'N/D', 'Desconhecido', NULL, NULL) ON CONFLICT (sk_fonte) DO NOTHING;

INSERT INTO dw_campo_real.dim_fonte (id_fonte, cod_fonte, descricao, renovavel, intermitente)
SELECT id_fonte, btrim(cod_fonte), descricao, renovavel, intermitente FROM campo_real_energia.fonte_energia
ON CONFLICT (id_fonte) DO UPDATE SET cod_fonte = EXCLUDED.cod_fonte, descricao = EXCLUDED.descricao,
    renovavel = EXCLUDED.renovavel, intermitente = EXCLUDED.intermitente;

INSERT INTO dw_campo_real.dim_submercado (sk_submercado, cod_submercado, nome, regioes)
VALUES (-1, 'N/D', 'Desconhecido', NULL) ON CONFLICT (sk_submercado) DO NOTHING;

INSERT INTO dw_campo_real.dim_submercado (cod_submercado, nome, regioes)
SELECT btrim(cod_submercado::text), nome, regioes FROM campo_real_energia.submercado
ON CONFLICT (cod_submercado) DO UPDATE SET nome = EXCLUDED.nome, regioes = EXCLUDED.regioes;

INSERT INTO dw_campo_real.dim_tipo_parada (sk_tipo_parada, tipo)
VALUES (-1, 'Desconhecido') ON CONFLICT (sk_tipo_parada) DO NOTHING;

INSERT INTO dw_campo_real.dim_tipo_parada (tipo)
SELECT DISTINCT btrim(tipo) FROM campo_real_energia.parada_usina WHERE tipo IS NOT NULL
ON CONFLICT (tipo) DO NOTHING;

-- ---------------------------------------------------------------- feriados (2025 da origem + 2026 do calendario oficial)
DELETE FROM dw_campo_real.ref_feriado;
INSERT INTO dw_campo_real.ref_feriado (data, descricao, tipo, fonte)
SELECT data, descricao, tipo, 'origem: campo_real_energia.feriado_nacional' FROM campo_real_energia.feriado_nacional;

-- Regra C08: a origem so tem 2025. 2026 complementado com o calendario nacional (datas fixas em lei,
-- Sexta-feira Santa, e Carnaval e Corpus Christi como ponto facultativo, igual a classificacao de 2025).
INSERT INTO dw_campo_real.ref_feriado (data, descricao, tipo, fonte) VALUES
  ('2026-01-01', 'Confraternização Universal',  'Feriado',           'complemento do DW (regra C08)'),
  ('2026-02-16', 'Carnaval',                    'Ponto facultativo', 'complemento do DW (regra C08)'),
  ('2026-02-17', 'Carnaval',                    'Ponto facultativo', 'complemento do DW (regra C08)'),
  ('2026-04-03', 'Sexta-feira Santa',           'Feriado',           'complemento do DW (regra C08)'),
  ('2026-04-21', 'Tiradentes',                  'Feriado',           'complemento do DW (regra C08)'),
  ('2026-05-01', 'Dia do Trabalho',             'Feriado',           'complemento do DW (regra C08)'),
  ('2026-06-04', 'Corpus Christi',              'Ponto facultativo', 'complemento do DW (regra C08)'),
  ('2026-09-07', 'Independência do Brasil',     'Feriado',           'complemento do DW (regra C08)'),
  ('2026-10-12', 'Nossa Senhora Aparecida',     'Feriado',           'complemento do DW (regra C08)'),
  ('2026-11-02', 'Finados',                     'Feriado',           'complemento do DW (regra C08)'),
  ('2026-11-15', 'Proclamação da República',    'Feriado',           'complemento do DW (regra C08)'),
  ('2026-11-20', 'Dia da Consciência Negra',    'Feriado',           'complemento do DW (regra C08)'),
  ('2026-12-25', 'Natal',                       'Feriado',           'complemento do DW (regra C08)')
ON CONFLICT (data) DO NOTHING;

-- ---------------------------------------------------------------- dim_tempo
INSERT INTO dw_campo_real.dim_tempo (sk_tempo, nome_mes, nome_dia_semana, nome_feriado, tipo_feriado, estacao, patamar_carga,
                                     eh_fim_de_semana, eh_feriado, eh_dia_util)
VALUES (-1, 'Desconhecido', 'Desconhecido', NULL, NULL, 'Desconhecido', 'Desconhecido', FALSE, FALSE, FALSE)
ON CONFLICT (sk_tempo) DO NOTHING;

WITH x AS (
    SELECT g.ts, g.ts::date AS d,
           EXTRACT(MONTH FROM g.ts)::int AS mes, EXTRACT(DAY FROM g.ts)::int AS dia,
           EXTRACT(HOUR FROM g.ts)::int AS hora, EXTRACT(ISODOW FROM g.ts)::int AS dow
    FROM generate_series('2025-01-01 00:00'::timestamp, '2026-12-31 23:00'::timestamp, interval '1 hour') AS g(ts)
), y AS (
    SELECT x.*, f.descricao AS nome_feriado, f.tipo AS tipo_feriado,
           (x.dow < 6 AND COALESCE(f.tipo, '') <> 'Feriado') AS dia_util
    FROM x LEFT JOIN dw_campo_real.ref_feriado f ON f.data = x.d
)
INSERT INTO dw_campo_real.dim_tempo
    (sk_tempo, data_hora, data, ano, trimestre, mes, nome_mes, ano_mes, dia, hora, dia_semana, nome_dia_semana,
     eh_fim_de_semana, eh_feriado, nome_feriado, tipo_feriado, eh_dia_util, estacao, patamar_carga)
SELECT to_char(ts, 'YYYYMMDDHH24')::int, ts, d, EXTRACT(YEAR FROM ts)::int, EXTRACT(QUARTER FROM ts)::int, mes,
       (ARRAY['janeiro','fevereiro','março','abril','maio','junho','julho','agosto','setembro','outubro','novembro','dezembro'])[mes],
       to_char(ts, 'YYYY-MM'), dia, hora, dow,
       (ARRAY['segunda-feira','terça-feira','quarta-feira','quinta-feira','sexta-feira','sábado','domingo'])[dow],
       (dow >= 6), (nome_feriado IS NOT NULL), nome_feriado, tipo_feriado, dia_util,
       CASE WHEN mes * 100 + dia >= 1221 OR mes * 100 + dia <= 320 THEN 'Verão'
            WHEN mes * 100 + dia <= 620 THEN 'Outono'
            WHEN mes * 100 + dia <= 922 THEN 'Inverno'
            ELSE 'Primavera' END,
       CASE WHEN dia_util THEN
                CASE WHEN hora BETWEEN 18 AND 20 THEN 'Pesada'
                     WHEN hora BETWEEN 7 AND 17 OR hora IN (21, 22) THEN 'Média'
                     ELSE 'Leve' END
            ELSE CASE WHEN hora BETWEEN 18 AND 20 THEN 'Média' ELSE 'Leve' END END
FROM y
ON CONFLICT (sk_tempo) DO UPDATE SET eh_feriado = EXCLUDED.eh_feriado, nome_feriado = EXCLUDED.nome_feriado,
    tipo_feriado = EXCLUDED.tipo_feriado, eh_dia_util = EXCLUDED.eh_dia_util, patamar_carga = EXCLUDED.patamar_carga;

-- ---------------------------------------------------------------- de-para de usinas duplicadas (regras U02/U03/V06)
-- Duplicata = mesma latitude, longitude e fonte. Fica o cadastro mais completo (municipio preenchido), depois o menor id.
DELETE FROM dw_campo_real.ref_depara_usina;
INSERT INTO dw_campo_real.ref_depara_usina (id_usina_origem, id_usina_canonico, motivo)
SELECT u.id_usina,
       first_value(u.id_usina) OVER (PARTITION BY u.latitude, u.longitude, u.id_fonte
                                     ORDER BY (nullif(btrim(u.municipio), '') IS NULL), u.id_usina),
       'mesmas coordenadas e fonte (U02)'
FROM campo_real_energia.usina u;

-- ---------------------------------------------------------------- correcoes de cadastro com evidencia (V05, K04)
INSERT INTO dw_campo_real.correcao_cadastro (cod_usina, campo, valor_original, valor_corrigido, regra, justificativa) VALUES
  ('CRE-UFV-004', 'latitude', '15.803', '-15.803', 'V05',
   'Latitude positiva cai no oceano. Municipio (Janaiba/MG) e longitude indicam sinal trocado; todas as outras usinas tem latitude negativa.'),
  ('CRE-BIO-005', 'uf', 'PE', 'SP', 'K04',
   'Submercado SE, municipio Sertaozinho e coordenadas (-21,138; -47,99) apontam para SP, nao PE (NE).')
ON CONFLICT (cod_usina, campo) DO NOTHING;

-- ---------------------------------------------------------------- dim_usina (SCD tipo 2)
DROP TABLE IF EXISTS tmp_usina_canonica;
CREATE TEMP TABLE tmp_usina_canonica AS
SELECT u.id_usina AS id_usina_origem,
       btrim(u.cod_usina) AS cod_usina,
       regexp_replace(btrim(u.nome), '\s+', ' ', 'g') AS nome,
       fo.sk_fonte, su.sk_submercado,
       COALESCE(cu.valor_corrigido, btrim(u.uf::text)) AS uf,
       (cu.valor_corrigido IS NOT NULL) AS uf_corrigida,
       btrim(u.municipio) AS municipio,
       COALESCE(cl.valor_corrigido::numeric, u.latitude) AS latitude,
       (cl.valor_corrigido IS NOT NULL) AS coordenada_corrigida,
       u.longitude, u.potencia_mw,
       CASE WHEN u.data_inicio_operacao > current_date THEN NULL ELSE u.data_inicio_operacao END AS data_inicio_operacao,
       (u.data_inicio_operacao > current_date) AS data_inicio_suspeita,
       u.situacao,
       md5(concat_ws('|', regexp_replace(btrim(u.nome), '\s+', ' ', 'g'), u.potencia_mw::text, u.situacao,
                     fo.sk_fonte::text, su.sk_submercado::text)) AS hash_scd2
FROM campo_real_energia.usina u
JOIN dw_campo_real.ref_depara_usina d ON d.id_usina_origem = u.id_usina AND d.id_usina_canonico = u.id_usina
JOIN dw_campo_real.dim_fonte fo ON fo.id_fonte = u.id_fonte
JOIN dw_campo_real.dim_submercado su ON su.cod_submercado = btrim(u.cod_submercado::text)
LEFT JOIN dw_campo_real.correcao_cadastro cu
       ON cu.cod_usina = btrim(u.cod_usina) AND cu.campo = 'uf' AND cu.valor_original = btrim(u.uf::text)
LEFT JOIN dw_campo_real.correcao_cadastro cl
       ON cl.cod_usina = btrim(u.cod_usina) AND cl.campo = 'latitude'
       AND CASE WHEN cl.campo = 'latitude' THEN cl.valor_original::numeric END = u.latitude;

-- membro desconhecido
INSERT INTO dw_campo_real.dim_usina (sk_usina, id_usina_origem, cod_usina, nome, sk_fonte, sk_submercado, hash_scd2, vigente_de)
VALUES (-1, -1, 'N/D', 'Desconhecida', -1, -1, 'n/d', '1900-01-01') ON CONFLICT (sk_usina) DO NOTHING;

-- 1) fecha a versao vigente quando um atributo rastreado mudou
UPDATE dw_campo_real.dim_usina d
SET vigente_ate = localtimestamp, atual = FALSE
FROM tmp_usina_canonica t
WHERE d.id_usina_origem = t.id_usina_origem AND d.atual AND d.hash_scd2 <> t.hash_scd2;

-- 2) abre a nova versao (ou a primeira, com vigencia desde 1900 para cobrir todo o historico)
INSERT INTO dw_campo_real.dim_usina
    (id_usina_origem, cod_usina, nome, sk_fonte, sk_submercado, uf, municipio, latitude, longitude, potencia_mw,
     data_inicio_operacao, data_inicio_suspeita, situacao, coordenada_corrigida, uf_corrigida, hash_scd2, vigente_de)
SELECT t.id_usina_origem, t.cod_usina, t.nome, t.sk_fonte, t.sk_submercado, t.uf, t.municipio, t.latitude, t.longitude,
       t.potencia_mw, t.data_inicio_operacao, t.data_inicio_suspeita, t.situacao, t.coordenada_corrigida, t.uf_corrigida,
       t.hash_scd2,
       CASE WHEN EXISTS (SELECT 1 FROM dw_campo_real.dim_usina x WHERE x.id_usina_origem = t.id_usina_origem)
            THEN localtimestamp ELSE TIMESTAMP '1900-01-01' END
FROM tmp_usina_canonica t
WHERE NOT EXISTS (SELECT 1 FROM dw_campo_real.dim_usina d WHERE d.id_usina_origem = t.id_usina_origem AND d.atual);

-- 3) atributos nao rastreados (correcoes de cadastro, localizacao) sao sobrescritos: SCD tipo 1
UPDATE dw_campo_real.dim_usina d
SET cod_usina = t.cod_usina, uf = t.uf, municipio = t.municipio, latitude = t.latitude, longitude = t.longitude,
    data_inicio_operacao = t.data_inicio_operacao, data_inicio_suspeita = t.data_inicio_suspeita,
    coordenada_corrigida = t.coordenada_corrigida, uf_corrigida = t.uf_corrigida
FROM tmp_usina_canonica t
WHERE d.id_usina_origem = t.id_usina_origem AND d.atual;
