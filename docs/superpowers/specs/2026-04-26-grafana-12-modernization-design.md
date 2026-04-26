# Grafana 12 Test-Env Modernization — Design Spec

**Date:** 2026-04-26
**Status:** Approved
**Owner:** lucgomes
**Target:** internal fork (sub-project 1 of stack modernization roadmap)
**Branch:** `feat/grafana-12-modernization` (new, branched off `feat/credentials-env-vars`)

---

## Problem

O test-env atual (e a produção) rodam Grafana 7.5.7, fora de suporte desde 2022. Bumping para Grafana 12 expõe duas classes de problema:

1. **52 painéis usam `agenty-flowcharting-panel`** — plugin baseado em Angular, que Grafana 11+ rejeita por design (Angular foi removido do core). Esses painéis aparecem como "Panel plugin not found".
2. **9 dashboards JSON em schema versions 22, 26, 27** — antigos mas suportados pelo auto-migrate de schema do Grafana ao importar; nem todos painéis legados (ex: `graph` panel) preservam configuração 100% após migração.

Sem migração, atualizar Grafana inutiliza a parte mais valiosa dos dashboards (visualização topológica de UCS via SVG colorido). Migrar todos os 52 painéis Angular pra Canvas levaria ~26h.

## Goals

1. test-env rodando Grafana 12.0.2 + Telegraf 1.38 + InfluxDB 1.11 (mantido).
2. Os 9 dashboards JSON importados e schema-migrated automaticamente; painéis nativos (graph/table/stat) renderizando.
3. **6 painéis Angular dos 3 dashboards principais** (`domain_overview`, `locations`, `chassis_pause`) reconstruídos como Canvas panels nativos do Grafana 12, ligados às mesmas queries InfluxQL.
4. Os 46 painéis Angular restantes ficam como "Panel plugin not found" (aceitável); text panel informativo no topo dos 4 dashboards afetados explica o estado.
5. Backup do estado pré-migração preservado em `grafana/dashboards/legacy/` para retorno rápido.
6. Branch isolado (`feat/grafana-12-modernization`) — `feat/credentials-env-vars` permanece intocado como ponto de retorno.

## Non-Goals

- Migrar os 46 painéis Angular restantes (`domain_traffic`, `service_profile`, `chassis_traffic`, `ingress_congestion`). Cada um é mini-projeto futuro.
- Migrar para InfluxDB 2/3. InfluxDB 1.11 mantido — drop-in das queries InfluxQL existentes.
- Production rollout (subproject 2 de stack modernization).
- Validação contra UCS real — sem hardware de UCS disponível.
- Reescrever queries — InfluxDB 1.11 mantém suporte completo.
- Adicionar autenticação ou hardening além do que já existe no test-env.

## Threat Model

Não aplicável diretamente — escopo é desenvolvimento local em test-env. Sem novos vetores de segurança introduzidos. Branch isolado evita impacto em produção.

---

## Architecture

```
ucs_traffic_monitor/                        (branch: feat/grafana-12-modernization)
├── test-env/
│   ├── .env.example              # GRAFANA_VERSION 11.4.0 → 12.0.2
│   │                             # TELEGRAF_VERSION 1.32-alpine → 1.38-alpine
│   └── (rest unchanged)
├── grafana/
│   ├── dashboards/               # bind-mountado pelo Grafana
│   │   ├── domain_overview.json  # MODIFICADO — 3 painéis Angular → Canvas
│   │   ├── locations.json        # MODIFICADO — 1 painel Angular → Canvas
│   │   ├── chassis_pause.json    # MODIFICADO — 2 painéis Angular → Canvas
│   │   ├── chassis_traffic.json  # MODIFICADO — text panel info adicionado
│   │   ├── domain_traffic.json   # MODIFICADO — text panel info adicionado
│   │   ├── ingress_congestion.json # MODIFICADO — text panel info adicionado
│   │   ├── service_profile.json  # MODIFICADO — text panel info adicionado
│   │   ├── welcome.json          # SEM MUDANÇA (auto-migra)
│   │   └── local_sys.json        # SEM MUDANÇA (auto-migra)
│   ├── legacy-dashboards/        # NOVO — backup pré-migração (NÃO bind-mountado)
│   │   ├── domain_overview.json
│   │   ├── locations.json
│   │   ├── chassis_pause.json
│   │   ├── chassis_traffic.json
│   │   ├── domain_traffic.json
│   │   ├── ingress_congestion.json
│   │   ├── service_profile.json
│   │   ├── welcome.json
│   │   └── local_sys.json
│   └── canvas-svgs/              # NOVO — SVGs extraídos pra reuso em Canvas
│       ├── domain_overview_topology.svg
│       ├── locations_map.svg
│       └── chassis_pause_backplane.svg
└── (rest unchanged from credentials work)
```

**Princípio:** sub-projeto é "self-contained no test-env". Nenhuma mudança no script `ucs_traffic_monitor.py`, no `lib/utm-common.sh`, ou em scripts de operador (`upgrade_utm.sh`, `backup_utm_dashboards.sh`).

---

## Component changes

### 1. `test-env/.env.example`

Trocar duas linhas:
```diff
-TELEGRAF_VERSION=1.32-alpine
+TELEGRAF_VERSION=1.38-alpine
-GRAFANA_VERSION=11.4.0
+GRAFANA_VERSION=12.0.2
```

(Operador também troca em `.env` local antes de `docker compose up -d --build`.)

### 2. `grafana/legacy-dashboards/` (novo, fora de `dashboards/`)

Cópia exata dos 9 JSONs originais antes da migração. Fica **fora** de `grafana/dashboards/` deliberadamente — assim o bind-mount existente (`../grafana/dashboards:/var/lib/grafana/dashboards:ro`) não os carrega no Grafana, e o provisioning do Grafana não tenta auto-importá-los.

Propósito: histórico para inspeção e rollback parcial via `cp grafana/legacy-dashboards/*.json grafana/dashboards/` se algo do trabalho de migração der errado.

### 3. `grafana/canvas-svgs/` (novo)

SVGs extraídos dos painéis `agenty-flowcharting-panel` originais. São reusados como background em Canvas panels.

Cada SVG salvo com nome descritivo:
- `domain_overview_topology.svg` — topologia FI-A/FI-B + chassis (vinha embebida no JSON v22 do `domain_overview`)
- `locations_map.svg` — mapa de localidades visuais
- `chassis_pause_backplane.svg` — visualização de slots backplane do chassis

Os SVGs ficam **inline em base64** dentro do dashboard JSON (campo `background.image`) — não exigem servidor externo nem URL absoluta. Salvar em arquivo separado é só pra inspeção/edição offline.

### 4. `grafana/dashboards/<3 dashboards>.json` (modificados)

Para cada um dos 3 dashboards-alvo:

**Workflow de modificação:**
1. Subir test-env com Grafana 12.0.2.
2. Importar dashboard original (auto-migrate).
3. Para cada `agenty-flowcharting-panel`:
   - Anotar SVG e mappings (queries + thresholds + colors).
   - Adicionar Canvas panel no mesmo grid layout (mesma posição/tamanho).
   - Definir background = SVG inline.
   - Para cada elemento dinâmico do mapping original, criar Element (Rectangle/Text) sobre o SVG na posição visual correspondente.
   - Bindings: `background-color` mapeada na query + thresholds (verde/amarelo/vermelho conforme valor); `text` opcional pra mostrar valor numérico.
4. Deletar o painel `agenty-flowcharting-panel` original.
5. Save dashboard from Grafana UI → exporta JSON novo.
6. Substitui o arquivo em `grafana/dashboards/`.

**Limites do Canvas vs flowcharting (documentar para o operador saber):**
- ❌ Não colore paths SVG por métrica (só retângulos sobrepostos)
- ❌ Sem animação de fluxo
- ✅ Tooltips com valor da métrica funcionam
- ✅ Click-through pra outro dashboard funciona

### 5. `grafana/dashboards/<4 outros dashboards>.json` (modificados, mínimo)

Adicionar Text Panel no topo (linha 0, full width) com markdown:

```markdown
> ⚠️ Os painéis de topologia visual deste dashboard ainda usam o plugin
> `agenty-flowcharting-panel` (Angular), incompatível com Grafana 11+.
> Os painéis nativos abaixo (gráficos, tabelas, métricas) funcionam
> normalmente. Migração planejada — ver `docs/superpowers/specs/`.
```

Mudança mínima: adicionar 1 panel object no array `panels[]` do JSON, sem tocar nos outros painéis.

---

## Data flow (não muda)

```
syn-data ──HTTP POST──► influxdb:8086/write?db=telegraf
                                          │
                                          ▼
                                    grafana:3000 ──InfluxQL queries──► influxdb
                                          │
                                          ▼
                                    dashboards renderizam
                                    (timeseries panels auto-migrated;
                                     Canvas panels com background SVG;
                                     Angular panels = "Panel plugin not found")
```

InfluxDB 1.11 mantido. Queries InfluxQL não mudam. Only o presentation layer evolui.

---

## Error handling / known issues

| Cenário | Comportamento esperado |
|---|---|
| Grafana 12 não instala (image pull fail) | docker compose mostra erro; rollback: `cd test-env && cp .env.example.backup .env` ou checkout do branch anterior |
| Telegraf 1.38 quebra exec input (improvável) | Visto em logs; rollback de `TELEGRAF_VERSION` no `.env` |
| Painel Canvas não renderiza | Inspecionar JSON exportado pelo Grafana (lookup `"type": "canvas"`); validar SVG inline e elementos |
| Grafana 12 rejeita JSON v22/v26/v27 | Não esperado — Grafana 12 mantém compat para schemas v18+. Se acontecer, rollback do dashboard e abrir sub-spec separado |
| Browser cache mostrando dashboard antigo | Hard refresh (Ctrl+Shift+R), ou `docker compose down -v && up` (apaga volume Grafana) |
| Auto-migrate de `graph` panel perde alguma config | Anotar e tocar manualmente o JSON após exportação inicial |
| Canvas elemento não cobre 100% da posição visual original | Aceitável — operador ainda vê o número nos panels nativos abaixo |

**Princípios:**
- Branch isolado = rollback é `git checkout feat/credentials-env-vars` em segundos.
- Subprojeto não toca em produção. Se Grafana 12 não funcionar, produção segue intocada.
- Cada Canvas panel migrado é independente — se um não der, não bloqueia os outros.

---

## Acceptance criteria

| # | Critério | Como verificar |
|---|---|---|
| 1 | test-env sobe com Grafana 12.0.2 e Telegraf 1.38 | `docker compose ps`; `curl http://localhost:3000/api/health` retorna `"version": "12.0.2"` |
| 2 | InfluxDB 1.11 continua respondendo | `curl /query?q=SHOW MEASUREMENTS` retorna 7 measurements |
| 3 | `welcome.json` e `local_sys.json` renderizam ≥ 90% dos painéis nativos | Visual no browser; screenshots |
| 4 | `domain_overview` tem 3 Canvas panels renderizando + outros panels nativos OK | Visual; Canvas reage ao syn-data |
| 5 | `locations` tem 1 Canvas panel renderizando + outros OK | Visual |
| 6 | `chassis_pause` tem 2 Canvas panels renderizando + outros OK | Visual |
| 7 | `domain_traffic`, `service_profile`, `chassis_traffic`, `ingress_congestion` têm text panel informativo no topo + outros panels nativos OK | Visual; grep no JSON pelo texto novo |
| 8 | `grafana/legacy-dashboards/*.json` contém os 9 originais pré-migração | `ls -1 grafana/legacy-dashboards/ \| wc -l` retorna 9 |
| 9 | Branch `feat/grafana-12-modernization` empurrada pro fork | `git push origin feat/grafana-12-modernization` + visível no GitHub |
| 10 | `feat/credentials-env-vars` segue intocada (rollback funciona) | `git diff feat/credentials-env-vars feat/grafana-12-modernization` mostra apenas mudanças deste sub-projeto |

---

## Migration / rollback

**Migration (operador local):**
```fish
cd ~/Downloads/ucs_traffic_monitor
git fetch origin
git checkout -b feat/grafana-12-modernization origin/feat/grafana-12-modernization
cd test-env
cp .env.example .env  # ou edite mantendo customizações locais
sg docker -c "docker compose down"
sg docker -c "docker compose up -d --build"
# aguarde ~90s pro stack subir, ~3-5min se for primeira pull do Grafana 12
```

**Rollback total (branch anterior):**
```fish
git checkout feat/credentials-env-vars
cd test-env
sg docker -c "docker compose down -v"
sg docker -c "docker compose up -d --build"
```

**Rollback parcial (manter Grafana 12 mas voltar dashboards):**
```fish
cp grafana/legacy-dashboards/*.json grafana/dashboards/
sg docker -c "docker compose restart grafana"
# aguarde 30s pro provisioning recarregar
```

---

## Delivery

Single delivery, single new branch. Tasks (~10-12) cobrem:

1. Criar branch `feat/grafana-12-modernization` a partir de `feat/credentials-env-vars`
2. Criar `grafana/legacy-dashboards/` com cópia dos 9 JSONs originais
3. Bumpar versões em `test-env/.env.example`
4. Subir stack, validar Grafana 12.0.2 e InfluxDB ainda respondem
5. Documentar em planilha o status pós-auto-migração de cada dashboard (Phase B do design)
6. Migrar 3 painéis Angular de `domain_overview` para Canvas (Phase C)
7. Migrar 1 painel Angular de `locations` para Canvas (Phase D)
8. Migrar 2 painéis Angular de `chassis_pause` para Canvas (Phase E)
9. Adicionar text panel info nos 4 dashboards "aceitos quebrados" (Phase F)
10. Validar todos os 10 acceptance criteria
11. Commit final + push

Estimativa: 7-8 horas focadas, distribuíveis em 2-3 sessões.

---

## Open questions

Nenhuma. Design fechado em conversa de 2026-04-26.

## Next step (after this delivery)

Sub-projeto 2 da modernização: **Production rollout no VM**. Atualizar defaults do `upgrade_utm.sh` (já refatorado) para Grafana 12.0.2 + Telegraf 1.38, documentar roteiro de upgrade na sua VM, testar.

Sub-projetos futuros (ainda não brainstormed):
- Migração dos 46 painéis Angular restantes — projetos por dashboard
- Avaliação InfluxDB 2/3 — projeto de pesquisa antes de implementação
