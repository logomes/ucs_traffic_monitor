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
