# Refatoração do UTM — documentos

| Documento | Conteúdo |
|---|---|
| [`2026-09-20-utm-modernization-rfc.md`](2026-09-20-utm-modernization-rfc.md) | Análise técnica verificada, arquitetura-alvo e plano de migração |
| [`QUICK_FIXES.md`](QUICK_FIXES.md) | As 5 correções pontuais da seção 9 — status e passos na VM |
| [`poc/verify_findings.py`](poc/verify_findings.py) | Reprodução executável dos achados |
| [`../../tests/test_quick_fixes.py`](../../tests/test_quick_fixes.py) | Testes de regressão das correções |
| [`../../tools/audit_stats_interval.py`](../../tools/audit_stats_interval.py) | Auditoria dos três intervalos (F6/H1) |

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

| # | Achado | Sev. | Situação |
|---|---|---|---|
| F1 | Senha do UCS em texto claro no `.pickle` | Crítica | 🟡 contido (`0600`) — remoção do `pickle` na Fase 1 |
| F2 | `pickle.load()` de arquivo gravável = RCE | Crítica | 🟡 contido (recusa arquivo inseguro) — Fase 1 |
| F3 | Injeção de Line Protocol via descrição de porta | Crítica | 🔴 aberto — Fase 2, escape no exporter |
| F4 | Uma exceção descarta o ciclo de todos os domínios | Alta | 🟡 detectável (`UTMCollectorHealth`) — Fase 3 |
| F5 | `UnboundLocalError` em `print_output_in_influxdb_lp()` | Alta | ✅ **corrigido** |
| F6 | Taxa de banda depende de 3 configs não sincronizadas | Alta | 🟡 auditável (`tools/`) — Fase 2 |
| F7 | `iom_slot_id` vaza → PAUSE no IOM errado | Alta | 🔴 aberto — Fase 2 |
| F8 | `get_fi_id_from_dn()` erra fabric por substring | Média | 🔴 aberto — Fase 2 |
| F9 | `isFloat()` valida com `float()`, converte com `int()` | Média | 🔴 aberto — Fase 2 |
| F10 | `'associated' in 'unassociated'` | Média | 🔴 aberto — Fase 2 |
| F11 | `cleanup_ucs_connections()` quebra com `--no-ssh` | Média | ✅ **corrigido** |
| F12 | `-ct` não controla o timeout do stats pull do SDK | Média | 🔴 aberto — Fase 3 |

As cinco correções pontuais da seção 9 do RFC estão aplicadas. Detalhes e os
passos que ainda dependem de ação na VM: [`QUICK_FIXES.md`](QUICK_FIXES.md).

Hipóteses ainda **não** confirmadas (H1–H4) estão na seção 5 do RFC, separadas
dos fatos. H1 (divergência entre stat collection policy e `polling_interval`)
é a mais urgente: se confirmada, os números de banda dos dashboards estão
errados hoje.
