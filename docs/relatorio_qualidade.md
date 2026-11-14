# Relatório de qualidade de dados

Gerado automaticamente a partir de `qualidade.metricas`, `qualidade.decisoes` e das tabelas `qualidade_antes_depois` e `qualidade_impacto_tratamento` do DW.

## Índice por dimensão (100 × (1 − falhas / avaliados))

| Dimensão | Índice (%) |
|---|---|
| completude | 87,99 |
| unicidade | 96,65 |
| validade | 96,68 |
| consistencia | 95,78 |
| acuracia | 99,78 |
| integridade_referencial | 99,99 |
| atualidade | 99,36 |

## Problemas por dimensão, decisão e justificativa

### Completude

| Regra | Tabela | Problema | Avaliados | Falhas | % | Decisão | Justificativa |
|---|---|---|---|---|---|---|---|
| C01 | medicao_geracao | Energia nula (falha de comunicacao do medidor) | 78.798 | 6 | 0,008 | quarentena | Nao sabemos quanto a usina gerou. Imputar zero subestima e imputar media inventa dado. Fica fora da geracao valorada e aparece como hora sem leitura valida. |
| C02 | medicao_geracao | Medicao sem usina (id_usina nulo) | 78.798 | 1 | 0,001 | quarentena | Energia sem dono nao pode ser valorada: o PLD depende do submercado da usina. Mantida na quarentena para auditoria e nao entra no DW. |
| C03 | medicao_geracao | Horas faltantes por usina em 2025 (usina x hora) | 78.840 | 96 | 0,122 | sinalizar | A lacuna vira ausencia de linha no fato e a cobertura aparece no painel. Preencher por interpolacao criaria geracao que ninguem mediu. |
| C04 | usina | Municipio em branco no cadastro | 10 | 1 | 10,000 | descartar | O unico cadastro sem municipio e a usina duplicada (ver U02); ele sai junto com ela. |
| C05 | pld_horario_tratado | Horas de PLD faltantes por submercado | 65.472 | 0 | 0,000 | sinalizar | Hora sem preco nao pode ser valorada. Ela nao entra na receita e a cobertura e informada. |
| C06 | clima_horario | Variavel de clima nula | 162.240 | 0 | 0,000 | sinalizar | Valor ausente na fonte externa nao deve ser preenchido. A correlacao ignora as horas sem dado. |
| C07 | clima_horario | Horas de clima faltantes por usina | 162.240 | 0 | 0,000 | sinalizar | Mesmo motivo de C06: a hora fica sem clima, sem estimativa. |
| C08 | feriado_nacional | Ano do PLD sem feriados cadastrados (2026) | 2 | 1 | 50,000 | corrigir | A tabela de origem so tem 2025. Os feriados nacionais sao datas fixas em lei (mais Sexta-feira Santa), entao a dim_tempo do DW complementa 2026 com o calendario oficial. A origem nao e alterada. |

### Unicidade

| Regra | Tabela | Problema | Avaliados | Falhas | % | Decisão | Justificativa |
|---|---|---|---|---|---|---|---|
| U01 | medicao_geracao | Mesma usina e hora com mais de uma medicao | 78.797 | 28 | 0,035 | descartar | Duas causas: reprocessamento da integracao (valores identicos) e lancamento MANUAL 10% acima da leitura automatica. Vale a leitura SCADA mais antiga: manter as duas dobraria energia e receita, e o manual nao tem evidencia que justifique sobrescrever o medidor. |
| U02 | usina | Usina cadastrada duas vezes (mesmas coordenadas e fonte) | 10 | 1 | 10,000 | corrigir | CRE-EOL-07 repete CRE-EOL-007: mesma fonte, coordenadas e potencia, codigo fora do padrao e sem municipio. De-para 10 -> 6 (o cadastro mais completo). A dim_usina fica com uma linha so. |
| U03 | usina | Nome repetido depois de normalizar (caixa, espacos) | 10 | 1 | 10,000 | corrigir | Mesma evidencia de U02 por outro caminho; tratada pelo mesmo de-para. |
| U04 | clima_horario | Clima repetido para a mesma usina e hora | 162.240 | 0 | 0,000 | sinalizar | A chave primaria ja impede. A regra fica como monitor e deve dar zero. |
| U05 | pld_horario_tratado | PLD repetido para o mesmo submercado e hora | 0 | 0 | - | descartar | Prevalece o registro mais recente (maior id_raw); o anterior vai para a quarentena e fica rastreavel. |

### Validade

| Regra | Tabela | Problema | Avaliados | Falhas | % | Decisão | Justificativa |
|---|---|---|---|---|---|---|---|
| V01 | medicao_geracao | Energia negativa | 78.792 | 4 | 0,005 | quarentena | Geracao bruta nao e negativa. O sinal sugere consumo de servicos auxiliares lancado como geracao; zerar seria inventar, entao a hora sai da geracao valorada. |
| V02 | medicao_geracao | Data fora de 2025 (erro de digitacao no ano) | 78.798 | 1 | 0,001 | quarentena | Ha uma leitura em 2052 cujo recebido_em e de 2025. Sugere erro de digitacao, mas essa hora ja tem leitura do medidor, entao nao corrigimos. |
| V03 | usina | Inicio de operacao no futuro | 10 | 1 | 10,000 | sinalizar | A usina mede energia desde janeiro de 2025, entao a data do cadastro e que esta errada. Nao sabemos a data certa: no DW fica desconhecida, com marca de suspeita, e as medicoes sao mantidas. |
| V04 | parada_usina | Parada com fim anterior ao inicio | 11 | 1 | 9,091 | quarentena | Nao da para saber qual das duas datas esta errada. Fica fora do calculo de energia nao gerada. |
| V05 | usina | Coordenada fora do Brasil | 10 | 1 | 10,000 | corrigir | A UFV Campo Real Minas esta com latitude +15,803, no oceano. Municipio (Janaiba/MG), UF e longitude indicam sinal trocado e todas as outras usinas tem latitude negativa. Corrige-se o sinal no DW. O clima dessa usina precisa ser baixado de novo com a coordenada certa. |
| V06 | usina | Codigo da usina fora do padrao CRE-XXX-000 | 10 | 1 | 10,000 | corrigir | E o mesmo cadastro duplicado de U02. Resolve-se com o de-para. |
| V07 | usina | Potencia instalada menor ou igual a zero | 10 | 0 | 0,000 | sinalizar | Sem a potencia nao ha fator de capacidade. Monitor: hoje deve dar zero. |
| V08 | pld_horario_tratado | PLD fora dos limites da ANEEL do ano | 65.472 | 0 | 0,000 | quarentena | Fora do piso ou do teto horario o numero nao pode ser um PLD. Nao se corrige preco. |
| V09 | clima_horario | Clima fora da faixa fisica | 162.240 | 0 | 0,000 | sinalizar | Valores impossiveis da fonte externa ficam marcados e fora das correlacoes. |

### Consistencia

| Regra | Tabela | Problema | Avaliados | Falhas | % | Decisão | Justificativa |
|---|---|---|---|---|---|---|---|
| K01 | medicao_geracao | Energia na hora acima da potencia instalada | 78.767 | 26 | 0,033 | quarentena | Uma usina de X MW nao gera mais que X MWh em uma hora. Pega virgula deslocada e picos de leitura. O valor certo nao e conhecido. |
| K02 | medicao_geracao | Geracao registrada durante parada | 1.672 | 4 | 0,239 | quarentena | As duas tabelas se contradizem (parada programada x energia). Sem saber qual esta certa, a hora sai da receita para nao valorar energia sem confirmacao. |
| K03 | medicao_geracao | Usina solar gerando de noite | 17.473 | 4 | 0,023 | quarentena | Sol nao gera as 20h. Pode ser relogio do medidor errado, mas sem o deslocamento exato nao ha como realocar a leitura para a hora certa. |
| K04 | usina | UF incompativel com o submercado da usina | 10 | 1 | 10,000 | corrigir | CRE-BIO-005 esta com UF=PE mas submercado SE, e as coordenadas e o municipio (Sertaozinho) apontam para SP. Corrige-se a UF para SP no DW. |
| K05 | medicao_geracao | Medicao anterior ao inicio de operacao da usina | 78.773 | 8.760 | 11,121 | sinalizar | Todas as horas da UFV Sertao do Sol caem aqui por causa da data de 2031 (V03). O erro e do cadastro, nao da medicao, entao as medicoes ficam. |
| K06 | medicao_geracao | Dado recebido antes da hora medida (relogio do servidor) | 78.798 | 25 | 0,032 | sinalizar | A energia nao e afetada, so o carimbo de chegada. Mantem-se a medicao e ignora-se o recebido_em dessas linhas na regra de atualidade. |
| K07 | pld_horario_tratado | Periodo de comercializacao ou mes diferentes da data/hora | 65.472 | 0 | 0,000 | quarentena | Confere a data/hora que montamos com as colunas da propria CCEE. Se discordam, ha erro de interpretacao ou de origem. |
| K08 | medicao_geracao | Energia maior que a disponibilidade declarada | 78.791 | 30 | 0,038 | quarentena | Entre colunas da mesma linha: nao se gera mais do que o disponivel. Costuma coincidir com K01 e K02. |

### Acuracia

| Regra | Tabela | Problema | Avaliados | Falhas | % | Decisão | Justificativa |
|---|---|---|---|---|---|---|---|
| A01 | medicao_geracao | Medidor travado: 6 horas ou mais com o mesmo valor | 62.095 | 72 | 0,116 | quarentena | Geracao real varia hora a hora. Valor constante por dias indica sensor congelado, e o valor verdadeiro e desconhecido. |
| A02 | medicao_geracao | Unidade errada (energia acima de 10x a potencia, provavel kWh) | 78.767 | 24 | 0,030 | corrigir | Dividir por 1000 apenas quando todas as 24 leituras do dia da usina passam de 10x a potencia e a origem e MANUAL (planilha em kWh). O resultado cai na faixa normal da usina, o que valida a hipotese. Casos isolados vao para a quarentena por K01. |
| A03 | medicao_geracao | Outlier estatistico (mais de 6 MAD da mediana da usina no mesmo mes e hora, so geracao > 0) | 62.061 | 34 | 0,055 | sinalizar | Pico plausivel fisicamente pode ser real. Fica marcado para revisao, sem alterar o valor. Horas zeradas ficam de fora porque zero e parada, noite ou termica desligada, nao erro. |
| A04 | pld_horario_tratado | PLD acima de 5x a mediana dos submercados na mesma hora | 65.472 | 252 | 0,385 | sinalizar | Teste com a mediana mensal marcou 427 horas que eram picos reais: em meses de piso a mediana e o proprio piso e varios valores chegaram exatamente ao teto horario da ANEEL (R$ 1.611,04). Por isso a referencia e a mesma hora nos outros submercados. Desacoplamento real entre submercados existe, entao so sinalizamos; a quarentena de preco fica com V08 (limites legais). |

### Integridade referencial

| Regra | Tabela | Problema | Avaliados | Falhas | % | Decisão | Justificativa |
|---|---|---|---|---|---|---|---|
| R01 | medicao_geracao | Medicao de usina que nao existe no cadastro | 78.797 | 24 | 0,030 | quarentena | Equipamento fora do cadastro (id 99): nao ha submercado nem fonte para valorar. Quarentena. |
| R02 | parada_usina | Parada de usina inexistente | 11 | 0 | 0,000 | quarentena | Sem usina nao ha como atribuir a parada. Monitor: deve dar zero. |
| R03 | usina | Usina com fonte inexistente | 10 | 0 | 0,000 | sinalizar | A origem tem FK; a regra e um monitor e deve dar zero. |
| R04 | usina | Usina com submercado inexistente | 10 | 0 | 0,000 | sinalizar | A origem tem FK; a regra e um monitor e deve dar zero. |
| R05 | pld_horario_tratado | PLD de submercado inexistente | 65.472 | 0 | 0,000 | sinalizar | Monitor do mapeamento de nomes da CCEE para os codigos do cadastro. |
| R06 | clima_horario | Clima de usina inexistente | 162.240 | 0 | 0,000 | sinalizar | Monitor: o clima so e baixado para usinas do cadastro. |

### Atualidade

| Regra | Tabela | Problema | Avaliados | Falhas | % | Decisão | Justificativa |
|---|---|---|---|---|---|---|---|
| T01 | medicao_geracao | Dado chegou mais de 24 horas depois da hora medida | 78.797 | 316 | 0,401 | sinalizar | A energia chegou tarde, mas esta correta: a analise usa data_hora. Reprocessamentos duplicados ja saem em U01. As linhas ficam marcadas para medir o atraso da integracao. |
| T02 | medicao_geracao | Usina parou de enviar dados (ultima hora mais de 24h atras) | 9 | 1 | 11,111 | sinalizar | Os dias sem dado aparecem como lacuna (C03) e a usina e destacada. Nao se estima geracao. |
| T03 | clima_horario | Horas de PLD sem clima (arquivo do Open-Meteo atrasado) | 16.368 | 144 | 0,880 | sinalizar | O arquivo historico atrasa alguns dias. As ultimas horas ficam sem clima e fora das correlacoes. |

## Impacto na geração (o que aconteceu com cada leitura de origem)

| Tratamento | Destino | Linhas | Energia original (MWh) | Energia final (MWh) |
|---|---|---|---|---|
| Carregada sem alteracao | mantida | 78.628 | 3.107.178,8 | 3.107.178,8 |
| A01 medidor travado | quarentena ou descarte | 72 | 2.250,0 | 2.250,0 |
| U01 medicao duplicada | quarentena ou descarte | 28 | 387,3 | 387,3 |
| R01 usina fora do cadastro | quarentena ou descarte | 24 | 1.702,1 | 1.702,1 |
| A02 corrigida (kWh para MWh) | corrigida | 24 | 749.154,0 | 749,2 |
| C01 energia nula | quarentena ou descarte | 6 | - | - |
| K02 geracao durante parada | quarentena ou descarte | 4 | 528,0 | 528,0 |
| K03 solar gerando a noite | quarentena ou descarte | 4 | 61,6 | 61,6 |
| V01 energia negativa | quarentena ou descarte | 4 | -3,4 | -3,4 |
| K01 energia acima da potencia | quarentena ou descarte | 2 | 1.774,6 | 1.774,6 |
| V02 data fora de 2025 | quarentena ou descarte | 1 | 55,2 | 55,2 |
| C02 medicao sem usina | quarentena ou descarte | 1 | 33,1 | 33,1 |

## Antes × depois da limpeza (valoração ao PLD)

Antes = leituras de origem como chegam, valoradas ao PLD do submercado da usina. Depois = fato_geracao do DW.

| Usina | Geração antes (MWh) | Geração depois (MWh) | Receita antes (R$) | Receita depois (R$) | Δ receita % | Preço capt. antes | Preço capt. depois |
|---|---|---|---|---|---|---|---|
| Total geral | 3.861.330,9 | 3.107.928,0 | 802.448.263,05 | 635.350.737,24 | -20,82 | 207,82 | 204,43 |
| UTE Bagaço Campo Real | 934.288,5 | 183.633,7 | 210.868.355,45 | 44.158.145,37 | -79,06 | 225,70 | 240,47 |
| EOL Coxilha Real | 133.973,8 | 133.474,8 | 31.657.829,91 | 31.595.035,75 | -0,20 | 236,30 | 236,71 |
| EOL Ventos do Potiguar | 493.165,9 | 493.169,3 | 97.928.996,20 | 97.929.195,44 | 0,00 | 198,57 | 198,57 |
| PCH Rio das Araucárias | 130.792,5 | 130.733,9 | 28.865.926,26 | 28.862.490,84 | -0,01 | 220,70 | 220,77 |
| UFV Campo Real Minas | 112.096,4 | 111.767,7 | 19.545.600,74 | 19.526.338,51 | -0,10 | 174,36 | 174,70 |
| UFV Sertão do Sol | 169.102,3 | 169.040,7 | 23.149.585,85 | 23.129.117,71 | -0,09 | 136,90 | 136,83 |
| UHE Campo Real Iguaçu | 973.338,1 | 972.062,5 | 218.687.494,08 | 218.577.665,79 | -0,05 | 224,68 | 224,86 |
| UHE Tocantins Real | 540.129,2 | 540.129,2 | 86.080.877,47 | 86.080.877,47 | 0,00 | 159,37 | 159,37 |
| UTE Gás Norte | 374.444,2 | 373.916,2 | 85.663.597,10 | 85.491.870,38 | -0,20 | 228,78 | 228,64 |
