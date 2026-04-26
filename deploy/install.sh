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
