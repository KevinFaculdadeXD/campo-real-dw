-- Aplica as decisoes da qualidade (etapa 2) sobre medicao_geracao, SEM alterar a origem.
-- Resultado: stg.medicao_classificada, uma linha por leitura de origem, com o motivo da quarentena (ou NULL = carregar).
-- Precedencia dos motivos: o primeiro que casar na lista do CASE.

DROP TABLE IF EXISTS stg.medicao_classificada;
CREATE TABLE stg.medicao_classificada AS
WITH base AS (
    SELECT m.id_medicao, m.id_usina AS id_usina_origem, dp.id_usina_canonico,
           m.data_hora, m.energia_mwh, m.disponibilidade_mw, m.origem, m.recebido_em,
           u.potencia_mw, fo.cod_fonte,
           -- U01: vale a leitura SCADA e, entre iguais, a mais antiga
           row_number() OVER (PARTITION BY dp.id_usina_canonico, m.data_hora
                              ORDER BY (m.origem = 'MANUAL'), m.recebido_em, m.id_medicao) AS rn
    FROM campo_real_energia.medicao_geracao m
    LEFT JOIN campo_real_energia.usina u ON u.id_usina = m.id_usina
    LEFT JOIN dw_campo_real.ref_depara_usina dp ON dp.id_usina_origem = m.id_usina
    LEFT JOIN campo_real_energia.fonte_energia fo ON fo.id_fonte = u.id_fonte
),
-- A02: dias inteiros (todas as leituras do dia da usina > 10x a potencia) lancados MANUAL em kWh
dia_kwh AS (
    SELECT id_usina_canonico, data_hora::date AS dia
    FROM base
    WHERE rn = 1 AND energia_mwh IS NOT NULL AND id_usina_canonico IS NOT NULL
    GROUP BY id_usina_canonico, data_hora::date
    HAVING count(*) = count(*) FILTER (WHERE energia_mwh > 10 * potencia_mw)
       AND bool_and(origem = 'MANUAL')
),
-- A01: 6 ou mais leituras consecutivas iguais e positivas
travado AS (
    SELECT id_medicao
    FROM (
        SELECT id_medicao, count(*) OVER (PARTITION BY id_usina_canonico, grp) AS n
        FROM (
            SELECT id_medicao, id_usina_canonico,
                   sum(muda::int) OVER (PARTITION BY id_usina_canonico ORDER BY data_hora) AS grp
            FROM (
                SELECT id_medicao, id_usina_canonico, data_hora,
                       (energia_mwh IS DISTINCT FROM lag(energia_mwh) OVER (PARTITION BY id_usina_canonico ORDER BY data_hora)) AS muda
                FROM base
                WHERE rn = 1 AND energia_mwh > 0 AND id_usina_canonico IS NOT NULL
                  AND data_hora >= '2025-01-01' AND data_hora < '2026-01-01'
            ) a
        ) b
    ) c
    WHERE n >= 6
),
f AS (
    SELECT b.id_medicao, b.id_usina_origem, b.id_usina_canonico, b.data_hora,
           b.energia_mwh AS energia_original_mwh,
           CASE WHEN k.dia IS NOT NULL THEN round(b.energia_mwh / 1000.0, 3) ELSE b.energia_mwh END AS energia_final_mwh,
           (k.dia IS NOT NULL) AS corrigida,
           b.disponibilidade_mw, b.origem, b.recebido_em, b.potencia_mw, b.cod_fonte, b.rn,
           (t.id_medicao IS NOT NULL) AS travado
    FROM base b
    LEFT JOIN dia_kwh k ON k.id_usina_canonico = b.id_usina_canonico AND k.dia = b.data_hora::date
    LEFT JOIN travado t ON t.id_medicao = b.id_medicao
)
SELECT f.id_medicao, f.id_usina_origem, f.id_usina_canonico, f.data_hora,
       f.energia_original_mwh, f.energia_final_mwh, f.corrigida,
       f.disponibilidade_mw, f.origem, f.recebido_em,
       CASE
         WHEN f.id_usina_origem IS NULL THEN 'C02 medicao sem usina'
         WHEN f.potencia_mw IS NULL THEN 'R01 usina fora do cadastro'
         WHEN f.data_hora IS NULL OR f.data_hora < '2025-01-01' OR f.data_hora >= '2026-01-01' THEN 'V02 data fora de 2025'
         WHEN f.rn > 1 THEN 'U01 medicao duplicada'
         WHEN f.energia_original_mwh IS NULL THEN 'C01 energia nula'
         WHEN f.energia_original_mwh < 0 THEN 'V01 energia negativa'
         WHEN f.energia_final_mwh > f.potencia_mw THEN 'K01 energia acima da potencia'
         WHEN f.cod_fonte = 'UFV' AND f.energia_final_mwh > 0
              AND EXTRACT(HOUR FROM f.data_hora) NOT BETWEEN 5 AND 18 THEN 'K03 solar gerando a noite'
         WHEN f.energia_final_mwh > 0 AND EXISTS (
                 SELECT 1 FROM campo_real_energia.parada_usina p
                 JOIN dw_campo_real.ref_depara_usina dp2 ON dp2.id_usina_origem = p.id_usina
                 WHERE dp2.id_usina_canonico = f.id_usina_canonico AND p.fim >= p.inicio
                   AND f.data_hora BETWEEN p.inicio AND p.fim) THEN 'K02 geracao durante parada'
         WHEN f.travado THEN 'A01 medidor travado'
         WHEN f.energia_final_mwh > f.disponibilidade_mw THEN 'K08 acima da disponibilidade'
         ELSE NULL
       END AS motivo_quarentena
FROM f;

CREATE INDEX IF NOT EXISTS ix_medicao_class_motivo ON stg.medicao_classificada (motivo_quarentena);
