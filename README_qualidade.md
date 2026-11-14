# Etapa 2 · Qualidade de dados

```bash
# 1. DDL das tabelas de qualidade (uma vez; pode repetir). Pelo DBeaver: abrir o arquivo e Alt+X
psql "<string de conexao>" -f sql/03_qualidade/01_ddl_qualidade.sql

# 2. Profiling + 43 regras (7 dimensoes). Grava em qualidade.metricas, decisoes e perfil_colunas
python -m src.qualidade.executar
```
Opcoes: `--so-perfil`, `--sem-perfil`. Cada execucao tambem entra em `qualidade.log_execucao`.

Consultas uteis: `qualidade.v_metricas_ultimo_lote`, `qualidade.v_indice_qualidade`, `qualidade.decisoes`.
Limites do PLD (ANEEL) em `qualidade.limites_pld`. As regras nao alteram a origem; as decisoes
(corrigir, descartar, quarentena, sinalizar) sao aplicadas no caminho ate o DW.
