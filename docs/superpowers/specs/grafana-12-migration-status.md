# Grafana 12 Auto-Migration Status

Status do bump pra Grafana 12.0.2, antes da migração manual de painéis Canvas.
Skeleton criado a partir de inspeção estática dos JSONs (deducível) +
células TBD para observação visual no browser.

## Resumo (deducível, contagem recursiva)

Counts incluem painéis dentro de collapsed rows — Grafana 7 dashboards
agrupam painéis em `panels[].panels[]` quando estão em rows colapsadas.
Total de painéis Angular pra "aceitar quebrado" sem migração: 46.

| Dashboard | Total panels | Native (auto-migra) | Angular (broken in G12) | Visual TBD |
|---|---|---|---|---|
| welcome | 10 | 10 | 0 | rendering check |
| local_sys | 11 | 11 | 0 | rendering check |
| locations | 88 | 87 | 1 | rendering check (Canvas migration target) |
| domain_overview | 40 | 37 | 3 | rendering check (Canvas migration target) |
| chassis_pause | 24 | 22 | 2 | rendering check (Canvas migration target) |
| domain_traffic | 121 | 100 | 21 | rendering check (text panel notice) |
| service_profile | 66 | 51 | 15 | rendering check (text panel notice) |
| chassis_traffic | 22 | 17 | 5 | rendering check (text panel notice) |
| ingress_congestion | 64 | 59 | 5 | rendering check (text panel notice) |
| **TOTAL** | **446** | **394** | **52** | |

Migração planejada (Phase 3): 6 panels (`domain_overview` 3, `locations` 1, `chassis_pause` 2) → Canvas nativo.
Aceitos quebrados (Phase 4): 46 panels nos 4 dashboards restantes; cada um ganha text panel notice no topo.

## Visual observations (a preencher)

Para cada dashboard, abrir em http://localhost:3000 → folder UTM, e anotar:
- ✅ "Native panels render OK" (graphs/tables/stats com dados sintéticos)
- ❌ "Angular panels show 'Panel plugin not found'" (esperado, conta deve bater com a coluna acima)
- ⚠️ "Outras issues" (queries com erro, schema migration warning, etc.)

### welcome
TBD (visual)

### local_sys
TBD (visual)

### locations
TBD (visual)

### domain_overview
TBD (visual)

### chassis_pause
TBD (visual)

### domain_traffic
TBD (visual)

### service_profile
TBD (visual)

### chassis_traffic
TBD (visual)

### ingress_congestion
TBD (visual)
