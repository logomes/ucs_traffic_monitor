#!/bin/bash
# UTM upgrade script.
# Initial Version coded on 26-Jul-2020 by Paresh (with Kiara).
# Refactored 2026 to consume lib/utm-common.sh.

set -euo pipefail

# shellcheck source=lib/utm-common.sh
# shellcheck disable=SC1091  # path is dynamic (readlink -f); shellcheck can't follow it statically
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/utm-common.sh"

# === Configuration (override via environment) ===

: "${UTM_VERSION:=5}"
: "${UTM_DIR:=/usr/local/telegraf}"
: "${GRAFANA_IMG_DIR:=/usr/share/grafana/public/img}"

# To pin to a different version, override via env vars and supply the
# matching SHA256. Get the SHA from the publisher's checksum file:
#   curl https://dl.grafana.com/oss/release/grafana-X.Y.Z-1.x86_64.rpm.sha256
#   curl https://dl.influxdata.com/telegraf/releases/telegraf-X.Y.Z-1.x86_64.rpm.sha256
: "${GRAFANA_VERSION:=7.5.7}"
: "${GRAFANA_RPM_SHA256:=5e7649985bed0e4994f10b86c938bd1e895e394e39b58946dc08e2ff3573e89b}"
: "${TELEGRAF_VERSION:=1.18.3}"
: "${TELEGRAF_RPM_SHA256:=793ab05a7ec17b7a08cf14ab68f4c60a44b352477294407db97fd9f1dea98e81}"

# === Kiara personality (preserved) ===

intro_kiara() {
    local kiara_birth=1528354800
    local today
    today="$(date +%s)"
    local kiara_age=$(( (today - kiara_birth) / (60 * 60 * 24 * 365) ))

    cat <<EOF

---------------------------
Hi there. I am Kiara.
I am ${kiara_age} years old and I can help you in upgrading your UTM installation.
I learned it with my daddy while he was working on it.
---------------------------
EOF
}

bye_kiara() {
    cat <<EOF

---------------------------
Bye - Kiara.
---------------------------
EOF
}

# === Phase functions ===

upgrade_packages_phase() {
    cat <<EOF
---------------------------
I can download Grafana ${GRAFANA_VERSION} and Telegraf ${TELEGRAF_VERSION} if this machine has Internet access.
If not, see the manual install steps in the README.
---------------------------
EOF
    if ! utm::confirm "May I access the Internet now? (y/n): "; then
        utm::log info "Skipping package downloads"
        return 0
    fi

    utm::log info "Downloading and upgrading Grafana ${GRAFANA_VERSION}"
    utm::download_with_checksum \
        "https://dl.grafana.com/oss/release/grafana-${GRAFANA_VERSION}-1.x86_64.rpm" \
        "$GRAFANA_RPM_SHA256" \
        "/tmp/grafana-${GRAFANA_VERSION}.rpm"
    yum -y localinstall "/tmp/grafana-${GRAFANA_VERSION}.rpm"
    utm::log info "Grafana upgrade done"

    utm::log info "Downloading and upgrading Telegraf ${TELEGRAF_VERSION}"
    utm::download_with_checksum \
        "https://dl.influxdata.com/telegraf/releases/telegraf-${TELEGRAF_VERSION}-1.x86_64.rpm" \
        "$TELEGRAF_RPM_SHA256" \
        "/tmp/telegraf-${TELEGRAF_VERSION}.rpm"
    yum -y localinstall "/tmp/telegraf-${TELEGRAF_VERSION}.rpm"
    systemctl restart telegraf
    utm::log info "Telegraf upgrade done"

    utm::log info "Installing Grafana plugins"
    grafana-cli plugins install agenty-flowcharting-panel
    grafana-cli plugins install michaeldmoore-multistat-panel
    utm::log info "Plugins installation done"
}

upgrade_images_phase() {
    utm::log info "Upgrading UTM images"
    mkdir -p "$GRAFANA_IMG_DIR/utm"
    if cp images/* "$GRAFANA_IMG_DIR/utm/"; then
        utm::log info "Images upgrade done"
    else
        utm::log warning "Could not copy UTM images to $GRAFANA_IMG_DIR/utm/"
    fi
}

upgrade_collector_phase() {
    utm::log info "Upgrading UTM receiver"
    local utm_old_ver utm_new_ver
    utm_old_ver="$(grep -Po '(?<=__version__ =).*' "${UTM_DIR}/ucs_traffic_monitor.py" | awk -F'"' '{print $2}')"
    utm_new_ver="$(grep -Po '(?<=__version__ =).*' telegraf/ucs_traffic_monitor.py | awk -F'"' '{print $2}')"

    utm::log info "Backing up existing UTM receiver (v${utm_old_ver})"
    cp "${UTM_DIR}/ucs_traffic_monitor.py" "${UTM_DIR}/ucs_traffic_monitor_${utm_old_ver}.py"

    cp telegraf/ucs_traffic_monitor.py "${UTM_DIR}/ucs_traffic_monitor.py"
    utm::log info "UTM receiver upgraded to v${utm_new_ver}"
}

toggle_legacy_grafana_settings() {
    utm::log info "Disabling deprecated disable_sanitize_html flag"
    sed -i '/^disable_sanitize_html*/s/^/;/' /etc/grafana/grafana.ini
    utm::log info "Done"
}

backup_existing_dashboards() {
    utm::log info "Backing up existing UTM dashboards"
    local dest_dir
    dest_dir="${UTM_DIR}/grafana/dashboards_$(date +%M%H%m%d%y)"
    mkdir -p "$dest_dir"
    utm::backup_all_dashboards "$dest_dir"
    utm::log info "Backup saved to ${dest_dir}"

    # Remember folder/dashboard ids so the upgrade keeps them stable.
    declare -gA fid_arr
    declare -gA db_id_arr
    local item
    for item in "${!UTM_DASHBOARDS[@]}"; do
        fid_arr["$item"]="$(jq -r '.meta.folderId' "${dest_dir}/${item}.json")"
        db_id_arr["$item"]="$(jq -r '.dashboard.id' "${dest_dir}/${item}.json")"
    done
}

upgrade_dashboards() {
    utm::log info "Upgrading UTM dashboards"
    if ! utm::confirm "Are you sure? (y/n): "; then
        utm::log info "Dashboard upgrade aborted by user"
        return 0
    fi

    local locations_uid="${UTM_DASHBOARDS[locations]}"
    local locations_id=1
    local item fid db_id new_id

    for item in "${!UTM_DASHBOARDS[@]}"; do
        cp "grafana/dashboards/${item}.json" "/tmp/${item}.json"
        fid="${fid_arr[$item]}"
        db_id="${db_id_arr[$item]}"
        printf 'Upgrading %-25s -- in Folder %-3s -- with ID %-3s -- to UTM version %-3s\n' \
            "$item" "$fid" "$db_id" "$UTM_VERSION"

        # Wrap, set version, set id, add folder + overwrite flag.
        jq '{"dashboard": .}' "/tmp/${item}.json" > "/tmp/${item}_1.json"
        jq ".dashboard.version = ${UTM_VERSION}" "/tmp/${item}_1.json" > "/tmp/${item}.json"
        jq ".dashboard.id = ${db_id}" "/tmp/${item}.json" > "/tmp/${item}_1.json"
        jq ". + { \"folderId\": ${fid}, \"overwrite\": true }" "/tmp/${item}_1.json" > "/tmp/${item}.json"

        new_id="$(utm::grafana_curl POST /api/dashboards/db --data "@/tmp/${item}.json" \
            | jq -r --arg uid "$locations_uid" '. | select(.. | .uid? == $uid).id')"
        if [[ -n "$new_id" ]]; then
            locations_id="$new_id"
        fi
    done

    utm::log info "Dashboards upgraded"
    utm::log info "Setting home dashboard to ID ${locations_id}"
    utm::grafana_curl PUT /api/user/preferences \
        --data "{\"theme\":\"\",\"homeDashboardId\":${locations_id},\"timezone\":\"\"}" > /dev/null
}

# === Main ===

main() {
    intro_kiara
    if ! utm::confirm "May I continue? (y/n): "; then
        bye_kiara
        exit 0
    fi
    utm::require_jq

    if utm::confirm "Upgrade everything (a) or just dashboards (any other key)? "; then
        upgrade_packages_phase
        upgrade_images_phase
        upgrade_collector_phase
        toggle_legacy_grafana_settings
    fi

    if utm::confirm "Are you ready to upgrade UI dashboards? (y/n): "; then
        utm::grafana_login_loop
        backup_existing_dashboards
        upgrade_dashboards
    fi

    systemctl restart grafana-server
    bye_kiara
}

main "$@"
