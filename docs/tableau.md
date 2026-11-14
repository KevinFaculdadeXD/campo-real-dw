# Painel no Tableau · passo a passo

O painel lê **somente** o schema `dw_campo_real`. Não use `campo_real_energia`, `stg` nem `raw`.

## 1. Conexão
Conectar a PostgreSQL (neondb, SSL exigido) e escolher o schema `dw_campo_real`. Arraste para a planilha estas views/tabelas e use **Extrair** (mais rápido que conexão ativa):

| Fonte | Para |
|---|---|
| `vw_receita_horaria` | perguntas 1, 2, 3, 4 |
| `vw_pld_horario` | pergunta 4 (mapa de calor) |
| `vw_paradas` | pergunta 5 |
| `qualidade_metricas`, `qualidade_indice`, `qualidade_antes_depois`, `qualidade_impacto_tratamento` | pergunta 7 |
| `vw_clima_geracao` | pergunta 6 (opcional) |

Dica: coloque cada fonte em uma conexão separada (não faça junção entre elas); as views já trazem as dimensões.

## 2. Campos calculados (em `vw_receita_horaria`)
- **Geração (MWh)**: `SUM([energia_mwh])`
- **Receita (R$)**: `SUM([receita_rs])`
- **Preço capturado (R$/MWh)**: `SUM([receita_rs]) / SUM([energia_mwh])`
- **Razão de captura**: `SUM([receita_rs]) / SUM([energia_x_pld_medio_rs])`
- **Fator de capacidade**: `SUM([energia_mwh]) / SUM([potencia_mw])` (cada linha é uma hora, então a soma da potência é a energia máxima possível). Formatar como %.

## 3. Planilhas
| # | Pergunta | Construção |
|---|---|---|
| 1 | Geração por usina, fonte e submercado ao longo do ano | Barras: `usina` em Linhas, Geração em Colunas, cor por `fonte`. Segunda planilha: linha de `ano_mes` por `fonte`. Terceira: tabela com Fator de capacidade por usina. |
| 2 | Quanto vale a geração ao PLD | Cartão com Receita total. Barras de Receita por `fonte`. Linha de Receita por `ano_mes`. |
| 3 | Qual fonte captura o melhor preço | Barras com Preço capturado por `fonte` e uma segunda com Razão de captura (linha de referência em 1). |
| 4 | Horas e meses de PLD alto e geração nesses momentos | Mapa de calor em `vw_pld_horario`: `hora` em Colunas, `nome_mes` em Linhas, cor = `AVG([pld_rs_mwh])`. Perfil horário: linhas de `AVG([energia_mwh])` por `hora`, cor `fonte` (em `vw_receita_horaria`). |
| 5 | Perdas com paradas | Em `vw_paradas`: barras de `SUM([horas_indisponiveis])`, `SUM([energia_estimada_mwh])` e `SUM([receita_estimada_rs])` por `tipo_parada`. Detalhe por `usina`. **Nota de rodapé**: onde `base_estimativa` é "sem base", a energia não é estimada. |
| 7 | Podemos confiar nos números | `qualidade_indice`: barras de `indice_pct` por `dimensao`. `qualidade_metricas`: tabela com regra, falhas e decisão. `qualidade_antes_depois` (linha TOTAL): receita antes × depois. `qualidade_impacto_tratamento`: barras de linhas por tratamento. |

## 4. História (3 painéis + recomendação)
1. **A pergunta**: título com a pergunta da diretoria e os cartões Geração, Receita e Preço capturado.
2. **A evidência**: perguntas 1 a 5 em dois painéis (geração e valor; preço e paradas).
3. **Podemos confiar?**: pergunta 7, com antes × depois.
4. **Recomendação**: caixa de texto final (preencha com os números reais; ver `docs/roteiro_apresentacao.md`).

Inclua no painel as fontes: "PLD: CCEE, dados abertos (CC-BY 4.0). Clima: Open-Meteo (uso não comercial, com atribuição)."
Salve como **.twbx** (pasta de trabalho empacotada) para entregar.
