#!/bin/bash
# Shared helpers for UTM operator scripts (upgrade_utm.sh, backup_utm_dashboards.sh).
#
# Conventions:
#   - Function names use the utm:: prefix to avoid collision with bash builtins.
#   - Caller scripts are expected to set `set -euo pipefail` themselves.
#   - I/O variables: GRAFANA_USER, GRAFANA_PASSWORD (set by utm::grafana_login_loop).
#
# Public API (defined below):
#   utm::confirm <prompt>
#   utm::log <level> <msg>
#   utm::require_jq
#   utm::download_with_checksum <url> <expected-sha256> <output-path>
#   utm::grafana_curl <method> <path> [<extra-curl-args>...]
#   utm::grafana_login_loop
#   utm::backup_dashboard <uid> <output-file>
#   utm::backup_all_dashboards <dest-dir>
#
# Public data:
#   UTM_DASHBOARDS  associative array (name → grafana UID)

# Grafana host (override via env if Grafana is on non-default host/port).
: "${UTM_GRAFANA_HOST:=localhost:3000}"

# utm::log <level> <msg>
# Print a timestamped log line to stderr. Level is uppercased.
utm::log() {
    local level="${1:?level required}"
    local msg="${2:?msg required}"
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    printf '[%s] %s: %s\n' "$ts" "${level^^}" "$msg" >&2
}

# utm::confirm <prompt>
# Read one character; return 0 for y/Y, 1 for anything else.
utm::confirm() {
    local prompt="${1:-Continue? (y/n):}"
    local reply
    read -r -n 1 -p "$prompt" reply
    printf '\n' >&2
    [[ "$reply" =~ ^[Yy]$ ]]
}

# Canonical dashboard UID list. Single source of truth — both the upgrade
# script and the backup script consume this. Adding a new dashboard means
# editing one line here.
declare -gA UTM_DASHBOARDS=(
    ["locations"]="ri2OFp4Wz"
    ["domain_overview"]="Inte2EIWk"
    ["domain_traffic"]="W7LSukHWz"
    ["chassis_traffic"]="KOM8ZHNWz"
    ["service_profile"]="Z0M_N1vWz"
    ["ingress_congestion"]="Sve32sDZk"
    ["chassis_pause"]="SVO-VNiWk"
    ["local_sys"]="9CXO3jTWz"
)

# utm::require_jq
# Aborts the calling script if jq is not on PATH.
utm::require_jq() {
    if ! command -v jq >/dev/null 2>&1; then
        utm::log error "jq is required but not installed. Install via your package manager (e.g., 'sudo pacman -S jq' or 'sudo yum install jq')."
        exit 1
    fi
}
