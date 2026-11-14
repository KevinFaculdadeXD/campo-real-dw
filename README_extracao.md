# Etapa 1 · Extração (CCEE + Open-Meteo)

Trecho do README para colar no README principal do repositório.

## Requisitos e configuração
```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy config.example.ini config.ini   # e preencha host/usuario/senha do Neon
```
`config.ini` está no `.gitignore`. A senha também pode vir da variável `CRE_PG_PASSWORD`.

## Ordem de execução (na raiz do projeto)
```bash
# 1. DDL (uma vez; pode repetir). Pelo DBeaver: abrir o arquivo e Alt+X
psql "<string de conexao>" -f sql/02_extracao/01_ddl_extracao.sql

# 2. PLD horário da CCEE (2025 e 2026): extrai para o raw e trata para o stg
python -m src.extracao.ccee_pld

# 3. Clima por usina (Open-Meteo): raw e stg
python -m src.extracao.open_meteo
```
Opções úteis: `--anos 2026`, `--full` (ignora o que já foi baixado), `--so-tratar`, `--sem-tratar`.

## O que cada tabela guarda
| Tabela | Camada | Grão | Conteúdo |
|---|---|---|---|
| `raw.ccee_pld_horario` | raw | 1 registro da API | JSON como chegou + `extraido_em`, `fonte_url`, `resource_id`, `id_execucao` |
| `stg.pld_horario_tratado` | tratada | submercado × hora | tipos, chave `(cod_submercado, data_hora)`, rastreável ao raw por `id_raw` |
| `stg.pld_horario_quarentena` | tratada | 1 registro raw | o que não pôde ser interpretado, com o motivo |
| `raw.openmeteo_resposta` | raw | usina × intervalo | JSON da resposta + coordenada enviada, URL e parâmetros |
| `stg.clima_horario` | tratada | usina × hora | temperatura, vento 10 m/100 m, radiação, chuva |
| `qualidade.log_execucao` | log | 1 execução de processo | início, fim, linhas lidas/gravadas, status, erro, detalhes (JSON) |

## Decisões de projeto
- **Raw intocado:** o registro é guardado como veio (jsonb). `UNIQUE (resource_id, row_hash)` impede duplicar o que já foi baixado.
- **Retomada, não re-download:** a extração começa no offset igual ao que já está no raw (a API é lida ordenada por `_id`). `--full` refaz.
- **Falhas tratadas:** tempo limite, 5xx e erro de conexão (espera exponencial com jitter), 429 (respeita `Retry-After`), resposta que não é JSON, resposta vazia, colunas novas (aviso) ou ausentes (erro), `sort` recusado (fallback).
- **Paginação:** `limit/offset`; para quando a página volta vazia ou o offset alcança `total`; trava de 2000 páginas.
- **Cada página é commitada**, então uma queda no meio preserva o progresso.
- **Log em conexão própria (autocommit):** o erro fica registrado mesmo se a carga der rollback.
- **Tratamento não "conserta" valor:** PLD negativo ou absurdo **passa** para o stg; julgar faixa é papel da Etapa 2. Só vai para a quarentena o que não dá para interpretar (submercado desconhecido, data/hora/PLD ilegível).
- **Hora 1–24:** se o dataset trouxer HORA de 1 a 24, aplica-se −1h (mesma regra do script da professora).
- **Repetidos** para o mesmo submercado/hora: prevalece o mais recente e o anterior vai para a quarentena com o motivo.
- **Clima:** as coordenadas vêm do cadastro **sem correção** (coordenada fora do Brasil gera aviso no log). Corrigir é decisão da Etapa 2.

## Se uma fonte cair
A execução fica em `qualidade.log_execucao` com `status = 'ERRO'` e a mensagem. Documente no relatório: horário, o erro, quantas tentativas, e o que o processo fez (o ano seguinte continua; o que já estava no raw é preservado). Consulta:
```sql
SELECT id_execucao, processo, status, inicio, fim, linhas_lidas, linhas_gravadas, erro, detalhes
FROM qualidade.log_execucao ORDER BY id_execucao DESC;
```

## Fontes e licenças (citar no painel e no README)
- CCEE · Dados Abertos, conjunto PLD_HORARIO — CC-BY 4.0 — https://dadosabertos.ccee.org.br/dataset/pld_horario
- Open-Meteo.com, Historical Weather API — CC-BY 4.0, uso não comercial — https://open-meteo.com/en/docs/historical-weather-api

## Testes
```bash
PYTHONPATH=. python tests/test_ccee_parse.py
```
