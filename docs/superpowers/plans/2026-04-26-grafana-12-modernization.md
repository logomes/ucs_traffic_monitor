# Grafana 12 Test-Env Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bumpar test-env para Grafana 12.0.2 + Telegraf 1.38, manter InfluxDB 1.11, e migrar 6 painéis Angular críticos (em 3 dashboards) para Canvas nativo.

**Architecture:** Branch isolado `feat/grafana-12-modernization`. Backup pré-migração em `grafana/legacy-dashboards/`. Trabalho de Canvas é interativo no Grafana UI — JSON resultante exportado e versionado. Painéis Angular não-migrados ganham text panel informativo no topo dos dashboards afetados.

**Tech Stack:** Docker Compose, Grafana 12.0.2, Telegraf 1.38-alpine, InfluxDB 1.11, Canvas panel (built-in), bash, curl, jq.

**Spec:** `docs/superpowers/specs/2026-04-26-grafana-12-modernization-design.md`

**Repository:** `/home/lucgomes/Downloads/ucs_traffic_monitor`

---

## Phase 1 — Branch + version bump

### Task 1: Create new branch off `feat/credentials-env-vars`

**Files:** none modified — git operation only.

- [ ] **Step 1: Confirm clean state on the source branch**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
git checkout feat/credentials-env-vars
git status
```

Expected: working tree clean, branch up to date with `origin/feat/credentials-env-vars`.

- [ ] **Step 2: Create and switch to new branch**

```fish
git checkout -b feat/grafana-12-modernization
git branch --show-current
```

Expected: `feat/grafana-12-modernization`.

No commit (just branch creation).

---

### Task 2: Backup 9 dashboards to `grafana/legacy-dashboards/`

**Files:**
- Create: `grafana/legacy-dashboards/` (directory)
- Copy: 9 JSON files from `grafana/dashboards/`

- [ ] **Step 1: Create directory and copy files**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
mkdir -p grafana/legacy-dashboards
cp grafana/dashboards/*.json grafana/legacy-dashboards/
ls grafana/legacy-dashboards/ | wc -l
```

Expected: `9` (nine JSONs).

- [ ] **Step 2: Confirm exact byte-equivalence**

```fish
for f in grafana/dashboards/*.json; do
    name=$(basename "$f")
    if ! cmp -s "$f" "grafana/legacy-dashboards/$name"; then
        echo "DIFFERS: $name"
    fi
done
echo "comparison done"
```

Expected: only `comparison done` (no DIFFERS lines).

- [ ] **Step 3: Commit**

```fish
git add grafana/legacy-dashboards/
git commit -m "Backup 9 dashboards to legacy-dashboards/ before Grafana 12 migration

Identical copy of grafana/dashboards/*.json captured before any
modernization edits. This directory is NOT bind-mounted by the
test-env (excluded by being outside grafana/dashboards/), so
Grafana won't auto-import duplicates. Used for inspection and
partial rollback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Bump Grafana and Telegraf versions

**Files:**
- Modify: `test-env/.env.example`

- [ ] **Step 1: Update version pins**

Open `/home/lucgomes/Downloads/ucs_traffic_monitor/test-env/.env.example` and replace these two lines:

From:
```env
INFLUXDB_VERSION=1.11
TELEGRAF_VERSION=1.32-alpine
GRAFANA_VERSION=11.4.0
```

To:
```env
INFLUXDB_VERSION=1.11
TELEGRAF_VERSION=1.38-alpine
GRAFANA_VERSION=12.0.2
```

(InfluxDB stays on 1.11 — that's deliberate per the spec.)

- [ ] **Step 2: Sync local `.env` with the new defaults**

If `test-env/.env` exists, also update it (it's gitignored — local copy):

```fish
sed -i 's/^TELEGRAF_VERSION=.*/TELEGRAF_VERSION=1.38-alpine/' test-env/.env
sed -i 's/^GRAFANA_VERSION=.*/GRAFANA_VERSION=12.0.2/' test-env/.env
grep -E '^(GRAFANA_VERSION|TELEGRAF_VERSION|INFLUXDB_VERSION)=' test-env/.env
```

Expected output:
```
GRAFANA_VERSION=12.0.2
TELEGRAF_VERSION=1.38-alpine
INFLUXDB_VERSION=1.11
```

- [ ] **Step 3: Commit**

```fish
git add test-env/.env.example
git commit -m "Bump test-env versions: Grafana 12.0.2, Telegraf 1.38

Grafana 11.4.0 → 12.0.2 (latest stable), Telegraf 1.32 → 1.38.
InfluxDB stays on 1.11 — InfluxQL compat for existing dashboards.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Bring up new stack and verify boot

**Files:** none modified — verification only.

- [ ] **Step 1: Tear down current stack and rebuild**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor/test-env
sg docker -c "docker compose down -v"
sg docker -c "docker compose up -d --build"
```

The first run with new images will take ~3-5 min (pulling Grafana 12.0.2 + Telegraf 1.38).

- [ ] **Step 2: Wait until services are healthy and verify versions**

```fish
sleep 90
sg docker -c "docker compose ps"
```

Expected: 4 services running, `utm-influxdb (healthy)`.

```fish
curl -sf http://localhost:8086/ping -o /dev/null -w 'InfluxDB: %{http_code}\n'
curl -sf http://localhost:3000/api/health
echo
```

Expected:
- InfluxDB: `204`
- Grafana JSON includes `"version": "12.0.2"`

- [ ] **Step 3: Verify InfluxDB still receives data**

```fish
sg docker -c "docker compose logs syn-data --tail=5"
curl -s -G http://localhost:8086/query --data-urlencode 'q=SHOW MEASUREMENTS ON telegraf' \
    | python3 -c "import json, sys; d = json.load(sys.stdin); print(len(d['results'][0]['series'][0]['values']))"
```

Expected:
- syn-data logs show "tick N: wrote 280 lines" pattern
- Measurement count: `7`

- [ ] **Step 4: Verify Grafana provisioned datasource and dashboards**

```fish
curl -sf -u admin:admin http://localhost:3000/api/datasources \
    | python3 -c "import json, sys; d = json.load(sys.stdin); print(f'{len(d)} datasources, types: {[x[\"type\"] for x in d]}')"
curl -sf -u admin:admin "http://localhost:3000/api/search?type=dash-db" \
    | python3 -c "import json, sys; d = json.load(sys.stdin); print(f'{len(d)} dashboards')"
```

Expected:
- 1 datasource, type `influxdb`
- 9 dashboards

If you renamed the Grafana admin password earlier, use it instead of `admin:admin`.

No commit (verification only).

---

## Phase 2 — Document post-auto-migration status

### Task 5: Inspect each dashboard and capture status

**Files:**
- Create: `docs/superpowers/specs/grafana-12-migration-status.md`

This is a documentation task. Open each of the 9 dashboards in the browser (http://localhost:3000) and record what you see.

- [ ] **Step 1: Open each dashboard in browser, take screenshots if useful**

Login at http://localhost:3000. Navigate to Dashboards → UTM folder. Open each one in turn and note:
- How many panels render with data ✅
- How many show "Panel plugin not found" ❌
- How many show errors / "No data" / partial render ⚠️

- [ ] **Step 2: Create the status table**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/docs/superpowers/specs/grafana-12-migration-status.md`:

```markdown
# Grafana 12 Auto-Migration Status

Status do bump pra Grafana 12.0.2, antes da migração manual de painéis Canvas.
Captured 2026-04-26 com syn-data fornecendo dados sintéticos e time range
"Last 6 hours" + backfill de 6h.

## Resumo

| Dashboard | Total panels | ✅ OK | ❌ Plugin not found | ⚠️ Other issue |
|---|---|---|---|---|
| welcome | TBD | TBD | TBD | TBD |
| local_sys | TBD | TBD | TBD | TBD |
| locations | TBD | TBD | TBD | TBD |
| domain_overview | TBD | TBD | TBD | TBD |
| chassis_pause | TBD | TBD | TBD | TBD |
| domain_traffic | TBD | TBD | TBD | TBD |
| service_profile | TBD | TBD | TBD | TBD |
| chassis_traffic | TBD | TBD | TBD | TBD |
| ingress_congestion | TBD | TBD | TBD | TBD |

## Per-dashboard notes

(One paragraph per dashboard with specific observations.)

### welcome
TBD

### local_sys
TBD

### locations
TBD

### domain_overview
TBD

### chassis_pause
TBD

### domain_traffic
TBD

### service_profile
TBD

### chassis_traffic
TBD

### ingress_congestion
TBD
```

Replace each `TBD` with what you actually observe. Be honest — this is the baseline that future migration work measures against.

- [ ] **Step 3: Commit**

```fish
git add docs/superpowers/specs/grafana-12-migration-status.md
git commit -m "Document post-Grafana-12 auto-migration status of dashboards

Baseline observation of which panels render OK, which show
'Panel plugin not found', and which have other issues. Captured
before manual Canvas migration of the 6 priority panels.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Canvas migration (interactive Grafana UI work)

These three tasks involve clicking around the Grafana UI. Each follows the same pattern; instructions repeat to make tasks self-contained.

### Task 6: Migrate `domain_overview` (3 Angular panels → Canvas)

**Files:**
- Modify: `grafana/dashboards/domain_overview.json` (replace, ~8000 lines)

#### General workflow per Angular panel

For each `agenty-flowcharting-panel` in the dashboard:

1. **Find the panel in the Grafana UI** (Dashboards → UTM → Domain Overview → click on the broken panel area).
2. **Click the panel title → Inspect → Panel JSON** to read its JSON config. Note:
   - Position: `gridPos` (`x`, `y`, `w`, `h`)
   - Title
   - SVG source: search for `flowchart` or `definition` keys — the SVG is usually base64-encoded inline, or referenced via URL
   - Mappings: list of `mappingsObject` entries, each with `pattern` (element id in SVG) + `metricType` + `text`/`color` rules
3. **Decode the SVG** if base64. Save to `grafana/canvas-svgs/domain_overview_<panelname>.svg` for reference.
4. **Add a new Canvas panel** at the same `gridPos` (use Grafana UI: + Add panel → Visualization → Canvas).
5. **Configure background:** Canvas options → Background → upload the SVG, OR paste it inline as `data:image/svg+xml;base64,...`.
6. **Add Element per mapping:** for each mapping pattern, add a Canvas element (Rectangle) at the corresponding visual position on the SVG. Bind:
   - Data link: same query the original mapping used.
   - Background color: thresholds matching the original color rules.
7. **Delete the original Angular panel.**
8. **Save dashboard** (top right → Save → "Save current state").
9. **Export updated JSON** via Dashboard settings → JSON Model → copy → paste over `grafana/dashboards/domain_overview.json`.

#### `domain_overview` specifics

- [ ] **Step 1: Inspect original Angular panels in Grafana UI**

Open http://localhost:3000 → UTM → Domain Overview. Find the 3 panels showing "Panel plugin not found". For each, click the panel header → Inspect → Panel JSON. Copy the JSON of each panel into a temporary scratch file.

If "Panel plugin not found" doesn't expose a panel header to click, look at the dashboard JSON directly:

```fish
jq '.panels[] | select(.type == "agenty-flowcharting-panel") | {title, gridPos, id}' \
    grafana/dashboards/domain_overview.json
```

This lists the 3 panels' titles, positions, and ids.

- [ ] **Step 2: Extract SVGs**

For each panel, find the SVG source. In the original JSON, look for keys like `flowchartsData.flowcharts[].xml` or `definitions`. If base64-encoded, decode:

```fish
mkdir -p grafana/canvas-svgs
# For each panel, save the decoded SVG to a named file like:
#   grafana/canvas-svgs/domain_overview_topology.svg
# (manual step — depends on what each panel contains)
```

- [ ] **Step 3: Build Canvas panels in the UI**

For each of the 3 panels, follow the General workflow above (steps 4-7). Validate visually that the panel renders, that elements are positioned over the SVG correctly, and that colors react to syn-data's varying values.

If you can't reproduce a panel acceptably (e.g., the SVG is too complex with 30+ elements), STOP and report: we can either invest more time or fall back to text panel info for that specific one.

- [ ] **Step 4: Save and export the dashboard**

In Grafana UI, save the dashboard (top right → Save). Then go to Dashboard settings → JSON Model → copy entire JSON. Paste over `grafana/dashboards/domain_overview.json`, replacing all content.

- [ ] **Step 5: Verify the JSON contains Canvas panels**

```fish
jq '[.panels[] | select(.type == "canvas")] | length' grafana/dashboards/domain_overview.json
jq '[.panels[] | select(.type == "agenty-flowcharting-panel")] | length' grafana/dashboards/domain_overview.json
```

Expected:
- canvas count: `3`
- agenty-flowcharting-panel count: `0`

- [ ] **Step 6: Confirm provisioning reloads in Grafana**

Wait 30s for Grafana's provisioning loop. Refresh the browser. Confirm the dashboard now shows 3 Canvas panels (no "Panel plugin not found" for those panels).

- [ ] **Step 7: Commit**

```fish
git add grafana/dashboards/domain_overview.json grafana/canvas-svgs/
git commit -m "Migrate domain_overview: 3 Angular panels → Canvas

Replaces 3 agenty-flowcharting-panel instances with native Canvas
panels in domain_overview. SVG sources extracted into
grafana/canvas-svgs/. Each Canvas element bound to the same
InfluxQL query as the original mapping.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

If you can't complete one of the panels, commit what you have with `DONE_WITH_CONCERNS` in the implementer report and skip step 5's strict counts (they'll fail) — proceed to Task 7.

---

### Task 7: Migrate `locations` (1 Angular panel → Canvas)

**Files:**
- Modify: `grafana/dashboards/locations.json`

#### General workflow

Same as Task 6 but for the single Angular panel in `locations`. Locate it:

```fish
jq '.panels[] | select(.type == "agenty-flowcharting-panel") | {title, gridPos, id}' \
    grafana/dashboards/locations.json
```

- [ ] **Step 1: Locate and extract**

Use the JSON query above to find the one Angular panel. Extract its SVG to `grafana/canvas-svgs/locations_map.svg`.

- [ ] **Step 2: Build Canvas in UI**

Follow the General workflow (Task 6, steps 4-7) for the single panel.

- [ ] **Step 3: Verify**

```fish
jq '[.panels[] | select(.type == "canvas")] | length' grafana/dashboards/locations.json
jq '[.panels[] | select(.type == "agenty-flowcharting-panel")] | length' grafana/dashboards/locations.json
```

Expected: canvas `1`, agenty-flowcharting-panel `0`.

- [ ] **Step 4: Commit**

```fish
git add grafana/dashboards/locations.json grafana/canvas-svgs/
git commit -m "Migrate locations: 1 Angular panel → Canvas

Replaces the agenty-flowcharting-panel locations map with a native
Canvas panel.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Migrate `chassis_pause` (2 Angular panels → Canvas)

**Files:**
- Modify: `grafana/dashboards/chassis_pause.json`

Same workflow as Tasks 6-7.

- [ ] **Step 1: Locate**

```fish
jq '.panels[] | select(.type == "agenty-flowcharting-panel") | {title, gridPos, id}' \
    grafana/dashboards/chassis_pause.json
```

Expected: 2 panels.

- [ ] **Step 2: Extract SVGs**

Save to `grafana/canvas-svgs/chassis_pause_<panelname>.svg`.

- [ ] **Step 3: Build Canvas in UI**

Follow Task 6's General workflow for both panels.

- [ ] **Step 4: Verify**

```fish
jq '[.panels[] | select(.type == "canvas")] | length' grafana/dashboards/chassis_pause.json
jq '[.panels[] | select(.type == "agenty-flowcharting-panel")] | length' grafana/dashboards/chassis_pause.json
```

Expected: canvas `2`, agenty-flowcharting-panel `0`.

- [ ] **Step 5: Commit**

```fish
git add grafana/dashboards/chassis_pause.json grafana/canvas-svgs/
git commit -m "Migrate chassis_pause: 2 Angular panels → Canvas

Replaces both agenty-flowcharting-panel instances (chassis backplane
visualizations) with native Canvas panels.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — UX mitigation for unmigrated dashboards

### Task 9: Add info text panel to 4 dashboards with unmigrated Angular panels

**Files:**
- Modify: `grafana/dashboards/domain_traffic.json`
- Modify: `grafana/dashboards/service_profile.json`
- Modify: `grafana/dashboards/chassis_traffic.json`
- Modify: `grafana/dashboards/ingress_congestion.json`

The mechanical task: insert a text panel at position (0, 0) with markdown content explaining the migration status. Done via JSON edit (no Grafana UI needed, since text panels are simple).

- [ ] **Step 1: Define the text panel object**

The panel object to insert (replace `<DASHBOARD_NAME>` per dashboard):

```json
{
  "id": 999,
  "type": "text",
  "title": "Migration notice",
  "gridPos": { "h": 3, "w": 24, "x": 0, "y": 0 },
  "options": {
    "mode": "markdown",
    "content": "> ⚠️ **Migration in progress.** Os painéis de topologia visual deste dashboard ainda usam o plugin `agenty-flowcharting-panel` (Angular), que Grafana 11+ não carrega. Os painéis nativos abaixo (gráficos, séries temporais, tabelas) funcionam normalmente. Migração planejada — ver [`docs/superpowers/specs/2026-04-26-grafana-12-modernization-design.md`](.)."
  },
  "datasource": null
}
```

The `id: 999` is unique enough to identify and remove later if needed; Grafana will renumber internally on save.

- [ ] **Step 2: Bump existing panel y-coordinates by 3 to make room**

Each of the 4 dashboards has panels at `gridPos.y` starting from 0. We need them to start at 3 (to leave the top 3 grid units for the text panel). Use a small Python helper:

```fish
python3 <<'PY'
import json
from pathlib import Path

DASHBOARDS = [
    "domain_traffic", "service_profile", "chassis_traffic", "ingress_congestion",
]

INFO_PANEL = {
    "id": 999,
    "type": "text",
    "title": "Migration notice",
    "gridPos": {"h": 3, "w": 24, "x": 0, "y": 0},
    "options": {
        "mode": "markdown",
        "content": (
            "> ⚠️ **Migration in progress.** Os painéis de topologia visual "
            "deste dashboard ainda usam o plugin `agenty-flowcharting-panel` "
            "(Angular), que Grafana 11+ não carrega. Os painéis nativos abaixo "
            "(gráficos, séries temporais, tabelas) funcionam normalmente. "
            "Migração planejada — ver "
            "[`docs/superpowers/specs/2026-04-26-grafana-12-modernization-design.md`](.)."
        ),
    },
    "datasource": None,
}

repo = Path("/home/lucgomes/Downloads/ucs_traffic_monitor")

for name in DASHBOARDS:
    path = repo / "grafana" / "dashboards" / f"{name}.json"
    data = json.loads(path.read_text())
    panels = data.get("panels", [])

    # Skip if already inserted (idempotency).
    if any(p.get("id") == 999 and p.get("title") == "Migration notice" for p in panels):
        print(f"  {name}: notice already present, skipping")
        continue

    # Bump y by 3 for all existing panels.
    for p in panels:
        if "gridPos" in p:
            p["gridPos"]["y"] = p["gridPos"].get("y", 0) + 3

    # Insert the notice as the first panel.
    data["panels"] = [INFO_PANEL] + panels

    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  {name}: inserted notice + bumped {len(panels)} panels")

print("done")
PY
```

Expected: each dashboard prints "inserted notice + bumped N panels".

- [ ] **Step 3: Verify the change is consistent**

```fish
for name in domain_traffic service_profile chassis_traffic ingress_congestion; do
    count=$(jq '[.panels[] | select(.title == "Migration notice")] | length' "grafana/dashboards/${name}.json")
    echo "${name}: ${count} notice panel(s)"
done
```

Expected: each dashboard reports `1`.

- [ ] **Step 4: Confirm provisioning reloads (test-env still up)**

Wait 30s for Grafana's provisioning loop. Refresh browser. Confirm the 4 dashboards now show the migration notice at the top.

- [ ] **Step 5: Commit**

```fish
git add grafana/dashboards/domain_traffic.json grafana/dashboards/service_profile.json grafana/dashboards/chassis_traffic.json grafana/dashboards/ingress_congestion.json
git commit -m "Add migration notice text panel to 4 dashboards with unmigrated Angular panels

Inserts a top-of-dashboard markdown text panel explaining that the
flowcharting topology panels are not yet migrated. The native panels
below continue to function normally. Existing panels' y-coordinates
bumped by 3 to make room.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5 — Final validation + push

### Task 10: Run all 10 acceptance criteria

**Files:** none modified — verification only.

- [ ] **Step 1: Acceptance #1 — Grafana 12 + Telegraf 1.38 running**

```fish
sg docker -c "docker compose -f /home/lucgomes/Downloads/ucs_traffic_monitor/test-env/docker-compose.yml ps"
curl -sf http://localhost:3000/api/health | python3 -c "import json, sys; d = json.load(sys.stdin); print(f'Grafana version: {d[\"version\"]}')"
sg docker -c "docker inspect utm-telegraf --format '{{.Config.Image}}'"
```

Expected:
- 4 services running
- Grafana version: `12.0.2`
- telegraf image references `1.38-alpine` (custom build is `utm-telegraf:test`, but base FROM is `1.38-alpine`).

- [ ] **Step 2: Acceptance #2 — InfluxDB still responsive**

```fish
curl -s -G http://localhost:8086/query --data-urlencode 'q=SHOW MEASUREMENTS ON telegraf' \
    | python3 -c "import json, sys; d = json.load(sys.stdin); count = len(d['results'][0]['series'][0]['values']); print(f'measurements: {count}')"
```

Expected: `measurements: 7`.

- [ ] **Step 3: Acceptance #3 — welcome and local_sys render**

Open the two dashboards in the browser. Confirm visually:
- `welcome`: ≥ 90% of native panels render with data (header counts, alert list, links)
- `local_sys`: ≥ 90% of panels render

If you spot a panel in either with "No data" or "Panel plugin not found", document it in the migration-status notes (it'll be a known limitation).

- [ ] **Step 4: Acceptance #4-6 — Canvas migrations**

```fish
echo -n "domain_overview canvas: "; jq '[.panels[] | select(.type == "canvas")] | length' grafana/dashboards/domain_overview.json
echo -n "domain_overview angular: "; jq '[.panels[] | select(.type == "agenty-flowcharting-panel")] | length' grafana/dashboards/domain_overview.json
echo -n "locations canvas: "; jq '[.panels[] | select(.type == "canvas")] | length' grafana/dashboards/locations.json
echo -n "locations angular: "; jq '[.panels[] | select(.type == "agenty-flowcharting-panel")] | length' grafana/dashboards/locations.json
echo -n "chassis_pause canvas: "; jq '[.panels[] | select(.type == "canvas")] | length' grafana/dashboards/chassis_pause.json
echo -n "chassis_pause angular: "; jq '[.panels[] | select(.type == "agenty-flowcharting-panel")] | length' grafana/dashboards/chassis_pause.json
```

Expected:
- domain_overview: canvas `3`, angular `0`
- locations: canvas `1`, angular `0`
- chassis_pause: canvas `2`, angular `0`

If `DONE_WITH_CONCERNS` was reported on Task 6, 7, or 8, the counts may be partial (e.g., canvas `2`, angular `1` for domain_overview if one panel couldn't be reproduced). Document and accept as a known limitation.

- [ ] **Step 5: Acceptance #7 — text panels in 4 dashboards**

```fish
for name in domain_traffic service_profile chassis_traffic ingress_congestion; do
    count=$(jq '[.panels[] | select(.title == "Migration notice")] | length' "grafana/dashboards/${name}.json")
    echo "${name}: notice=${count}"
done
```

Expected: each `1`.

- [ ] **Step 6: Acceptance #8 — legacy backup intact**

```fish
ls -1 grafana/legacy-dashboards/*.json | wc -l
```

Expected: `9`.

- [ ] **Step 7: Acceptance #10 — credentials branch untouched**

```fish
git diff feat/credentials-env-vars feat/grafana-12-modernization --stat \
    | grep -v 'docs/superpowers/specs/2026-04-26-grafana-12-modernization-design.md' \
    | head
```

Expected: only show files modified by this sub-project (test-env/.env.example, grafana/dashboards/, grafana/legacy-dashboards/, grafana/canvas-svgs/, docs/superpowers/specs/grafana-12-migration-status.md). No unrelated changes.

No commit (verification only).

---

### Task 11: Push to fork

**Files:** none modified — git operation.

- [ ] **Step 1: Push the new branch**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
git push -u origin feat/grafana-12-modernization 2>&1 | tail -5
```

Expected: branch created on origin, tracking set up.

- [ ] **Step 2: Acceptance #9 — verify on GitHub**

Open https://github.com/logomes/ucs_traffic_monitor/tree/feat/grafana-12-modernization

Expected: branch visible, recent commits from this plan listed.

---

## Self-review notes

Spec coverage:
- ✅ Branch isolated `feat/grafana-12-modernization` (Task 1)
- ✅ `grafana/legacy-dashboards/` backup (Task 2)
- ✅ Versions bumped (Task 3)
- ✅ Stack rebuild + verification (Task 4)
- ✅ Per-dashboard auto-migration status documented (Task 5)
- ✅ 6 Canvas migrations across 3 dashboards (Tasks 6, 7, 8)
- ✅ Text panel info on 4 dashboards (Task 9)
- ✅ All 10 acceptance criteria validated (Task 10)
- ✅ Push to fork (Task 11)

Items deliberately not in plan (per spec Non-Goals):
- Migration of the 46 remaining Angular panels
- InfluxDB v2/v3 migration
- Production rollout (sub-project 2)
- Real UCS validation

Risk acknowledgment: Phase 3 (Canvas migration) requires manual Grafana UI work. If a particular panel turns out to be too complex to reproduce, the implementer is instructed to report `DONE_WITH_CONCERNS` and proceed; acceptance criteria account for partial completion.

## Next step (after this plan)

Sub-project 2 of stack modernization: **Production rollout**. Update `upgrade_utm.sh` defaults to Grafana 12.0.2 + Telegraf 1.38, document VM upgrade procedure, test on the production VM. Lower risk now that test-env has validated the stack.
