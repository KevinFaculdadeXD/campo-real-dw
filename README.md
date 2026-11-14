# Data Warehouse da Campo Real Energia

Extração de dados abertos, qualidade em Python, star schema em PostgreSQL e painel em Tableau.

## Requisitos
- Python 3.10+ e `pip install -r requirements.txt`
- PostgreSQL 13+ (usamos o Neon). O banco de origem vem do script `campo_real_energia_postgres.sql`.
- Tableau Desktop, só para abrir o painel.

## Configuração
1. Copie `config.example.ini` para `config.ini` e preencha a seção `[postgres]`. **Nunca suba o `config.ini` para o Git.** A senha também pode vir de `CRE_PG_PASSWORD`.
2. Execute o script do banco de origem no PostgreSQL (DBeaver: abrir e Alt+X).

## Ordem de execução
```bash
# Etapa 1: extração
psql <conexao> -f sql/02_extracao/01_ddl_extracao.sql
python -m src.extracao.ccee_pld            # PLD pela API da CCEE (API CKAN)
python -m src.extracao.ccee_pld_csv --ano 2025 --arquivo <csv>   # alternativa, se a API responder 403
python -m src.extracao.ccee_pld_csv --ano 2026 --arquivo <csv>
python -m src.extracao.open_meteo          # clima por usina

# Etapa 2: qualidade
psql <conexao> -f sql/03_qualidade/01_ddl_qualidade.sql
python -m src.qualidade.executar

# Etapa 3: data warehouse (executa os 4 scripts de sql/04_dw)
python -m src.dw.carregar

# Relatorio de qualidade (gera docs/relatorio_qualidade.md)
python -m src.qualidade.relatorio
```
Testes: `PYTHONPATH=. python tests/test_ccee_parse.py` e `PYTHONPATH=. python tests/test_qualidade_catalogo.py`.

## Estrutura
| Pasta | Conteúdo |
|---|---|
| `src/extracao` | extratores (CCEE por API e por CSV, Open-Meteo) com retry, raw e log |
| `src/qualidade` | regras reutilizáveis, catálogo com decisões, profiling, relatório |
| `src/dw` | executor da carga do data warehouse |
| `sql/02_extracao`, `03_qualidade`, `04_dw` | DDL e cargas versionados |
| `docs/` | modelagem, relatório de qualidade, roteiro do painel e da apresentação |

## Fontes e licenças
- **CCEE, PLD horário**: dadosabertos.ccee.org.br/dataset/pld_horario. CC-BY 4.0.
- **Open-Meteo, histórico**: archive-api.open-meteo.com. Uso não comercial, com atribuição.
- Limites do PLD: ANEEL (2025 e 2026), guardados em `qualidade.limites_pld`.

## Sobre o bloqueio da API da CCEE
Durante o trabalho a API respondeu **HTTP 403** a chamadas programáticas, enquanto o portal abria normalmente no navegador. O extrator registrou as tentativas em `qualidade.log_execucao` (execuções com ERRO). Com a autorização da professora, o PLD de 2025 e 2026 foi carregado por CSV **por código Python**, com o mesmo tratamento do extrator, o SHA-256 do arquivo no log e o dado bruto preservado em `raw.ccee_pld_horario`. Se a API for liberada, `python -m src.extracao.ccee_pld` volta a ser o caminho principal.

## Regras do trabalho cumpridas
As tabelas de origem nunca são alteradas: a limpeza acontece no caminho até o DW, e o painel lê somente `dw_campo_real`.
