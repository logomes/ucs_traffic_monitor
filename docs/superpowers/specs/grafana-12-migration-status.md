# Grafana 12 Auto-Migration Status

Status do bump pra Grafana 12.0.2, antes da migração manual de painéis Canvas.
Skeleton criado a partir de inspeção estática dos JSONs (deducível) +
células TBD para observação visual no browser.

## Resumo (deducível)

| Dashboard | Total panels | Native (auto-migra) | Angular (broken in G12) | Visual TBD |
|---|---|---|---|---|
| welcome | 10 | 10 | 0 | rendering check |
| local_sys | 11 | 11 | 0 | rendering check |
| locations | 22 | 21 | 1 | rendering check |
| domain_overview | 40 | 37 | 3 | rendering check |
| chassis_pause | 14 | 12 | 2 | rendering check |
| domain_traffic | 28 | 27 | 1 | rendering check |
| service_profile | 18 | 16 | 2 | rendering check |
| chassis_traffic | 11 | 10 | 1 | rendering check |
| ingress_congestion | 17 | 16 | 1 | rendering check |

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
