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
# shellcheck disable=SC2034
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

# utm::download_with_checksum <url> <expected-sha256> <output-path>
# Downloads url to output-path, verifies SHA256 matches expected.
# On mismatch: deletes output, exits 1 with diagnostic.
# Implementation uses curl (-fL: fail on HTTP error, follow redirects).
utm::download_with_checksum() {
    local url="${1:?url required}"
    local expected="${2:?expected sha256 required}"
    local output="${3:?output path required}"

    utm::log info "Downloading ${url}"
    if ! curl -fLs --output "$output" "$url"; then
        utm::log error "Download failed: ${url}"
        return 1
    fi

    local actual
    actual="$(sha256sum "$output" | awk '{print $1}')"

    # Case-insensitive comparison.
    if [[ "${actual,,}" != "${expected,,}" ]]; then
        utm::log error "SHA256 mismatch for ${output}"
        utm::log error "  expected: ${expected}"
        utm::log error "  actual:   ${actual}"
        rm -f "$output"
        return 1
    fi

    utm::log info "Verified ${output} (sha256 ok)"
    return 0
}

# utm::grafana_curl <method> <path> [<extra-curl-args>...]
# Wraps curl with --user (no creds in URL), JSON headers, fail-on-HTTP-error.
# Requires GRAFANA_USER and GRAFANA_PASSWORD to be set.
utm::grafana_curl() {
    local method="${1:?method required}"
    local path="${2:?path required}"
    shift 2
    curl -fsS \
        --user "${GRAFANA_USER}:${GRAFANA_PASSWORD}" \
        -H 'Accept: application/json' \
        -H 'Content-Type: application/json' \
        -X "$method" \
        "$@" \
        "http://${UTM_GRAFANA_HOST}${path}"
}

# utm::grafana_login_loop
# Prompts user/password until /api/org succeeds. Sets globals
# GRAFANA_USER and GRAFANA_PASSWORD.
utm::grafana_login_loop() {
    while true; do
        unset GRAFANA_USER GRAFANA_PASSWORD
        while [[ -z "${GRAFANA_USER:-}" ]]; do
            read -r -p "Grafana User: " GRAFANA_USER
        done
        while [[ -z "${GRAFANA_PASSWORD:-}" ]]; do
            read -r -s -p "Password: " GRAFANA_PASSWORD
            printf '\n'
        done

        local resp
        if resp="$(utm::grafana_curl GET /api/org 2>&1)"; then
            utm::log info "Authenticated to Grafana as ${GRAFANA_USER}"
            return 0
        fi
        utm::log warning "Authentication failed: ${resp}"
        utm::log warning "Please try again."
    done
}

# utm::backup_dashboard <uid> <output-file>
# Saves the full dashboard JSON returned by /api/dashboards/uid/<uid>.
utm::backup_dashboard() {
    local uid="${1:?uid required}"
    local out="${2:?output file required}"
    utm::grafana_curl GET "/api/dashboards/uid/${uid}" > "$out"
}

# utm::backup_all_dashboards <dest-dir>
# Backs up every dashboard in UTM_DASHBOARDS to <dest-dir>/<name>.json.
utm::backup_all_dashboards() {
    local dest="${1:?destination directory required}"
    local name uid
    for name in "${!UTM_DASHBOARDS[@]}"; do
        uid="${UTM_DASHBOARDS[$name]}"
        utm::backup_dashboard "$uid" "${dest}/${name}.json"
        utm::log info "Backed up ${name} (uid=${uid})"
    done
}
