# UTM Production Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empacotar o trabalho dos sub-projetos anteriores (credentials refactor, dashboards Grafana 12, operator scripts) num tarball self-contained com `install.sh` idempotente que o operador roda na VM de produção.

**Architecture:** Diretório `deploy/` no repo contém `install.sh` (~250 linhas, idempotente, com `trap rollback ERR`) e `pack.sh` que gera o tarball a partir do branch atual. Tarball inclui todos os arquivos do branch grafana-12-modernization mais o install.sh. Operador faz `scp` + `sudo ./install.sh` na VM. Auto-rollback embutido + rollback script standalone gerado pra uso posterior.

**Tech Stack:** bash 4+, POSIX utils (install, sed, jq, sha256sum), systemd, Grafana provisioning, tar/gzip.

**Spec:** `docs/superpowers/specs/2026-04-26-prod-rollout-design.md`

**Repository:** `/home/lucgomes/Downloads/ucs_traffic_monitor`

---

## Phase 1 — Branch + skeleton

### Task 1: Create branch and deploy/ skeleton

**Files:**
- Create directory: `deploy/`

- [ ] **Step 1: Create branch from grafana-12-modernization**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
git checkout feat/grafana-12-modernization
git status
git checkout -b feat/prod-rollout-grafana-12
git branch --show-current
```

Expected: `feat/prod-rollout-grafana-12`.

- [ ] **Step 2: Create deploy directory**

```fish
mkdir -p deploy
```

No commit yet (wait for content in next task).

---

### Task 2: install.sh — header, helpers, argument parsing

**Files:**
- Create: `deploy/install.sh`

- [ ] **Step 1: Write install.sh skeleton with helpers**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/deploy/install.sh`:

```bash
#!/bin/bash
# UTM Production Rollout — installer
#
# Deploys the UTM credentials refactor + migrated Grafana 12 dashboards +
# operator scripts to a production VM. Idempotent and self-rolling-back.
#
# Usage:
#   sudo ./install.sh                                  # interactive
#   sudo SKIP_CONFIRMATIONS=1 ./install.sh             # non-interactive
#   sudo ./install.sh --dry-run                        # preview only
#   sudo ./install.sh --rollback /root/utm-pre-...     # explicit rollback
#
# Environment overrides:
#   UTM_DIR              (default: /usr/local/telegraf)
#   TELEGRAF_CONF_PATH   (default: /etc/telegraf/telegraf.conf)
#   CREDS_DIR            (default: /etc/utm)
#   INSTANCE_NAME        (default: utm)
#   SKIP_CONFIRMATIONS=1 (skip y/n prompts)
#   SKIP_GRAFANA_BACKUP=1 (skip API snapshot of dashboards)

set -euo pipefail

# ---------- Constants ----------

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FILES_DIR="${SCRIPT_DIR}/files"
readonly DATE_TAG="$(date +%Y-%m-%d_%H%M%S)"

# Configurable via env
: "${UTM_DIR:=/usr/local/telegraf}"
: "${TELEGRAF_CONF_PATH:=/etc/telegraf/telegraf.conf}"
: "${CREDS_DIR:=/etc/utm}"
: "${INSTANCE_NAME:=utm}"
: "${SKIP_CONFIRMATIONS:=0}"
: "${SKIP_GRAFANA_BACKUP:=0}"

readonly BACKUP_DIR="/root/utm-pre-upgrade-${DATE_TAG}"

# Mode flags
DRY_RUN=0
ROLLBACK_DIR=""

# ---------- Helpers ----------

log_info() { printf '\033[0;32m[INFO]\033[0m  %s\n' "$*" >&2; }
log_warn() { printf '\033[0;33m[WARN]\033[0m  %s\n' "$*" >&2; }
log_error() { printf '\033[0;31m[ERROR]\033[0m %s\n' "$*" >&2; }
log_step() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$*" >&2; }

confirm() {
    local prompt="${1:-Continue? (y/n): }"
    if [[ "$SKIP_CONFIRMATIONS" == "1" ]]; then
        log_info "Auto-confirming: $prompt"
        return 0
    fi
    local reply
    read -r -n 1 -p "$prompt" reply
    echo
    [[ "$reply" =~ ^[Yy]$ ]]
}

run() {
    # Wrapper that respects --dry-run.
    if [[ "$DRY_RUN" == "1" ]]; then
        log_info "DRY-RUN: $*"
        return 0
    fi
    "$@"
}

require() {
    # require <command> <hint-message>
    local cmd="$1"
    local hint="${2:-install it}"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log_error "Required command not found: $cmd ($hint)"
        exit 1
    fi
}

# ---------- Argument parsing ----------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=1
            log_warn "DRY-RUN mode: no changes will be made"
            shift
            ;;
        --rollback)
            ROLLBACK_DIR="$2"
            shift 2
            ;;
        -h|--help)
            sed -n '3,/^set -euo/p' "$0" | sed 's/^# \?//' | head -n -1
            exit 0
            ;;
        *)
            log_error "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# ---------- (rest of script in subsequent tasks) ----------

log_error "TODO: phases not yet implemented"
exit 1
```

- [ ] **Step 2: Make executable and check syntax**

```fish
chmod +x deploy/install.sh
bash -n deploy/install.sh && echo "syntax OK"
```

Expected: "syntax OK".

- [ ] **Step 3: Run with --help to verify argument parsing**

```fish
deploy/install.sh --help
```

Expected: prints the usage block (lines 3-19 from the script header).

- [ ] **Step 4: Commit**

```fish
git add deploy/install.sh
git commit -m "Add install.sh skeleton with helpers and argument parsing

Defines constants (paths, date tag, env-overridable config), color-coded
log helpers, run() wrapper for --dry-run, require() for dep checking,
and argument parser supporting --dry-run / --rollback / --help.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — install.sh phases

### Task 3: Pre-flight + backup phases

**Files:**
- Modify: `deploy/install.sh` (replace the trailing `TODO` line with real phase functions)

- [ ] **Step 1: Replace the TODO with preflight() and backup() functions**

In `deploy/install.sh`, **REPLACE** the lines:

```bash
# ---------- (rest of script in subsequent tasks) ----------

log_error "TODO: phases not yet implemented"
exit 1
```

with:

```bash
# ---------- Phase functions ----------

preflight() {
    log_step "Phase 1/11 — Pre-flight checks"

    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (sudo)"
        exit 1
    fi

    require python3 "install via package manager (e.g., zypper in python3)"
    require jq       "zypper in jq"
    require sed      "(should be present)"
    require sha256sum "(coreutils, should be present)"
    require curl     "zypper in curl"
    require systemctl "(systemd should be present)"

    if ! id telegraf >/dev/null 2>&1; then
        log_error "User 'telegraf' does not exist. Is telegraf installed?"
        exit 1
    fi

    if [[ ! -d "$UTM_DIR" ]]; then
        log_error "UTM_DIR not found: $UTM_DIR"
        log_error "Override via UTM_DIR=... if installed elsewhere."
        exit 1
    fi

    if [[ ! -f "$TELEGRAF_CONF_PATH" ]]; then
        log_error "telegraf.conf not found at $TELEGRAF_CONF_PATH"
        log_error "Override via TELEGRAF_CONF_PATH=... if elsewhere."
        exit 1
    fi

    if ! systemctl cat telegraf >/dev/null 2>&1; then
        log_error "telegraf.service not found in systemd. Is telegraf installed?"
        exit 1
    fi

    if ! systemctl cat grafana-server >/dev/null 2>&1; then
        log_error "grafana-server.service not found in systemd. Is Grafana installed?"
        exit 1
    fi

    if [[ ! -d "$FILES_DIR" ]]; then
        log_error "Tarball files dir not found: $FILES_DIR"
        log_error "Did you extract the tarball completely?"
        exit 1
    fi

    log_info "All pre-flight checks passed"
    log_info "  UTM_DIR=$UTM_DIR"
    log_info "  TELEGRAF_CONF_PATH=$TELEGRAF_CONF_PATH"
    log_info "  CREDS_DIR=$CREDS_DIR"
    log_info "  INSTANCE_NAME=$INSTANCE_NAME"
    log_info "  Backup will be at: $BACKUP_DIR"
}

backup() {
    log_step "Phase 2/11 — Backup current state"

    run mkdir -p "$BACKUP_DIR"

    # Copy files that we'll modify
    if [[ -f "${UTM_DIR}/ucs_traffic_monitor.py" ]]; then
        run cp -p "${UTM_DIR}/ucs_traffic_monitor.py" "$BACKUP_DIR/"
        log_info "Backed up ${UTM_DIR}/ucs_traffic_monitor.py"
    fi

    if [[ -f "$TELEGRAF_CONF_PATH" ]]; then
        run cp -p "$TELEGRAF_CONF_PATH" "$BACKUP_DIR/telegraf.conf"
        log_info "Backed up $TELEGRAF_CONF_PATH"
    fi

    # Copy all ucs_domains_group_*.txt (legacy creds)
    local found=0
    for f in "${UTM_DIR}"/ucs_domains_group_*.txt; do
        if [[ -f "$f" ]]; then
            run cp -p "$f" "$BACKUP_DIR/"
            log_info "Backed up $(basename "$f")"
            found=$((found + 1))
        fi
    done
    if [[ "$found" -eq 0 ]]; then
        log_warn "No ucs_domains_group_*.txt files found — assuming creds already in env vars"
    fi

    # Snapshot dashboards via Grafana API (optional)
    if [[ "$SKIP_GRAFANA_BACKUP" != "1" ]]; then
        run mkdir -p "$BACKUP_DIR/dashboards-snapshot"
        log_info "Snapshotting dashboards via Grafana API..."
        log_info "Enter Grafana admin credentials when prompted."

        local user pass
        if [[ "$DRY_RUN" != "1" ]]; then
            read -r -p "Grafana admin user: " user
            read -r -s -p "Grafana admin password: " pass
            echo

            local uids
            uids="$(curl -sf -u "${user}:${pass}" \
                "http://localhost:3000/api/search?type=dash-db" \
                | jq -r '.[].uid' || true)"

            if [[ -z "$uids" ]]; then
                log_warn "No dashboards found via API (or auth failed); skipping snapshot"
            else
                local count=0
                while IFS= read -r uid; do
                    [[ -z "$uid" ]] && continue
                    curl -sf -u "${user}:${pass}" \
                        "http://localhost:3000/api/dashboards/uid/${uid}" \
                        > "$BACKUP_DIR/dashboards-snapshot/${uid}.json" || true
                    count=$((count + 1))
                done <<< "$uids"
                log_info "Snapshotted $count dashboard(s) to $BACKUP_DIR/dashboards-snapshot/"
            fi
        fi
    fi

    # Generate rollback.sh standalone
    write_rollback_script "$BACKUP_DIR"

    log_info "Backup complete: $BACKUP_DIR"
    if ! confirm "Backup created. Continue with deployment? (y/n): "; then
        log_warn "Aborted by user"
        exit 0
    fi
}

write_rollback_script() {
    local dir="$1"
    if [[ "$DRY_RUN" == "1" ]]; then
        log_info "DRY-RUN: would write $dir/rollback.sh"
        return
    fi
    cat > "${dir}/rollback.sh" <<ROLLBACK
#!/bin/bash
# UTM rollback script — generated by install.sh on ${DATE_TAG}
# Run as root: sudo bash $dir/rollback.sh
set -euo pipefail

if [[ \$EUID -ne 0 ]]; then
    echo "Run as root" >&2
    exit 1
fi

echo "Rolling back UTM to pre-${DATE_TAG} state..."
systemctl stop telegraf grafana-server || true

# Restore files
[[ -f "$dir/ucs_traffic_monitor.py" ]] && cp -p "$dir/ucs_traffic_monitor.py" "${UTM_DIR}/"
[[ -f "$dir/telegraf.conf" ]] && cp -p "$dir/telegraf.conf" "$TELEGRAF_CONF_PATH"
for f in "$dir"/ucs_domains_group_*.txt; do
    [[ -f "\$f" ]] && cp -p "\$f" "${UTM_DIR}/"
done

# Remove drop-in
rm -f /etc/systemd/system/telegraf.service.d/utm-creds.conf
rmdir /etc/systemd/system/telegraf.service.d/ 2>/dev/null || true

# Remove provisioning yaml + dashboards (legacy API-imported dashboards survive in DB)
rm -f /etc/grafana/provisioning/dashboards/utm.yml
rm -f /var/lib/grafana/dashboards/*.json
rmdir /var/lib/grafana/dashboards 2>/dev/null || true

systemctl daemon-reload
systemctl start telegraf grafana-server
echo "Rollback complete. /etc/utm/creds.env left in place — remove manually if desired."
ROLLBACK
    chmod +x "${dir}/rollback.sh"
    log_info "Wrote $dir/rollback.sh"
}

# ---------- (more phases in next task) ----------

# Handle --rollback shortcut
if [[ -n "$ROLLBACK_DIR" ]]; then
    if [[ ! -d "$ROLLBACK_DIR" ]]; then
        log_error "Rollback dir not found: $ROLLBACK_DIR"
        exit 1
    fi
    if [[ -f "${ROLLBACK_DIR}/rollback.sh" ]]; then
        exec bash "${ROLLBACK_DIR}/rollback.sh"
    else
        log_error "No rollback.sh in $ROLLBACK_DIR"
        exit 1
    fi
fi

preflight
backup
log_info "Phases 1-2 complete. (More phases coming in next task — install will fail here.)"
exit 0
```

- [ ] **Step 2: Syntax check**

```fish
bash -n deploy/install.sh && echo "syntax OK"
```

- [ ] **Step 3: Test with --dry-run** (no real backup created)

Since we don't have all dependencies for a real install, a basic dry-run test must run as a regular user — and will fail at the "must run as root" check. That's the expected behavior:

```fish
deploy/install.sh --dry-run 2>&1 | head -10
```

Expected: hits the EUID check and exits with `[ERROR] This script must be run as root (sudo)`.

- [ ] **Step 4: Commit**

```fish
git add deploy/install.sh
git commit -m "install.sh: implement preflight() and backup() phases

Pre-flight validates root + deps + paths + services + tarball
contents. Backup creates /root/utm-pre-upgrade-DATE/, copies the
files we'll modify, optionally snapshots dashboards via Grafana
API (interactive prompt for credentials), and generates a
standalone rollback.sh.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Deploy + migrate + telegraf.conf phases

**Files:**
- Modify: `deploy/install.sh` (add phase functions, update main flow)

- [ ] **Step 1: Replace the trailing block with deploy/migrate/telegraf phases**

In `deploy/install.sh`, find the line `log_info "Phases 1-2 complete..."` and the `exit 0` after it. **REPLACE** that block with the following (inserting the new phase functions BEFORE the main call sequence):

Find this block:
```bash
preflight
backup
log_info "Phases 1-2 complete. (More phases coming in next task — install will fail here.)"
exit 0
```

Replace it with:

```bash
stop_telegraf() {
    log_step "Phase 3/11 — Stop telegraf"
    run systemctl stop telegraf
    # Wait up to 30s for it to actually stop
    for _ in $(seq 1 30); do
        if ! systemctl is-active --quiet telegraf; then
            log_info "telegraf stopped"
            return 0
        fi
        sleep 1
    done
    log_error "telegraf did not stop within 30s"
    return 1
}

deploy_scripts() {
    log_step "Phase 4/11 — Deploy script files"

    run install -m 644 "${FILES_DIR}/credentials.py" "${UTM_DIR}/credentials.py"
    log_info "Installed credentials.py"

    run install -m 755 "${FILES_DIR}/ucs_traffic_monitor.py" "${UTM_DIR}/ucs_traffic_monitor.py"
    log_info "Installed ucs_traffic_monitor.py"

    run install -d -m 755 "${UTM_DIR}/lib"
    run install -m 644 "${FILES_DIR}/lib/utm-common.sh" "${UTM_DIR}/lib/utm-common.sh"
    log_info "Installed lib/utm-common.sh"

    run install -d -m 755 "${UTM_DIR}/scripts"
    run install -m 755 "${FILES_DIR}/scripts/migrate_credentials.py" "${UTM_DIR}/scripts/migrate_credentials.py"
    log_info "Installed scripts/migrate_credentials.py"

    run install -m 755 "${FILES_DIR}/upgrade_utm.sh" "${UTM_DIR}/upgrade_utm.sh"
    run install -m 755 "${FILES_DIR}/backup_utm_dashboards.sh" "${UTM_DIR}/backup_utm_dashboards.sh"
    log_info "Installed operator scripts"

    # Compat symlink
    if [[ "$DRY_RUN" != "1" ]]; then
        ln -sfn backup_utm_dashboards.sh "${UTM_DIR}/backup_utm_bashboards.sh"
    fi
    log_info "Created compat symlink backup_utm_bashboards.sh"
}

migrate_credentials() {
    log_step "Phase 5/11 — Migrate credentials"

    run install -d -m 0700 -o telegraf -g telegraf "$CREDS_DIR"

    if [[ -f "${CREDS_DIR}/creds.env" ]]; then
        log_warn "${CREDS_DIR}/creds.env already exists — skipping migration (idempotent)"
        return 0
    fi

    local found=0
    local first_target="${CREDS_DIR}/creds.env"
    local n=0
    for f in "${UTM_DIR}"/ucs_domains_group_*.txt; do
        [[ ! -f "$f" ]] && continue
        n=$((n + 1))
        local target
        if [[ "$n" -eq 1 ]]; then
            target="$first_target"
        else
            target="${CREDS_DIR}/creds_${n}.env"
        fi

        if [[ "$DRY_RUN" == "1" ]]; then
            log_info "DRY-RUN: would migrate $f → $target"
            continue
        fi

        python3 "${UTM_DIR}/scripts/migrate_credentials.py" \
            --input "$f" --output "$target"
        chown telegraf:telegraf "$target"
        chmod 600 "$target"
        log_info "Migrated $(basename "$f") → $target"
        found=$((found + 1))
    done

    if [[ "$found" -eq 0 && "$DRY_RUN" != "1" ]]; then
        log_warn "No legacy ucs_domains_group_*.txt files found"
        log_warn "Create ${CREDS_DIR}/creds.env manually before starting telegraf, e.g.:"
        log_warn "  echo 'UTM_DOMAINS=dom1' > ${CREDS_DIR}/creds.env"
        log_warn "  echo 'UTM_dom1_HOST=10.0.0.X' >> ${CREDS_DIR}/creds.env"
        log_warn "  echo 'UTM_dom1_USER=monitoring' >> ${CREDS_DIR}/creds.env"
        log_warn "  echo 'UTM_dom1_PASS=...' >> ${CREDS_DIR}/creds.env"
        log_warn "  chmod 600 ${CREDS_DIR}/creds.env"
        log_warn "  chown telegraf:telegraf ${CREDS_DIR}/creds.env"
    fi

    if [[ "$n" -gt 1 ]]; then
        log_warn "$n legacy files found; only first one ($first_target) is wired into the systemd drop-in."
        log_warn "For multi-instance, edit /etc/systemd/system/telegraf.service.d/utm-creds.conf"
        log_warn "or create separate telegraf instances. See README for details."
    fi
}

update_telegraf_conf() {
    log_step "Phase 6/11 — Update telegraf.conf"

    if grep -q -- "--instance-name" "$TELEGRAF_CONF_PATH"; then
        log_warn "telegraf.conf already contains --instance-name — skipping (idempotent)"
        return 0
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
        log_info "DRY-RUN: would edit $TELEGRAF_CONF_PATH to use --instance-name $INSTANCE_NAME"
        return 0
    fi

    cp -p "$TELEGRAF_CONF_PATH" "${TELEGRAF_CONF_PATH}.bak.${DATE_TAG}"
    log_info "Saved backup at ${TELEGRAF_CONF_PATH}.bak.${DATE_TAG}"

    # Match: python3 .../ucs_traffic_monitor.py .../ucs_domains_group_N.txt influxdb-lp -vv
    # Replace with: python3 .../ucs_traffic_monitor.py influxdb-lp --instance-name <name> -vv
    # We use sed with extended regex.
    sed -i -E "s|(python3[[:space:]]+[^[:space:]]*ucs_traffic_monitor\\.py)[[:space:]]+[^[:space:]]+\\.txt[[:space:]]+(influxdb-lp)|\\1 \\2 --instance-name ${INSTANCE_NAME}|g" \
        "$TELEGRAF_CONF_PATH"

    if grep -q -- "--instance-name" "$TELEGRAF_CONF_PATH"; then
        log_info "telegraf.conf updated to invoke ucs_traffic_monitor.py with --instance-name ${INSTANCE_NAME}"
    else
        log_error "Failed to update telegraf.conf — invocation pattern not matched."
        log_error "Inspect manually: grep ucs_traffic_monitor $TELEGRAF_CONF_PATH"
        return 1
    fi
}

# ---------- (final phases in next task) ----------

if [[ -n "$ROLLBACK_DIR" ]]; then
    if [[ ! -d "$ROLLBACK_DIR" ]]; then
        log_error "Rollback dir not found: $ROLLBACK_DIR"
        exit 1
    fi
    exec bash "${ROLLBACK_DIR}/rollback.sh"
fi

preflight
backup
stop_telegraf
deploy_scripts
migrate_credentials
update_telegraf_conf
log_info "Phases 1-6 complete. (More phases coming in next task — install will incomplete here.)"
exit 0
```

Note: the `exec bash "${ROLLBACK_DIR}/rollback.sh"` block is the same as before — I just removed the `if [[ -f ... ]]` wrapper since rollback.sh is always present in dirs created by our backup.

- [ ] **Step 2: Syntax check**

```fish
bash -n deploy/install.sh && echo "syntax OK"
```

- [ ] **Step 3: shellcheck**

```fish
shellcheck deploy/install.sh 2>&1 | head -30
```

Expected: 0 issues. If issues:
- `SC2086` (quote variables) → fix with quotes
- `SC2155` (declare and assign separately) → split lines
- For false positives, `# shellcheck disable=SCxxxx` with comment

- [ ] **Step 4: Commit**

```fish
git add deploy/install.sh
git commit -m "install.sh: implement deploy/migrate/telegraf phases

stop_telegraf waits up to 30s for systemctl stop to take effect.
deploy_scripts uses install(1) with proper modes for credentials.py
(644), the main script (755), the lib (644), the migrate helper
(755), and the operator scripts (755). migrate_credentials handles
multi-instance (.txt → multiple creds.env files) but warns that
only creds.env is wired into the systemd drop-in. update_telegraf_conf
uses sed -E to swap the legacy invocation for the new
--instance-name form, with a .bak file lateral.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: systemd + provisioning + restart + validate phases

**Files:**
- Modify: `deploy/install.sh` (add final phase functions + main rollback handling)

- [ ] **Step 1: Replace trailing block with final phases**

Find the block:
```bash
preflight
backup
stop_telegraf
deploy_scripts
migrate_credentials
update_telegraf_conf
log_info "Phases 1-6 complete. (More phases coming in next task — install will incomplete here.)"
exit 0
```

Replace it with:

```bash
setup_systemd_dropin() {
    log_step "Phase 7/11 — Setup systemd EnvironmentFile drop-in"

    local dropin_dir="/etc/systemd/system/telegraf.service.d"
    local dropin_file="${dropin_dir}/utm-creds.conf"

    run mkdir -p "$dropin_dir"

    if [[ "$DRY_RUN" == "1" ]]; then
        log_info "DRY-RUN: would write $dropin_file"
        return 0
    fi

    cat > "$dropin_file" <<EOF
# Loaded by telegraf.service to inject UTM credentials into the
# environment seen by /usr/local/telegraf/ucs_traffic_monitor.py.
# Generated by install.sh on ${DATE_TAG}
[Service]
EnvironmentFile=${CREDS_DIR}/creds.env
EOF

    chmod 644 "$dropin_file"
    log_info "Wrote $dropin_file"

    systemctl daemon-reload
    log_info "systemd reloaded"
}

setup_provisioning() {
    log_step "Phase 8/11 — Setup Grafana provisioning"

    local prov_dir="/etc/grafana/provisioning/dashboards"
    local dash_dir="/var/lib/grafana/dashboards"

    run install -d -m 755 "$prov_dir"
    run install -m 644 "${FILES_DIR}/grafana/provisioning/utm.yml" "${prov_dir}/utm.yml"
    log_info "Installed $prov_dir/utm.yml"

    if [[ "$DRY_RUN" != "1" ]]; then
        install -d -m 755 -o grafana -g grafana "$dash_dir"
    fi

    local count=0
    for f in "${FILES_DIR}/grafana/dashboards"/*.json; do
        [[ ! -f "$f" ]] && continue
        if [[ "$DRY_RUN" == "1" ]]; then
            log_info "DRY-RUN: would install $(basename "$f") → $dash_dir/"
        else
            install -m 644 -o grafana -g grafana "$f" "${dash_dir}/$(basename "$f")"
        fi
        count=$((count + 1))
    done
    log_info "Installed $count dashboard(s) to $dash_dir/"
}

restart_services() {
    log_step "Phase 9/11 — Restart services"
    run systemctl daemon-reload
    run systemctl restart telegraf
    run systemctl restart grafana-server
    log_info "Waiting 60s for first telegraf collection cycle..."
    [[ "$DRY_RUN" != "1" ]] && sleep 60
}

validate() {
    log_step "Phase 10/11 — Validate"
    local failures=0

    # 1. InfluxDB ping
    if curl -sf http://localhost:8086/ping -o /dev/null -w '%{http_code}' 2>/dev/null | grep -q 204; then
        log_info "✓ InfluxDB /ping returns 204"
    else
        log_warn "✗ InfluxDB /ping did not return 204"
        failures=$((failures + 1))
    fi

    # 2. Grafana health
    if curl -sf http://localhost:3000/api/health -o /dev/null -w '%{http_code}' 2>/dev/null | grep -q 200; then
        log_info "✓ Grafana /api/health returns 200"
    else
        log_warn "✗ Grafana /api/health did not return 200"
        failures=$((failures + 1))
    fi

    # 3. Telegraf running
    if systemctl is-active --quiet telegraf; then
        log_info "✓ telegraf service active"
    else
        log_warn "✗ telegraf service not active"
        failures=$((failures + 1))
    fi

    # 4. Script log shows 'Added domain dict'
    local logfile="/var/log/telegraf/ucs_traffic_monitor/ucs_traffic_monitor_${INSTANCE_NAME}.log"
    if [[ -f "$logfile" ]] && grep -q "Added.*to domain dict" "$logfile" 2>/dev/null; then
        log_info "✓ Script log shows credentials loaded ('Added * to domain dict')"
    else
        log_warn "✗ Script log not found or missing 'Added * to domain dict' marker: $logfile"
        failures=$((failures + 1))
    fi

    # 5. InfluxDB has recent data
    local count
    count="$(curl -s -G http://localhost:8086/query \
        --data-urlencode 'q=SELECT count(*) FROM FIEnvStats WHERE time > now() - 5m' \
        --data-urlencode 'db=telegraf' 2>/dev/null \
        | jq -r '.results[0].series[0].values[0][1] // 0' 2>/dev/null || echo 0)"
    if [[ "${count:-0}" -gt 0 ]]; then
        log_info "✓ InfluxDB has $count FIEnvStats record(s) in last 5m"
    else
        log_warn "✗ InfluxDB has no FIEnvStats data in last 5m (UCS connectivity?)"
        failures=$((failures + 1))
    fi

    # 6. Dashboards present
    local n_json
    n_json="$(ls /var/lib/grafana/dashboards/*.json 2>/dev/null | wc -l)"
    if [[ "${n_json:-0}" -ge 1 ]]; then
        log_info "✓ $n_json dashboard JSON(s) in /var/lib/grafana/dashboards/"
    else
        log_warn "✗ No dashboards in /var/lib/grafana/dashboards/"
        failures=$((failures + 1))
    fi

    if [[ "$failures" -gt 0 ]]; then
        log_warn "$failures of 6 validation checks failed."
        log_warn "Investigation suggestions:"
        log_warn "  journalctl -u telegraf --since '5 min ago'"
        log_warn "  cat $logfile"
        log_warn "  systemctl status telegraf grafana-server"
    fi
    return 0  # Validation failures are advisory; don't auto-rollback
}

summary() {
    log_step "Phase 11/11 — Summary"
    cat <<EOF

UTM production deployment complete.

  Backup:           $BACKUP_DIR
  Rollback script:  $BACKUP_DIR/rollback.sh
  Credentials file: ${CREDS_DIR}/creds.env  (chmod 600, owner telegraf)
  Provisioning:     /etc/grafana/provisioning/dashboards/utm.yml
  Dashboards:       /var/lib/grafana/dashboards/
  systemd drop-in:  /etc/systemd/system/telegraf.service.d/utm-creds.conf

To roll back:
  sudo bash $BACKUP_DIR/rollback.sh

Next steps:
  1. Open Grafana in browser, navigate to UTM folder, verify all 9 dashboards.
  2. Watch telegraf logs for ~10 min: journalctl -u telegraf -f
  3. After 24-48h of stable operation, securely delete the legacy txt files:
     for f in $UTM_DIR/ucs_domains_group_*.txt; do shred -u "\$f"; done

EOF
}

# ---------- Rollback handler ----------

rollback_on_error() {
    log_error "Caught error — running rollback"
    if [[ -d "$BACKUP_DIR" && -x "${BACKUP_DIR}/rollback.sh" ]]; then
        bash "${BACKUP_DIR}/rollback.sh" || log_error "Rollback script failed!"
    else
        log_error "No rollback script available at ${BACKUP_DIR}/rollback.sh"
        log_error "Manual rollback required."
    fi
    exit 1
}

# ---------- Main ----------

if [[ -n "$ROLLBACK_DIR" ]]; then
    if [[ ! -d "$ROLLBACK_DIR" ]]; then
        log_error "Rollback dir not found: $ROLLBACK_DIR"
        exit 1
    fi
    exec bash "${ROLLBACK_DIR}/rollback.sh"
fi

# Trap activated AFTER preflight (so backup must succeed before we trap to rollback).
preflight
backup
trap rollback_on_error ERR
stop_telegraf
deploy_scripts
migrate_credentials
update_telegraf_conf
setup_systemd_dropin
setup_provisioning
restart_services
trap - ERR  # disable the trap before validate (validation failures are advisory)
validate
summary
exit 0
```

- [ ] **Step 2: Syntax check + shellcheck**

```fish
bash -n deploy/install.sh && echo "syntax OK"
shellcheck deploy/install.sh 2>&1 | head -30
```

Expected: zero shellcheck issues. Fix any inline.

- [ ] **Step 3: Verify --help still works**

```fish
deploy/install.sh --help 2>&1 | head -10
```

Expected: usage block still printed (Phase 1-2 not run because --help short-circuits before EUID check).

- [ ] **Step 4: Verify line count**

```fish
wc -l deploy/install.sh
```

Expected: ~280-300 lines.

- [ ] **Step 5: Commit**

```fish
git add deploy/install.sh
git commit -m "install.sh: complete with systemd/provisioning/restart/validate

setup_systemd_dropin writes utm-creds.conf with EnvironmentFile.
setup_provisioning copies utm.yml + 9 JSONs into the right places
with grafana ownership. restart_services daemon-reloads then
restarts telegraf and grafana-server. validate runs 6 advisory
checks (InfluxDB ping, Grafana health, telegraf active, script log
marker, recent FIEnvStats records, dashboard JSON count). summary
prints final state plus rollback command and next-step guidance.
trap rollback_on_error activates after backup so any phase failure
auto-rolls-back; trap disabled before validate (failures are
advisory, not regressions of the install itself).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Tarball builder + README

### Task 6: pack.sh — tarball builder

**Files:**
- Create: `deploy/pack.sh`

- [ ] **Step 1: Write pack.sh**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/deploy/pack.sh`:

```bash
#!/bin/bash
# pack.sh — build the UTM production deployment tarball.
#
# Usage:
#   ./deploy/pack.sh                  # builds utm-prod-deploy-<sha>.tar.gz
#   ./deploy/pack.sh /tmp             # writes to /tmp/utm-prod-deploy-<sha>.tar.gz
#
# Run from repo root.

set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly OUT_DIR="${1:-${REPO_ROOT}}"
readonly SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
readonly TARBALL="${OUT_DIR}/utm-prod-deploy-${SHA}.tar.gz"
readonly STAGING="$(mktemp -d)"

trap 'rm -rf "$STAGING"' EXIT

echo "Building $TARBALL ..."

# Top-level: install.sh and README.md
cp "${REPO_ROOT}/deploy/install.sh" "${STAGING}/install.sh"
cp "${REPO_ROOT}/deploy/README.md"  "${STAGING}/README.md"
chmod 755 "${STAGING}/install.sh"

# files/ — everything install.sh deploys
mkdir -p "${STAGING}/files"

cp "${REPO_ROOT}/telegraf/credentials.py"                "${STAGING}/files/credentials.py"
cp "${REPO_ROOT}/telegraf/ucs_traffic_monitor.py"         "${STAGING}/files/ucs_traffic_monitor.py"

mkdir -p "${STAGING}/files/lib"
cp "${REPO_ROOT}/lib/utm-common.sh"                       "${STAGING}/files/lib/utm-common.sh"

mkdir -p "${STAGING}/files/scripts"
cp "${REPO_ROOT}/scripts/migrate_credentials.py"          "${STAGING}/files/scripts/migrate_credentials.py"

cp "${REPO_ROOT}/upgrade_utm.sh"                          "${STAGING}/files/upgrade_utm.sh"
cp "${REPO_ROOT}/backup_utm_dashboards.sh"                "${STAGING}/files/backup_utm_dashboards.sh"

# Grafana provisioning — point uses files/grafana/dashboards
mkdir -p "${STAGING}/files/grafana/dashboards"
cp "${REPO_ROOT}/grafana/dashboards"/*.json               "${STAGING}/files/grafana/dashboards/"

# Provisioning yaml — needs to point to /var/lib/grafana/dashboards on the VM,
# which is where install.sh deploys the JSONs.
mkdir -p "${STAGING}/files/grafana/provisioning"
cat > "${STAGING}/files/grafana/provisioning/utm.yml" <<'EOF'
apiVersion: 1

providers:
  - name: UTM-Dashboards
    orgId: 1
    folder: UTM
    type: file
    disableDeletion: false
    editable: true
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
EOF

# systemd drop-in template (install.sh writes the actual file with
# CREDS_DIR variable expanded; this is reference)
mkdir -p "${STAGING}/files/systemd"
cat > "${STAGING}/files/systemd/telegraf-utm-creds.conf" <<'EOF'
[Service]
EnvironmentFile=/etc/utm/creds.env
EOF

# Stamp build info
cat > "${STAGING}/BUILD_INFO" <<EOF
sha=${SHA}
built=$(date -u +%Y-%m-%dT%H:%M:%SZ)
branch=$(git -C "$REPO_ROOT" branch --show-current)
host=$(hostname)
EOF

# Pack
tar czf "$TARBALL" -C "$STAGING" .
echo "Done: $TARBALL"
echo "Size: $(du -h "$TARBALL" | cut -f1)"
echo
echo "Tarball contents:"
tar tzf "$TARBALL" | head -25
echo "  (total: $(tar tzf "$TARBALL" | wc -l) entries)"
```

- [ ] **Step 2: Make executable + syntax check**

```fish
chmod +x deploy/pack.sh
bash -n deploy/pack.sh && echo "syntax OK"
shellcheck deploy/pack.sh 2>&1 | head -10
```

Expected: zero shellcheck issues.

- [ ] **Step 3: Commit**

```fish
git add deploy/pack.sh
git commit -m "Add deploy/pack.sh — build tarball from current branch

Stages all files install.sh expects (credentials.py, script,
lib/utm-common.sh, migrate script, operator scripts, 9 dashboards,
provisioning yaml, systemd drop-in template) plus install.sh and
README.md and a BUILD_INFO stamp. Output: utm-prod-deploy-<sha>.tar.gz
in repo root (or path given as \$1).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: README.md for the tarball

**Files:**
- Create: `deploy/README.md`

- [ ] **Step 1: Write README.md**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/deploy/README.md`:

```markdown
# UTM Production Deployment Tarball

Self-contained tarball that deploys the modernized UTM codebase to
a production VM running Grafana 12, Telegraf 1.38, InfluxDB 1.10 (or
1.11). Idempotent — safe to re-run.

## Quickstart

On your workstation:

```sh
./deploy/pack.sh
scp utm-prod-deploy-<sha>.tar.gz user@vm:/tmp/
```

On the VM:

```sh
cd /tmp
tar xzf utm-prod-deploy-<sha>.tar.gz -C /tmp/utm-deploy
cd /tmp/utm-deploy
sudo ./install.sh
```

The script is interactive — it asks for confirmation after the backup
phase and for Grafana admin credentials during the dashboard snapshot.

For non-interactive runs (CI, scripted deploys):

```sh
sudo SKIP_CONFIRMATIONS=1 SKIP_GRAFANA_BACKUP=1 ./install.sh
```

## What it does

| Phase | Action |
|---|---|
| 1 | Pre-flight: validates root, deps (python3/jq/sed/sha256sum/curl/systemctl), telegraf user exists, services installed, paths valid |
| 2 | Backup: copies current files to `/root/utm-pre-upgrade-<DATE>/`, snapshots dashboards via Grafana API, generates `rollback.sh` |
| 3 | Stops telegraf |
| 4 | Deploys script files: `credentials.py`, `ucs_traffic_monitor.py`, `lib/utm-common.sh`, `scripts/migrate_credentials.py`, `upgrade_utm.sh`, `backup_utm_dashboards.sh` (+ compat symlink) |
| 5 | Migrates credentials: converts `ucs_domains_group_*.txt` → `/etc/utm/creds.env` (chmod 600, owner telegraf) |
| 6 | Updates `telegraf.conf`: replaces legacy invocation with `--instance-name <name>` form |
| 7 | Sets up systemd EnvironmentFile drop-in for telegraf |
| 8 | Sets up Grafana provisioning + drops 9 migrated dashboards |
| 9 | Restarts telegraf and grafana-server, waits 60s |
| 10 | Validates: 6 advisory checks (InfluxDB/Grafana health, telegraf active, script log marker, recent data, dashboards present) |
| 11 | Prints summary with rollback command |

## Configuration via environment variables

| Variable | Default | Purpose |
|---|---|---|
| `UTM_DIR` | `/usr/local/telegraf` | Path to UTM repo on VM |
| `TELEGRAF_CONF_PATH` | `/etc/telegraf/telegraf.conf` | telegraf config |
| `CREDS_DIR` | `/etc/utm` | Where `creds.env` lives |
| `INSTANCE_NAME` | `utm` | Becomes `--instance-name` value + log file suffix |
| `SKIP_CONFIRMATIONS` | `0` | Set to `1` for non-interactive |
| `SKIP_GRAFANA_BACKUP` | `0` | Set to `1` to skip dashboard API snapshot (faster, no Grafana creds needed) |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `[ERROR] User 'telegraf' does not exist` | Telegraf not installed | `sudo zypper install telegraf` (or distro equivalent) |
| `[ERROR] UTM_DIR not found` | UTM in non-default path | `sudo UTM_DIR=/opt/utm ./install.sh` |
| `[ERROR] Failed to update telegraf.conf — invocation pattern not matched` | telegraf.conf doesn't have the legacy exec invocation | Either telegraf already configured for new format, or it lives elsewhere — inspect manually with `grep ucs_traffic_monitor /etc/telegraf/telegraf.conf` |
| Validation #5 fails (no FIEnvStats in 5m) | UCS unreachable from VM | Test: `curl -k https://<UCS-IP>/`. If fails, check firewall / network / credentials in `/etc/utm/creds.env` |
| Dashboards show "No data" | Time range too long, or `db` constant variable issue | Set time range to "Last 5 min" first; if still empty, see migration spec for known issues |

## Rollback

The install script generates a standalone rollback script at
`/root/utm-pre-upgrade-<DATE>/rollback.sh`. To roll back:

```sh
sudo bash /root/utm-pre-upgrade-<DATE>/rollback.sh
```

This restores the original `ucs_traffic_monitor.py`, `telegraf.conf`,
and `ucs_domains_group_*.txt`, removes the systemd drop-in and the
provisioning yaml, and restarts services. The new `creds.env` file is
left in place (harmless — old code doesn't read it).

If install.sh fails partway through (any phase 3-9), it auto-rolls
back via the same script.

## Multi-instance deployments

If your VM has multiple `ucs_domains_group_N.txt` files (multi-instance
collection), the script generates `creds.env`, `creds_2.env`, etc.
Only `creds.env` is wired into the systemd drop-in. To support
additional instances:

1. Edit `/etc/systemd/system/telegraf.service.d/utm-creds.conf`:
   ```ini
   [Service]
   EnvironmentFile=/etc/utm/creds.env
   EnvironmentFile=/etc/utm/creds_2.env
   ```
   (Multi-instance is non-trivial — env vars from later files override
   earlier ones if the same key is defined. Recommend separate
   telegraf instances instead.)
2. Or, more cleanly, run separate telegraf service units, each with
   its own drop-in pointing to one creds file.
3. Each invocation needs a unique `--instance-name` to keep log/pickle
   files separate.

## Build info

Each tarball includes a `BUILD_INFO` file with:
- `sha`: short git SHA of the branch built from
- `built`: ISO timestamp
- `branch`: branch name
- `host`: hostname of the build machine

Verify before running: `cat BUILD_INFO` after `tar xzf`.
```

- [ ] **Step 2: Commit**

```fish
git add deploy/README.md
git commit -m "Add deploy/README.md with quickstart, troubleshooting, rollback

Documents the tarball workflow, the 11 install phases, env var
overrides, common errors with fixes, the standalone rollback
script, and multi-instance considerations.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Build + push

### Task 8: Build a test tarball and verify structure

**Files:** none modified — verification only.

- [ ] **Step 1: Build the tarball**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
./deploy/pack.sh /tmp
```

Expected output: `Done: /tmp/utm-prod-deploy-<sha>.tar.gz` plus a list of contents.

- [ ] **Step 2: Inspect the tarball structure**

```fish
tar tzf /tmp/utm-prod-deploy-*.tar.gz | sort
```

Expected entries (some prefix order may vary):
- `./BUILD_INFO`
- `./README.md`
- `./install.sh`
- `./files/credentials.py`
- `./files/ucs_traffic_monitor.py`
- `./files/lib/utm-common.sh`
- `./files/scripts/migrate_credentials.py`
- `./files/upgrade_utm.sh`
- `./files/backup_utm_dashboards.sh`
- `./files/grafana/dashboards/chassis_pause.json`
- `./files/grafana/dashboards/chassis_traffic.json`
- `./files/grafana/dashboards/domain_overview.json`
- `./files/grafana/dashboards/domain_traffic.json`
- `./files/grafana/dashboards/ingress_congestion.json`
- `./files/grafana/dashboards/local_sys.json`
- `./files/grafana/dashboards/locations.json`
- `./files/grafana/dashboards/service_profile.json`
- `./files/grafana/dashboards/welcome.json`
- `./files/grafana/provisioning/utm.yml`
- `./files/systemd/telegraf-utm-creds.conf`

- [ ] **Step 3: Verify install.sh inside tarball is executable**

```fish
mkdir -p /tmp/utm-deploy-test
tar xzf /tmp/utm-prod-deploy-*.tar.gz -C /tmp/utm-deploy-test
ls -l /tmp/utm-deploy-test/install.sh
```

Expected: `-rwxr-xr-x` (executable bit set).

- [ ] **Step 4: Verify install.sh --help still works from extracted tarball**

```fish
/tmp/utm-deploy-test/install.sh --help 2>&1 | head -10
```

Expected: usage block prints without error.

- [ ] **Step 5: Cleanup**

```fish
rm -rf /tmp/utm-deploy-test /tmp/utm-prod-deploy-*.tar.gz
```

No commit (verification only).

---

### Task 9: Push branch to fork

**Files:** none modified — git operation.

- [ ] **Step 1: Confirm branch and clean state**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
git branch --show-current
git status
git log --oneline feat/grafana-12-modernization..HEAD
```

Expected: branch is `feat/prod-rollout-grafana-12`, working tree clean, log shows the new commits from this plan.

- [ ] **Step 2: Push**

```fish
git push -u origin feat/prod-rollout-grafana-12 2>&1 | tail -5
```

Expected: branch created on origin, tracking established.

- [ ] **Step 3: Verify on GitHub**

Open https://github.com/logomes/ucs_traffic_monitor/tree/feat/prod-rollout-grafana-12

Expected: branch visible with the `deploy/` directory containing `install.sh`, `pack.sh`, `README.md`.

- [ ] **Step 4: Build a versioned tarball for the user**

```fish
./deploy/pack.sh /home/lucgomes/
ls -lh /home/lucgomes/utm-prod-deploy-*.tar.gz
```

Expected: tarball at `/home/lucgomes/utm-prod-deploy-<sha>.tar.gz`, ready for `scp` to the production VM.

No commit (the tarball is intentionally not versioned — it's generated per release).

---

## Self-review notes

Spec coverage:
- ✅ Tarball self-contained (Tasks 6, 8)
- ✅ install.sh idempotent + auto-rollback (Tasks 2-5)
- ✅ Backup of current state + standalone rollback.sh (Task 3)
- ✅ Deploys script + lib + scripts + operator scripts (Task 4)
- ✅ Migrates credentials (Task 4)
- ✅ Updates telegraf.conf (Task 4)
- ✅ Sets up systemd EnvironmentFile (Task 5)
- ✅ Sets up Grafana provisioning + drops 9 dashboards (Task 5)
- ✅ Restarts services + validates (Task 5)
- ✅ All 12 acceptance criteria (Task 5 validate function + Task 8)
- ✅ pack.sh builds versioned tarball (Task 6)
- ✅ README.md operator guide (Task 7)

Items deliberately not in plan (per spec Non-Goals):
- Stack version migration (already done by operator)
- SOPS layer deploy (left opt-in)
- Real VM execution (operator's job)

Risk acknowledgment: install.sh hasn't been tested against a real SUSE VM. Smoke testing in a container is optional in this plan but recommended before the user runs it on production. Suggest the user does a `--dry-run` first.

## Next step (after this plan)

User executes the tarball on the production VM:
1. `./deploy/pack.sh ~`
2. `scp ~/utm-prod-deploy-*.tar.gz user@vm:/tmp/`
3. On VM: `tar xzf ... && sudo ./install.sh --dry-run` (verify plan)
4. On VM: `sudo ./install.sh` (execute)
5. Validate visually in browser
6. After 24-48h stable: `shred -u /usr/local/telegraf/ucs_domains_group_*.txt`

If issues surface during real execution, follow-ups go into a new sub-spec.
