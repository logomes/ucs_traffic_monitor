#!/usr/bin/env bash
#
# Decrypt UTM credentials and write /run/utm/creds.env atomically.
#
# Reads:
#   /etc/utm/credentials.sops.yaml  (SOPS-encrypted YAML)
#   /etc/utm/age.key                (age private key, chmod 600)
#
# Writes:
#   /run/utm/creds.env              (chmod 600, owner telegraf:telegraf)
#
# Run by utm-creds.service oneshot before utm.service starts.

set -euo pipefail

SOPS_INPUT="/etc/utm/credentials.sops.yaml"
AGE_KEY="/etc/utm/age.key"
OUT_DIR="/run/utm"
OUT_FILE="${OUT_DIR}/creds.env"
TMP_FILE="${OUT_FILE}.tmp.$$"

if [[ ! -f "${SOPS_INPUT}" ]]; then
    echo "ERROR: ${SOPS_INPUT} not found" >&2
    exit 1
fi

if [[ ! -f "${AGE_KEY}" ]]; then
    echo "ERROR: ${AGE_KEY} not found" >&2
    exit 1
fi

mkdir -p "${OUT_DIR}"
chmod 0700 "${OUT_DIR}"
chown telegraf:telegraf "${OUT_DIR}"

# Decrypt to a YAML stream, then convert to KEY=VALUE.
# We use Python (stdlib only) to avoid an extra yq dependency.
SOPS_AGE_KEY_FILE="${AGE_KEY}" \
    sops -d "${SOPS_INPUT}" | python3 - <<'PY' > "${TMP_FILE}"
import sys
import yaml

data = yaml.safe_load(sys.stdin)
domains = data.get("domains", {})

ids = list(domains.keys())
print(f"UTM_DOMAINS={','.join(ids)}")
print()

for domain_id, fields in domains.items():
    for key, env_suffix in (
        ("host", "HOST"),
        ("user", "USER"),
        ("password", "PASS"),
        ("group", "GROUP"),
    ):
        value = fields.get(key, "")
        # Single-quote escape for systemd EnvironmentFile.
        escaped = str(value).replace("'", "'\\''")
        print(f"UTM_{domain_id}_{env_suffix}='{escaped}'")
    print()
PY

chmod 0600 "${TMP_FILE}"
chown telegraf:telegraf "${TMP_FILE}"
mv "${TMP_FILE}" "${OUT_FILE}"

echo "Wrote ${OUT_FILE}"
