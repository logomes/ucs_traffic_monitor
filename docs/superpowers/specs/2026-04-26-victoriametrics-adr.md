# ADR: Migrate UTM datastore from InfluxDB v1 to VictoriaMetrics

**Date:** 2026-04-26
**Status:** Accepted
**Owner:** lucgomes
**Type:** Architecture Decision Record (decision-only; sub-projects implement)

---

## TL;DR

Substituir InfluxDB v1.10 (VM 2 atual) por **VictoriaMetrics single-node** numa **VM 3 greenfield**. VM 2 fica como fallback indefinido até validação completa. Migração decomposta em 3 sub-projetos: setup VM 3 → migração de queries InfluxQL → MetricsQL → cutover de Grafana datasource.

Trade-off principal: **reescrever ~50 queries em MetricsQL** em troca de melhor cardinality (4-7×), menor footprint operacional (single binary, single dir), e arquitetura mais alinhada com tendência atual de TSDB (PromQL ecosystem).

## Context

### Stack atual

- **VM 1**: Grafana 12 (já atualizada externamente)
- **VM 2**: InfluxDB 1.10 + Telegraf 1.38 + UTM script legado (`ucs_domains_group_*.txt` plaintext, dashboards via API import legacy)
- **VM 3**: nova, será provisionada para receber a stack moderna

### Drivers da decisão

Operador identificou três motivações:

1. **Performance / cardinality (B no questionário)** — InfluxDB v1 começando a sentir cardinality crescente conforme UCS expande blades/service profiles
2. **Suporte a longo prazo (C)** — InfluxDB v1.x está em "maintenance only", sem novas features. Risco gradual ao longo de 2-5 anos
3. **Features novas (D, condicional)** — abertura para conhecer paradigmas modernos (Flux, SQL, MetricsQL)

### Escala atual estimada

Categoria **B** (médio): 5-20 UCS domains, 500-2000 blades, retention 90-180 dias, banco 10-100 GB. Inflexion point onde v1 funciona mas v2/v3/VM brilham.

---

## Decision

**Migrar para VictoriaMetrics single-node em VM 3 greenfield.**

VictoriaMetrics ([documentação](https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/)) é um TSDB moderno baseado em PromQL/MetricsQL, single-binary, com Apache 2.0 license, mantido ativamente. Aceita ingestão via InfluxDB Line Protocol (Telegraf escreve sem trocar de plugin).

Decisão por single-node (não cluster) é apropriada para escala B — VictoriaMetrics single-node confortavelmente escala até "vários milhões de active series" segundo benchmarks publicados.

### Por quê VictoriaMetrics e não outras opções

Avaliadas durante brainstorming:

| Opção | Por que descartada |
|---|---|
| **InfluxDB v1.11 (manter)** | Resolve EOL parcial mas não traz benefício de cardinality. Adia o problema sem investir |
| **InfluxDB v2.7 OSS** | Queries InfluxQL continuam, mas operationally mais complex (orgs/buckets/tokens) sem grande ganho de perf vs v1 |
| **InfluxDB v3 OSS Core** | IOx engine moderno mas InfluxQL compat é parcial/imatura. SQL é o caminho nativo. Pesquisa Q1 2026 ainda mostra muitos arquétipos de query não suportados |
| **InfluxDB v3 Cloud Serverless** | Custo por consumo significativo no escala B; data egress charges; lock-in |
| **VictoriaMetrics + Prometheus** | Adicionar Prometheus a stack push-based (UTM coleta via Telegraf) é overhead sem ganho. Prometheus é pull-based; pra usá-lo bem, UTM precisaria virar exporter — projeto à parte sem motivação atual |
| **TimescaleDB** | PostgreSQL extension, SQL queries, mas operacionalmente pesado (Postgres a manter), e cardinality benchmarks ficam atrás de VictoriaMetrics na faixa B-C |

### Por quê VictoriaMetrics ganha

- **Cardinality**: 4-7× melhor que InfluxDB em benchmarks publicados; aguenta milhões de active series com poucos GB de RAM
- **Disk**: 7-10× menos disco que Prometheus pra mesmo dataset (compression algorithms agressivos)
- **Operação**: single binary, single data dir, defaults sensatos, todos config via flag CLI. Sem orgs/buckets/tokens
- **Telegraf compat**: aceita InfluxDB Line Protocol nativamente (`outputs.influxdb_v2` aponta para `:8428/influx/api/v2/write`)
- **Grafana plugin oficial**: maturo, mantido pela equipe VictoriaMetrics, aceita PromQL e MetricsQL
- **Cluster path quando precisar**: scale-up para vmselect/vminsert/vmstorage sem mudar API/datasource (futuro-proof)
- **Custo**: zero para single-node Apache 2.0 OSS; sem feature locked behind enterprise tier
- **Comunidade**: ativa, KubeCon talks, wide industry adoption (Wikipedia, Adidas, Cisco UCS Director uses Prometheus stack — overlapping ecosystem)

### Custo aceito

- **Reescrever ~50 queries InfluxQL → MetricsQL** nos 9 dashboards. Trabalho contido em sub-projeto 2.
- **Curva de aprendizado MetricsQL** (extensão de PromQL) — menor que SQL nativo do v3, mas diferente do mental model InfluxQL atual.
- **Schema rename**: Influx Line Protocol fields viram métricas separadas em VM (e.g., `FIEnvStats,domain=X load=0.5,total_memory=8192` → `FIEnvStats_load{domain="X"}` + `FIEnvStats_total_memory{domain="X"}`). Tags viram labels.

---

## Target architecture

```
┌─────────────────────────────────────────────────────────────┐
│  VM 1 (Grafana 12)                                          │
│  ├─ datasource1: InfluxDB v1 → http://VM2:8086/  (legacy)   │
│  └─ datasource2: VictoriaMetrics → http://VM3:8428/  (new)  │
└────────────┬─────────────────────────────────────┬──────────┘
             │ InfluxQL                           │ MetricsQL/PromQL
             │ (existing)                         │ (new)
             ▼                                    ▼
┌─────────────────────────────┐    ┌─────────────────────────┐
│  VM 2 (legacy fallback)     │    │  VM 3 (new target)      │
│  ├─ InfluxDB 1.10            │    │  ├─ VictoriaMetrics     │
│  ├─ Telegraf 1.38            │    │  ├─ Telegraf 1.38       │
│  └─ UTM script legacy        │    │  └─ UTM script v0.53    │
└─────────────────────────────┘    └─────────────────────────┘
       ▲                                      ▲
       │ exec input (current)                 │ exec input (parallel)
       │                                      │
       └──────────────┬───────────────────────┘
                      ▼
                ┌──────────┐
                │  UCS     │
                └──────────┘
```

### Componentes em VM 3

| Componente | Versão | Porta | Propósito |
|---|---|---|---|
| VictoriaMetrics | v1.110 (latest stable em 2026-04) | 8428 (HTTP) | Storage + query |
| Telegraf | 1.38 | — (exec, no listen) | Coleta UCS + push pra VM |
| UTM script | 0.53 (refactored) | — | Coleta UCS via SDK/SSH |
| systemd | — | — | Manage telegraf + creds.env |

**VM 1 (Grafana)** ganha um datasource adicional apontando para VM 3 (não substitui o existente — fica em paralelo durante validação).

### Data flow alvo

```
1. Telegraf na VM 3 executa exec input (a cada 60s):
   python3 ucs_traffic_monitor.py influxdb-lp --instance-name utm

2. Script lê env vars (creds.env), conecta UCS, emite Line Protocol em stdout.

3. Telegraf processa LP, envia para VM 3 via:
   [[outputs.influxdb_v2]]
     urls = ["http://localhost:8428/influx"]
     token = "..."          # opcional em VM, mas usa pra paridade

4. VictoriaMetrics armazena em /var/lib/victoria-metrics-data/.

5. Grafana (VM 1) consulta VM 3 em /api/v1/query, /api/v1/query_range
   via plugin oficial VictoriaMetrics datasource.
```

### Backup / DR

- VM 3 snapshots VM-level (whatever your hypervisor supports)
- VictoriaMetrics builtin snapshot endpoint (`/snapshot/create`) gera consistent snapshots em hot
- Retention configurada via flag `-retentionPeriod=180d`
- Sem replicação cross-VM no scope inicial; aceita-se que falha de VM 3 = restore de snapshot

---

## MetricsQL primer

Tradução das queries InfluxQL atuais. Conjunto representativo:

### Pattern 1 — Mean rate de bytes (ports)

**InfluxQL atual** (`domain_traffic.json`):
```sql
SELECT mean("bytes_rx_delta") *8/[[polling_interval]] AS "RX"
FROM "$db"."$rp"."FIServerPortStats"
WHERE ("domain" =~ /^${domain:regex}$/ AND "fi_id" = 'A' AND "port" =~ /^${port:regex}$/)
  AND $timeFilter
GROUP BY time($__interval), "port"
```

**MetricsQL equivalente**:
```promql
rate(FIServerPortStats_bytes_rx_delta{
    domain=~"$domain",
    fi_id="A",
    port=~"$port"
}[$__interval]) * 8
```

`rate()` calcula derivada por segundo automaticamente, eliminando `mean+polling_interval`. Mais conciso.

### Pattern 2 — Last value (status indicator)

**InfluxQL** (`domain_overview.json` leadership):
```sql
SELECT last("leadership") AS "leadership"
FROM "$db"."$rp"."FIEnvStats"
WHERE ("domain" =~ /^${domain:regex}$/ AND "fi_id" = 'A')
  AND $timeFilter
```

**MetricsQL**:
```promql
last_over_time(FIEnvStats_leadership{
    domain=~"$domain", fi_id="A"
}[$__range])
```

### Pattern 3 — Top 10 by traffic (table panel)

**InfluxQL**:
```sql
SELECT top("RX", "service_profile", 10) FROM (
    SELECT mean("bytes_rx_delta") *8/[[polling_interval]] AS "RX"
    FROM VnicStats
    WHERE ("domain" =~ /^${domain:regex}$/) AND $timeFilter
    GROUP BY service_profile
)
```

**MetricsQL**:
```promql
topk(10,
    sum by (service_profile) (
        rate(VnicStats_bytes_rx_delta{domain=~"$domain"}[$__rate_interval]) * 8
    )
)
```

`topk()` é built-in. Subqueries InfluxQL viram `sum by(...) ()` em MetricsQL.

### Pattern 4 — Counter monotonic delta (PAUSE frames)

**InfluxQL** (`chassis_pause.json`):
```sql
SELECT non_negative_difference(mean("pause_rx")) / [[polling_interval]] AS "RX PAUSE"
FROM BackplanePortStats
WHERE ("domain" =~ /^${domain:regex}$/ AND "chassis" =~ /^${chassis:regex}$/)
  AND $timeFilter
GROUP BY time($__interval), "chassis", "bp_port"
```

**MetricsQL**:
```promql
rate(BackplanePortStats_pause_rx{
    domain=~"$domain",
    chassis=~"$chassis"
}[$__rate_interval])
```

Counters são tratados nativamente por `rate()` (handles resets/restarts automaticamente).

### Pattern 5 — Sum across labels (aggregate by chassis)

**InfluxQL**:
```sql
SELECT sum("RX") FROM (
    SELECT mean("bytes_rx_delta") *8/[[polling_interval]] AS "RX"
    FROM VnicStats
    WHERE ("chassis" =~ /^${chassis:regex}$/) AND $timeFilter
    GROUP BY blade
)
GROUP BY chassis
```

**MetricsQL**:
```promql
sum by (chassis) (
    rate(VnicStats_bytes_rx_delta{chassis=~"$chassis"}[$__rate_interval]) * 8
)
```

### Pattern 6 — String fields (inventory)

**InfluxQL** (`service_profile.json` Server identity):
```sql
SELECT last("model") AS "model" FROM Servers
WHERE ("service_profile" =~ /^${service_profile:regex}$/)
  AND $timeFilter
```

**MetricsQL: NÃO suporta string values diretamente.** PromQL/MetricsQL é numeric-first. Solução padrão: usar **info-style metrics** com label values, ou expor model como `Servers_info{model="UCSB-B200-M5", service_profile="..."} = 1`.

Telegraf precisa de relabel/output config para isso. Workaround: queries de identidade ficam num panel separado consultando direto via API com `match[]=Servers_info{...}`. **Deal-breaker para alguns panels — investigar em sub-projeto 2**.

### Resumo curva de aprendizado

- **Padrões 1-5**: trivial após entender 4 funções (`rate`, `sum by`, `topk`, `last_over_time`). 1-2 dias de learning curve.
- **Pattern 6 (strings)**: não-trivial. Pode requerer mudar como Telegraf emite tags vs fields, ou aceitar perda de panels de identidade.
- **Recording rules**: VictoriaMetrics permite pré-computar agregações complexas (similar a InfluxDB Continuous Queries). Útil para queries pesadas em dashboards de alta-frequência refresh.

---

## Sub-project roadmap

### Sub-projeto 1 — VM 3 greenfield setup

**Goal:** VM 3 rodando VictoriaMetrics + Telegraf + UTM script. Receiving data via InfluxDB Line Protocol. Validated in test mode against syn-data ou UCS limitado.

**Estimate:** 4-6 horas (setup + smoke test + retention/backup config)

**Deliverables:**
- VictoriaMetrics instalado, systemd unit, retention configurada
- Telegraf reconfigurado com `outputs.influxdb_v2` apontando para VictoriaMetrics local
- UTM script (refactored, do prod-rollout sub-project) instalado
- systemd EnvironmentFile (creds.env) reutilizado
- Validação: `curl localhost:8428/api/v1/query?query=up` retorna dados; sample query retorna FIEnvStats_load

### Sub-projeto 2 — MetricsQL migration

**Goal:** 9 dashboards JSON com queries reescritas em MetricsQL, validadas contra VM 3 com dados reais.

**Estimate:** 8-16 horas (~50 queries × 5-15 min cada + validação visual)

**Deliverables:**
- Translation guide doc (extensão deste primer)
- 9 JSONs `grafana/dashboards/` atualizados (datasource type = victoriametrics)
- Per-dashboard validation report
- Recording rules para queries pesadas (se identificadas)
- Decision sobre Pattern 6 (string fields): mudar Telegraf config OR aceitar perda

### Sub-projeto 3 — Cutover

**Goal:** Grafana (VM 1) usa VM 3 como datasource primário. VM 2 ainda alive como fallback até retention period expirar.

**Estimate:** 2-4 horas (validation + datasource swap + monitoring)

**Deliverables:**
- VM 1 datasource provisioning yaml atualizado (VM 3 isDefault)
- Sanity check: dashboards renderizam sem erros, latência aceitável
- Documentação operacional: como apontar de volta pra VM 2 em caso de issue
- Plano de retirada de VM 2: 30/60/90 dias após cutover

---

## Risks and mitigations

| Risco | Prob | Impacto | Mitigação |
|---|---|---|---|
| Curva MetricsQL maior que esperada | Médio | Médio | VM 2 fallback indefinido; sem pressa |
| Pattern 6 (string fields) não tem solução clean | Médio | Baixo | Aceitar perda em panels de inventário OR investigar Telegraf relabel |
| Cardinality real surpreende (>10M series, single-node hits limit) | Baixo | Médio | VictoriaMetrics suporta scale-up trivial para cluster mode |
| Plugin Grafana VictoriaMetrics tem bug com Grafana 12 | Baixo | Médio | Issues em < 24h no GitHub; fallback Prometheus datasource (VM expõe API compat) |
| Telegraf v2-compat output tem comportamento inesperado | Baixo | Baixo | Sub-projeto 1 faz smoke test antes de prod |
| Dashboard regression visual (graphs diferentes mesmo com mesma intenção) | Alto | Baixo | Sub-projeto 2 documenta diff per-panel |
| Perda de dados ao retirar VM 2 prematuramente | Baixo | Alto | VM 2 fica viva 30+ dias após cutover; backup antes de retirar |
| VictoriaMetrics OSS não terá feature X que precisamos | Baixo | Baixo | Histórico mostra equipa adiciona features rapidamente; alternativa cluster mode disponível |

---

## Open questions

1. **Cardinality real em prod**: rodar `SHOW SERIES CARDINALITY ON telegraf` na VM 2 antes do sub-projeto 1. Resultado calibra sizing da VM 3.
2. **Volume de ingestão**: pontos/segundo? Backed-up bytes/dia? `du -sh /var/lib/influxdb/data` na VM 2 dá sense.
3. **Recording rules**: identificar quais queries em dashboards são pesadas (ex: subqueries com join across measurements) e pré-computar via VM rules. Sub-projeto 2 endereça.
4. **Backup strategy do VictoriaMetrics**: snapshot via API endpoint `/snapshot/create` com qual cadência? Onde armazenar (s3? local FS?)?
5. **Alerting**: vai usar `vmalert` (componente VM, alert rules em PromQL) ou Grafana alerts? Fora de escopo do MVP, mas mapear.
6. **String/inventory fields (Pattern 6)**: solução técnica? Sub-projeto 2 decide.
7. **Multi-tenancy futuro**: vai ter múltiplas orgs ou uso isolado da VM 3? Single-node suporta single tenant; cluster suporta multi-tenant.
8. **Retention period**: 90 dias? 180? Mais? Affects disk sizing. Cliente atual é 30d em InfluxDB; pode aumentar com VM (storage barato).

---

## Approval criteria

Este ADR está "accepted" quando:
1. Operador (lucgomes) lê e concorda com a decisão
2. Trade-off de query rewriting é compreendido e aceito
3. Roadmap de 3 sub-projetos é aprovado em alto nível (sem committar nas datas; apenas a ordem)
4. Open questions 1 e 2 (cardinality + volume) são levantados como pré-trabalho do sub-projeto 1

Após approval, sub-projeto 1 inicia com brainstorming → spec → plan próprios.

---

## References

- [VictoriaMetrics single-node docs](https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/)
- [VictoriaMetrics Grafana plugin](https://grafana.com/grafana/plugins/victoriametrics-metrics-datasource/)
- [VictoriaMetrics InfluxDB integration](https://docs.victoriametrics.com/victoriametrics/integrations/influxdb/)
- [VictoriaMetrics: Migrate from InfluxDB guide](https://docs.victoriametrics.com/guides/migrate-from-influx/)
- [High-cardinality TSDB benchmarks (VM vs Influx vs Timescale)](https://valyala.medium.com/high-cardinality-tsdb-benchmarks-victoriametrics-vs-timescaledb-vs-influxdb-13e6ee64dd6b)
- [MetricsQL reference](https://docs.victoriametrics.com/victoriametrics/metricsql/)
- [Prometheus alternatives 2026](https://simpleobservability.com/blog/prometheus-alternatives)

---

## Decision history

- **2026-04-26**: ADR drafted and accepted. Sub-projects 1, 2, 3 to follow in subsequent sessions.
