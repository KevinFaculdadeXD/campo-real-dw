"""Catalogo de regras: cada regra tem dimensao, como medir e a decisao justificada.

A decisao fica junto da regra de proposito: quem le o codigo ve o que acontece com o problema.
Nenhuma regra altera a origem. As decisoes sao aplicadas no caminho ate o DW (etapa 3).
"""
from .regras import (Regra, condicao, duplicados, nulos, orfaos, lacunas_horarias, sequencia_repetida,
                     outlier_robusto, pld_vs_submercados, usinas_sem_dados_recentes,
                     horas_pld_sem_clima, anos_sem_feriados)

PERIODO_INI, PERIODO_FIM = "2025-01-01", "2025-12-31 23:00"
LIMITE_SUP = "2026-01-01"   # a base de medicao cobre 2025

# UF -> submercado do SIN (usado na regra de consistencia do cadastro)
UF_SUBMERCADO = {
    "SP": "SE", "MG": "SE", "RJ": "SE", "ES": "SE", "GO": "SE", "DF": "SE", "MT": "SE", "MS": "SE",
    "AC": "SE", "RO": "SE", "PR": "S", "SC": "S", "RS": "S",
    "BA": "NE", "SE": "NE", "AL": "NE", "PE": "NE", "PB": "NE", "RN": "NE", "CE": "NE", "PI": "NE",
    "PA": "N", "AM": "N", "AP": "N", "RR": "N", "TO": "N", "MA": "N",
}


def construir_catalogo(o="campo_real_energia"):
    med = f"{o}.medicao_geracao"
    usi = f"{o}.usina"
    par = f"{o}.parada_usina"
    pld = "stg.pld_horario_tratado"
    cli = "stg.clima_horario"
    m_u = f"{med} m JOIN {usi} u ON u.id_usina = m.id_usina"
    vals = ", ".join(f"('{uf}','{s}')" for uf, s in UF_SUBMERCADO.items())
    R = Regra

    return [
        # ------------------------------------------------------------ COMPLETUDE
        R("C01", "completude", "medicao_geracao", "Energia nula (falha de comunicacao do medidor)",
          nulos(med, "energia_mwh"), "quarentena",
          "Nao sabemos quanto a usina gerou. Imputar zero subestima e imputar media inventa dado. "
          "Fica fora da geracao valorada e aparece como hora sem leitura valida."),
        R("C02", "completude", "medicao_geracao", "Medicao sem usina (id_usina nulo)",
          nulos(med, "id_usina"), "quarentena",
          "Energia sem dono nao pode ser valorada: o PLD depende do submercado da usina. "
          "Mantida na quarentena para auditoria e nao entra no DW."),
        R("C03", "completude", "medicao_geracao", "Horas faltantes por usina em 2025 (usina x hora)",
          lacunas_horarias(m_u, "m.id_usina", "m.data_hora", PERIODO_INI, PERIODO_FIM), "sinalizar",
          "A lacuna vira ausencia de linha no fato e a cobertura aparece no painel. Preencher por "
          "interpolacao criaria geracao que ninguem mediu."),
        R("C04", "completude", "usina", "Municipio em branco no cadastro",
          nulos(usi, "municipio", considerar_vazio=True), "descartar",
          "O unico cadastro sem municipio e a usina duplicada (ver U02); ele sai junto com ela."),
        R("C05", "completude", "pld_horario_tratado", "Horas de PLD faltantes por submercado",
          lacunas_horarias(pld, "cod_submercado", "data_hora"), "sinalizar",
          "Hora sem preco nao pode ser valorada. Ela nao entra na receita e a cobertura e informada."),
        R("C06", "completude", "clima_horario", "Variavel de clima nula",
          condicao(cli, "temperatura_c IS NULL OR vento_10m_ms IS NULL OR vento_100m_ms IS NULL "
                        "OR radiacao_wm2 IS NULL OR chuva_mm IS NULL"), "sinalizar",
          "Valor ausente na fonte externa nao deve ser preenchido. A correlacao ignora as horas sem dado."),
        R("C07", "completude", "clima_horario", "Horas de clima faltantes por usina",
          lacunas_horarias(cli, "id_usina", "data_hora"), "sinalizar",
          "Mesmo motivo de C06: a hora fica sem clima, sem estimativa."),
        R("C08", "completude", "feriado_nacional", "Ano do PLD sem feriados cadastrados (2026)",
          anos_sem_feriados(pld, f"{o}.feriado_nacional"), "corrigir",
          "A tabela de origem so tem 2025. Os feriados nacionais sao datas fixas em lei (mais Sexta-feira "
          "Santa), entao a dim_tempo do DW complementa 2026 com o calendario oficial. A origem nao e alterada."),

        # ------------------------------------------------------------ UNICIDADE
        R("U01", "unicidade", "medicao_geracao", "Mesma usina e hora com mais de uma medicao",
          duplicados(med, "id_usina, data_hora", "id_usina IS NOT NULL AND data_hora IS NOT NULL"), "descartar",
          "Duas causas: reprocessamento da integracao (valores identicos) e lancamento MANUAL 10% acima da "
          "leitura automatica. Vale a leitura SCADA mais antiga: manter as duas dobraria energia e receita, "
          "e o manual nao tem evidencia que justifique sobrescrever o medidor."),
        R("U02", "unicidade", "usina", "Usina cadastrada duas vezes (mesmas coordenadas e fonte)",
          duplicados(usi, "latitude, longitude, id_fonte"), "corrigir",
          "CRE-EOL-07 repete CRE-EOL-007: mesma fonte, coordenadas e potencia, codigo fora do padrao e sem "
          "municipio. De-para 10 -> 6 (o cadastro mais completo). A dim_usina fica com uma linha so."),
        R("U03", "unicidade", "usina", "Nome repetido depois de normalizar (caixa, espacos)",
          duplicados(usi, "lower(regexp_replace(btrim(nome), '\\s+', ' ', 'g'))"), "corrigir",
          "Mesma evidencia de U02 por outro caminho; tratada pelo mesmo de-para."),
        R("U04", "unicidade", "clima_horario", "Clima repetido para a mesma usina e hora",
          duplicados(cli, "id_usina, data_hora"), "sinalizar",
          "A chave primaria ja impede. A regra fica como monitor e deve dar zero."),
        R("U05", "unicidade", "pld_horario_tratado", "PLD repetido para o mesmo submercado e hora",
          condicao("stg.pld_horario_quarentena", "motivo LIKE 'repetido%'"), "descartar",
          "Prevalece o registro mais recente (maior id_raw); o anterior vai para a quarentena e fica rastreavel."),

        # ------------------------------------------------------------ VALIDADE
        R("V01", "validade", "medicao_geracao", "Energia negativa",
          condicao(med, "energia_mwh < 0", "energia_mwh IS NOT NULL"), "quarentena",
          "Geracao bruta nao e negativa. O sinal sugere consumo de servicos auxiliares lancado como geracao; "
          "zerar seria inventar, entao a hora sai da geracao valorada."),
        R("V02", "validade", "medicao_geracao", "Data fora de 2025 (erro de digitacao no ano)",
          condicao(med, f"data_hora < '{PERIODO_INI}' OR data_hora >= '{LIMITE_SUP}'", "data_hora IS NOT NULL"),
          "quarentena",
          "Ha uma leitura em 2052 cujo recebido_em e de 2025. Sugere erro de digitacao, mas essa hora ja tem "
          "leitura do medidor, entao nao corrigimos."),
        R("V03", "validade", "usina", "Inicio de operacao no futuro",
          condicao(usi, "data_inicio_operacao > current_date"), "sinalizar",
          "A usina mede energia desde janeiro de 2025, entao a data do cadastro e que esta errada. Nao "
          "sabemos a data certa: no DW fica desconhecida, com marca de suspeita, e as medicoes sao mantidas."),
        R("V04", "validade", "parada_usina", "Parada com fim anterior ao inicio",
          condicao(par, "fim < inicio"), "quarentena",
          "Nao da para saber qual das duas datas esta errada. Fica fora do calculo de energia nao gerada."),
        R("V05", "validade", "usina", "Coordenada fora do Brasil",
          condicao(usi, "latitude NOT BETWEEN -34 AND 6 OR longitude NOT BETWEEN -74 AND -32"), "corrigir",
          "A UFV Campo Real Minas esta com latitude +15,803, no oceano. Municipio (Janaiba/MG), UF e longitude "
          "indicam sinal trocado e todas as outras usinas tem latitude negativa. Corrige-se o sinal no DW. "
          "O clima dessa usina precisa ser baixado de novo com a coordenada certa."),
        R("V06", "validade", "usina", "Codigo da usina fora do padrao CRE-XXX-000",
          condicao(usi, "cod_usina !~ '^CRE-[A-Z]{3}-[0-9]{3}$'"), "corrigir",
          "E o mesmo cadastro duplicado de U02. Resolve-se com o de-para."),
        R("V07", "validade", "usina", "Potencia instalada menor ou igual a zero",
          condicao(usi, "potencia_mw <= 0"), "sinalizar",
          "Sem a potencia nao ha fator de capacidade. Monitor: hoje deve dar zero."),
        R("V08", "validade", "pld_horario_tratado", "PLD fora dos limites da ANEEL do ano",
          condicao(f"{pld} t JOIN qualidade.limites_pld l ON l.ano = EXTRACT(YEAR FROM t.data_hora)::int",
                   "t.pld_rs_mwh < l.piso OR t.pld_rs_mwh > l.teto_horario"), "quarentena",
          "Fora do piso ou do teto horario o numero nao pode ser um PLD. Nao se corrige preco."),
        R("V09", "validade", "clima_horario", "Clima fora da faixa fisica",
          condicao(cli, "radiacao_wm2 < 0 OR radiacao_wm2 > 1500 OR vento_10m_ms < 0 OR vento_100m_ms < 0 "
                        "OR chuva_mm < 0 OR temperatura_c NOT BETWEEN -10 AND 50"), "sinalizar",
          "Valores impossiveis da fonte externa ficam marcados e fora das correlacoes."),

        # ------------------------------------------------------------ CONSISTENCIA
        R("K01", "consistencia", "medicao_geracao", "Energia na hora acima da potencia instalada",
          condicao(m_u, "m.energia_mwh > u.potencia_mw", "m.energia_mwh IS NOT NULL"), "quarentena",
          "Uma usina de X MW nao gera mais que X MWh em uma hora. Pega virgula deslocada e picos de leitura. "
          "O valor certo nao e conhecido."),
        R("K02", "consistencia", "medicao_geracao", "Geracao registrada durante parada",
          condicao(f"{med} m JOIN {par} p ON p.id_usina = m.id_usina AND m.data_hora BETWEEN p.inicio AND p.fim",
                   "m.energia_mwh > 0", "p.fim >= p.inicio AND m.energia_mwh IS NOT NULL"), "quarentena",
          "As duas tabelas se contradizem (parada programada x energia). Sem saber qual esta certa, a hora "
          "sai da receita para nao valorar energia sem confirmacao."),
        R("K03", "consistencia", "medicao_geracao", "Usina solar gerando de noite",
          condicao(f"{m_u} JOIN {o}.fonte_energia f ON f.id_fonte = u.id_fonte",
                   "m.energia_mwh > 0 AND EXTRACT(HOUR FROM m.data_hora) NOT BETWEEN 5 AND 18",
                   "f.cod_fonte = 'UFV' AND m.energia_mwh IS NOT NULL"), "quarentena",
          "Sol nao gera as 20h. Pode ser relogio do medidor errado, mas sem o deslocamento exato nao ha "
          "como realocar a leitura para a hora certa."),
        R("K04", "consistencia", "usina", "UF incompativel com o submercado da usina",
          condicao(f"{usi} u JOIN (VALUES {vals}) AS s(uf, cod) ON s.uf = u.uf", "s.cod <> u.cod_submercado"),
          "corrigir",
          "CRE-BIO-005 esta com UF=PE mas submercado SE, e as coordenadas e o municipio (Sertaozinho) "
          "apontam para SP. Corrige-se a UF para SP no DW."),
        R("K05", "consistencia", "medicao_geracao", "Medicao anterior ao inicio de operacao da usina",
          condicao(m_u, "m.data_hora < u.data_inicio_operacao", "m.data_hora IS NOT NULL"), "sinalizar",
          "Todas as horas da UFV Sertao do Sol caem aqui por causa da data de 2031 (V03). O erro e do "
          "cadastro, nao da medicao, entao as medicoes ficam."),
        R("K06", "consistencia", "medicao_geracao", "Dado recebido antes da hora medida (relogio do servidor)",
          condicao(med, "recebido_em < data_hora", "recebido_em IS NOT NULL AND data_hora IS NOT NULL"),
          "sinalizar",
          "A energia nao e afetada, so o carimbo de chegada. Mantem-se a medicao e ignora-se o recebido_em "
          "dessas linhas na regra de atualidade."),
        R("K07", "consistencia", "pld_horario_tratado", "Periodo de comercializacao ou mes diferentes da data/hora",
          condicao(pld, "periodo_comercializacao <> (EXTRACT(DAY FROM data_hora)::int - 1) * 24 "
                        "+ EXTRACT(HOUR FROM data_hora)::int + 1 OR mes_referencia <> to_char(data_hora, 'YYYYMM')"),
          "quarentena",
          "Confere a data/hora que montamos com as colunas da propria CCEE. Se discordam, ha erro de "
          "interpretacao ou de origem."),
        R("K08", "consistencia", "medicao_geracao", "Energia maior que a disponibilidade declarada",
          condicao(med, "energia_mwh > disponibilidade_mw", "energia_mwh IS NOT NULL AND disponibilidade_mw IS NOT NULL"),
          "quarentena",
          "Entre colunas da mesma linha: nao se gera mais do que o disponivel. Costuma coincidir com K01 e K02."),

        # ------------------------------------------------------------ ACURACIA
        R("A01", "acuracia", "medicao_geracao", "Medidor travado: 6 horas ou mais com o mesmo valor",
          sequencia_repetida(o, 6), "quarentena",
          "Geracao real varia hora a hora. Valor constante por dias indica sensor congelado, e o valor "
          "verdadeiro e desconhecido."),
        R("A02", "acuracia", "medicao_geracao", "Unidade errada (energia acima de 10x a potencia, provavel kWh)",
          condicao(m_u, "m.energia_mwh > 10 * u.potencia_mw", "m.energia_mwh IS NOT NULL"), "corrigir",
          "Dividir por 1000 apenas quando todas as 24 leituras do dia da usina passam de 10x a potencia e a "
          "origem e MANUAL (planilha em kWh). O resultado cai na faixa normal da usina, o que valida a hipotese. "
          "Casos isolados vao para a quarentena por K01."),
        R("A03", "acuracia", "medicao_geracao",
          "Outlier estatistico (mais de 6 MAD da mediana da usina no mesmo mes e hora, so geracao > 0)",
          outlier_robusto(o, 6), "sinalizar",
          "Pico plausivel fisicamente pode ser real. Fica marcado para revisao, sem alterar o valor. "
          "Horas zeradas ficam de fora porque zero e parada, noite ou termica desligada, nao erro."),
        R("A04", "acuracia", "pld_horario_tratado", "PLD acima de 5x a mediana dos submercados na mesma hora",
          pld_vs_submercados(pld, 5), "sinalizar",
          "Teste com a mediana mensal marcou 427 horas que eram picos reais: em meses de piso a mediana e "
          "o proprio piso e varios valores chegaram exatamente ao teto horario da ANEEL (R$ 1.611,04). "
          "Por isso a referencia e a mesma hora nos outros submercados. Desacoplamento real entre "
          "submercados existe, entao so sinalizamos; a quarentena de preco fica com V08 (limites legais)."),

        # ------------------------------------------------------------ INTEGRIDADE REFERENCIAL
        R("R01", "integridade_referencial", "medicao_geracao", "Medicao de usina que nao existe no cadastro",
          orfaos(med, "id_usina", usi, "id_usina"), "quarentena",
          "Equipamento fora do cadastro (id 99): nao ha submercado nem fonte para valorar. Quarentena."),
        R("R02", "integridade_referencial", "parada_usina", "Parada de usina inexistente",
          orfaos(par, "id_usina", usi, "id_usina"), "quarentena",
          "Sem usina nao ha como atribuir a parada. Monitor: deve dar zero."),
        R("R03", "integridade_referencial", "usina", "Usina com fonte inexistente",
          orfaos(usi, "id_fonte", f"{o}.fonte_energia", "id_fonte"), "sinalizar",
          "A origem tem FK; a regra e um monitor e deve dar zero."),
        R("R04", "integridade_referencial", "usina", "Usina com submercado inexistente",
          orfaos(usi, "cod_submercado", f"{o}.submercado", "cod_submercado"), "sinalizar",
          "A origem tem FK; a regra e um monitor e deve dar zero."),
        R("R05", "integridade_referencial", "pld_horario_tratado", "PLD de submercado inexistente",
          orfaos(pld, "cod_submercado", f"{o}.submercado", "cod_submercado"), "sinalizar",
          "Monitor do mapeamento de nomes da CCEE para os codigos do cadastro."),
        R("R06", "integridade_referencial", "clima_horario", "Clima de usina inexistente",
          orfaos(cli, "id_usina", usi, "id_usina"), "sinalizar",
          "Monitor: o clima so e baixado para usinas do cadastro."),

        # ------------------------------------------------------------ ATUALIDADE
        R("T01", "atualidade", "medicao_geracao", "Dado chegou mais de 24 horas depois da hora medida",
          condicao(med, "recebido_em - data_hora > interval '24 hours'",
                   f"recebido_em IS NOT NULL AND data_hora IS NOT NULL AND data_hora < '{LIMITE_SUP}'"),
          "sinalizar",
          "A energia chegou tarde, mas esta correta: a analise usa data_hora. Reprocessamentos duplicados "
          "ja saem em U01. As linhas ficam marcadas para medir o atraso da integracao."),
        R("T02", "atualidade", "medicao_geracao", "Usina parou de enviar dados (ultima hora mais de 24h atras)",
          usinas_sem_dados_recentes(o, LIMITE_SUP, 24), "sinalizar",
          "Os dias sem dado aparecem como lacuna (C03) e a usina e destacada. Nao se estima geracao."),
        R("T03", "atualidade", "clima_horario", "Horas de PLD sem clima (arquivo do Open-Meteo atrasado)",
          horas_pld_sem_clima(pld, cli), "sinalizar",
          "O arquivo historico atrasa alguns dias. As ultimas horas ficam sem clima e fora das correlacoes."),
    ]
