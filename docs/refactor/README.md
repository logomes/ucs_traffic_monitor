# Refatoração do UTM — documentos

| Documento | Conteúdo |
|---|---|
| [`2026-09-20-utm-modernization-rfc.md`](2026-09-20-utm-modernization-rfc.md) | Análise técnica verificada, arquitetura-alvo e plano de migração |
| [`poc/verify_findings.py`](poc/verify_findings.py) | Reprodução executável dos achados |

## Reproduzir os achados

```sh
python3 -m pip install ucsmsdk          # opcional; sem ele, F1 é pulado
python3 docs/refactor/poc/verify_findings.py
python3 docs/refactor/poc/verify_findings.py --finding F3
```

Sai com 0 se todos os defeitos forem reproduzidos. Não acessa nenhum UCS —
cada verificação extrai o trecho real de `telegraf/ucs_traffic_monitor.py`,
com a referência de linha no docstring.

## Achados

| # | Achado | Sev. | Correção proposta |
|---|---|---|---|
| F1 | Senha do UCS em texto claro no `.pickle` | Crítica | Fase 1 — remover o `pickle` |
| F2 | `pickle.load()` de arquivo gravável = RCE | Crítica | Fase 1 — remover o `pickle` |
| F3 | Injeção de Line Protocol via descrição de porta | Crítica | Fase 2 — escape no exporter |
| F4 | Uma exceção descarta o ciclo de todos os domínios | Alta | Fase 3 — isolamento por domínio |
| F5 | `UnboundLocalError` em `print_output_in_influxdb_lp()` | Alta | **correção pontual** (`:2793`) |
| F6 | Taxa de banda depende de 3 configs não sincronizadas | Alta | Fase 2 — `transform/rates.py` |
| F7 | `iom_slot_id` vaza → PAUSE no IOM errado | Alta | Fase 2 — função pura |
| F8 | `get_fi_id_from_dn()` erra fabric por substring | Média | Fase 2 — regex ancorada |
| F9 | `isFloat()` valida com `float()`, converte com `int()` | Média | Fase 2 |
| F10 | `'associated' in 'unassociated'` | Média | Fase 2 — `StrEnum` |
| F11 | `cleanup_ucs_connections()` quebra com `--no-ssh` | Média | **correção pontual** (`:607`) |
| F12 | `-ct` não controla o timeout do stats pull do SDK | Média | Fase 3 |

Hipóteses ainda **não** confirmadas (H1–H4) estão na seção 5 do RFC, separadas
dos fatos. H1 (divergência entre stat collection policy e `polling_interval`)
é a mais urgente: se confirmada, os números de banda dos dashboards estão
errados hoje.
