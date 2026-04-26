#!/bin/bash
# pack.sh — build the UTM production deployment tarball.
#
# Usage:
#   ./deploy/pack.sh                  # builds utm-prod-deploy-<sha>.tar.gz
#   ./deploy/pack.sh /tmp             # writes to /tmp/utm-prod-deploy-<sha>.tar.gz
#
# Run from repo root.

set -euo pipefail

# shellcheck disable=SC2155
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly OUT_DIR="${1:-${REPO_ROOT}}"
# shellcheck disable=SC2155
readonly SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
readonly TARBALL="${OUT_DIR}/utm-prod-deploy-${SHA}.tar.gz"
# shellcheck disable=SC2155
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
