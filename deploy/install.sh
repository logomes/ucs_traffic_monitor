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

# shellcheck disable=SC2155
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FILES_DIR="${SCRIPT_DIR}/files"
# shellcheck disable=SC2155
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
