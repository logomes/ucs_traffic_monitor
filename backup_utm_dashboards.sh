#!/bin/bash
# Backup of UTM dashboards.
# Initial Version coded on 26-Jul-2020 by Paresh (with Kiara)
# Refactored 2026 to consume lib/utm-common.sh.

set -euo pipefail

# shellcheck source=lib/utm-common.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/utm-common.sh"

: "${UTM_DIR:=/usr/local/telegraf}"

main() {
    utm::require_jq
    utm::grafana_login_loop

    local dest_dir
    dest_dir="${UTM_DIR}/grafana/dashboards_$(date +%M%H%m%d%y)"

    utm::log info "Taking backup of UTM dashboards"
    if ! mkdir -p "$dest_dir"; then
        utm::log error "Unable to create ${dest_dir}"
        exit 1
    fi

    utm::backup_all_dashboards "$dest_dir"
    utm::log info "Backup saved to ${dest_dir}"
}

main "$@"
