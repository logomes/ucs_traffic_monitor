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
