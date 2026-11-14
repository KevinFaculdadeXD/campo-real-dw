# Roteiro da apresentação (12 a 13 minutos)

| Tempo | Slide | O que dizer |
|---|---|---|
| 0:00 | Pergunta | "Quanto nossa geração vale, onde e quando ganhamos ou perdemos, e podemos confiar nos números?" |
| 0:45 | Arquitetura | Fontes (origem, CCEE, Open-Meteo) → raw → qualidade → DW → painel. Tudo reproduzível por scripts. |
| 2:00 | Extração | PLD pela API CKAN da CCEE; o portal respondeu 403 (registrado no log); processo seguiu por CSV carregado por Python com SHA-256 e autorização da professora. Open-Meteo por usina. Raw preservado, retry e log. |
| 3:30 | Qualidade | 43 regras em 7 dimensões, métricas em tabela. 3 exemplos fortes: usina duplicada, latitude no oceano, medidor travado por 3 dias. Decisões justificadas. |
| 5:00 | Antes × depois | Receita e preço capturado antes e depois da limpeza. Dizer o número real. |
| 6:00 | Modelo | Star schema: 4 fatos, 5 dimensões, grão declarado, SCD tipo 2 em usina, dim_tempo própria. |
| 7:30 | Painel · valor | Geração, receita ao PLD, fonte que captura melhor preço. |
| 9:00 | Painel · quando | Mapa de calor hora × mês e perfil de geração: geramos nas horas caras? |
| 10:00 | Painel · paradas | Horas, energia e receita perdidas por tipo de parada. |
| 11:00 | Confiança | Índice por dimensão e o que ainda não é confiável (clima da usina com coordenada corrigida, estimativa de paradas). |
| 12:00 | Recomendação | 2 ou 3 ações com base nos números (ex.: priorizar manutenção fora do pico de PLD; corrigir cadastro na origem; reprocessar o clima). |

Prepare: uma frase para o 403 ("a fonte estava fora do ar; documentamos e usamos a alternativa autorizada"), e o print da autorização.
