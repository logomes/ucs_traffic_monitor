# UTM Bash Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar três vetores de segurança nos shell scripts do UTM (URLs com creds, downloads sem checksum, falhas silenciosas) consolidando lógica compartilhada em `lib/utm-common.sh`.

**Architecture:** Lib única (`lib/utm-common.sh`) concentra helpers (`utm::` prefix). Os dois scripts de operador (`upgrade_utm.sh`, `backup_utm_dashboards.sh`) viram clientes finos da lib. Testes de funções puras em bats; funções com I/O testadas via smoke test contra o test-env Docker já existente. CI roda shellcheck + bats no GitHub Actions.

**Tech Stack:** bash 5+, shellcheck 0.9+, bats-core 1.10+, curl, jq, sha256sum, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-04-26-bash-hygiene-design.md`

**Repository:** `/home/lucgomes/Downloads/ucs_traffic_monitor` em branch `feat/credentials-env-vars`

---

## Phase 1 — Tooling setup

### Task 1: Install shellcheck and bats locally

**Files:** none (system setup only)

- [ ] **Step 1: Install shellcheck and bats-core**

```fish
sudo pacman -S shellcheck bats
```

(Se `bats` não estiver disponível como `bats`, pode estar como `bats-core` — `pacman -Ss bats` lista pacotes. Em distros sem pacote oficial: `git clone https://github.com/bats-core/bats-core.git /tmp/bats && sudo /tmp/bats/install.sh /usr/local`.)

- [ ] **Step 2: Verify versions**

```fish
shellcheck --version | head -2
bats --version
```

Expected: shellcheck >= 0.9, bats >= 1.x.

No commit (system tools, not project).

---

## Phase 2 — `lib/utm-common.sh` (pure functions, TDD)

### Task 2: Scaffolding + first failing test (`utm::confirm`)

**Files:**
- Create: `lib/utm-common.sh`
- Create: `tests/bash/test_utm_common.bats`

- [ ] **Step 1: Create `lib/utm-common.sh` with header**

`/home/lucgomes/Downloads/ucs_traffic_monitor/lib/utm-common.sh`:

```bash
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
```

- [ ] **Step 2: Create `tests/bash/test_utm_common.bats` with first failing test**

```bash
#!/usr/bin/env bats

# Source the lib under test from the repo root regardless of cwd.
LIB_PATH="$BATS_TEST_DIRNAME/../../lib/utm-common.sh"

setup() {
    # shellcheck disable=SC1090
    source "$LIB_PATH"
}

@test "utm::confirm returns 0 for 'y'" {
    run bash -c "source '$LIB_PATH'; printf 'y' | utm::confirm 'go?'"
    [ "$status" -eq 0 ]
}
```

- [ ] **Step 3: Run test, confirm it fails**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
bats tests/bash/
```

Expected: FAIL — `utm::confirm` not defined.

- [ ] **Step 4: Commit failing test**

```fish
git add lib/utm-common.sh tests/bash/test_utm_common.bats
git commit -m "Add lib/utm-common.sh skeleton + first failing bats test

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Implement `utm::confirm` and `utm::log`

**Files:**
- Modify: `lib/utm-common.sh`
- Modify: `tests/bash/test_utm_common.bats`

- [ ] **Step 1: Implement `utm::confirm` and `utm::log`**

Append to `lib/utm-common.sh`:

```bash
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
```

- [ ] **Step 2: Add more tests for confirm + log**

Append to `tests/bash/test_utm_common.bats`:

```bash
@test "utm::confirm returns 0 for 'Y'" {
    run bash -c "source '$LIB_PATH'; printf 'Y' | utm::confirm 'go?'"
    [ "$status" -eq 0 ]
}

@test "utm::confirm returns 1 for 'n'" {
    run bash -c "source '$LIB_PATH'; printf 'n' | utm::confirm 'go?'"
    [ "$status" -eq 1 ]
}

@test "utm::confirm returns 1 for empty input" {
    run bash -c "source '$LIB_PATH'; printf '' | utm::confirm 'go?'"
    [ "$status" -eq 1 ]
}

@test "utm::log writes to stderr in expected format" {
    run bash -c "source '$LIB_PATH'; utm::log info 'hello' 2>&1 1>/dev/null"
    [ "$status" -eq 0 ]
    [[ "$output" =~ \[[0-9-]+\ [0-9:]+\]\ INFO:\ hello ]]
}

@test "utm::log uppercases level" {
    run bash -c "source '$LIB_PATH'; utm::log warning 'careful' 2>&1 1>/dev/null"
    [[ "$output" =~ WARNING ]]
}
```

- [ ] **Step 3: Run tests, all pass**

```fish
bats tests/bash/
```

Expected: 5 tests pass.

- [ ] **Step 4: Commit**

```fish
git add lib/utm-common.sh tests/bash/test_utm_common.bats
git commit -m "Add utm::confirm and utm::log helpers + tests

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Implement `utm::require_jq` and `UTM_DASHBOARDS` array

**Files:**
- Modify: `lib/utm-common.sh`
- Modify: `tests/bash/test_utm_common.bats`

- [ ] **Step 1: Add to `lib/utm-common.sh`**

Append:

```bash
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
```

- [ ] **Step 2: Add tests**

Append to `tests/bash/test_utm_common.bats`:

```bash
@test "UTM_DASHBOARDS has 8 entries" {
    run bash -c "source '$LIB_PATH'; echo \${#UTM_DASHBOARDS[@]}"
    [ "$status" -eq 0 ]
    [ "$output" = "8" ]
}

@test "UTM_DASHBOARDS contains 'locations' key" {
    run bash -c "source '$LIB_PATH'; echo \${UTM_DASHBOARDS[locations]}"
    [ "$output" = "ri2OFp4Wz" ]
}

@test "utm::require_jq succeeds when jq is present" {
    run bash -c "source '$LIB_PATH'; utm::require_jq; echo ok"
    [ "$status" -eq 0 ]
    [[ "$output" =~ ok ]]
}

@test "utm::require_jq fails when jq is absent" {
    # Run the function with PATH that excludes jq.
    run bash -c "PATH=/nonexistent source '$LIB_PATH'; utm::require_jq"
    [ "$status" -eq 1 ]
}
```

- [ ] **Step 3: Run tests, all pass**

```fish
bats tests/bash/
```

Expected: 9 tests pass.

- [ ] **Step 4: Commit**

```fish
git add lib/utm-common.sh tests/bash/test_utm_common.bats
git commit -m "Add UTM_DASHBOARDS canonical array + utm::require_jq

Eight dashboards collapse to a single source of truth used by both
the upgrade and backup scripts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Implement `utm::download_with_checksum`

**Files:**
- Modify: `lib/utm-common.sh`
- Modify: `tests/bash/test_utm_common.bats`

- [ ] **Step 1: Add the function**

Append to `lib/utm-common.sh`:

```bash
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
```

- [ ] **Step 2: Add bats tests using local files (no network)**

Append to `tests/bash/test_utm_common.bats`:

```bash
@test "utm::download_with_checksum succeeds when sha matches" {
    local content="hello world\n"
    local tmp_src
    tmp_src="$(mktemp)"
    printf '%b' "$content" > "$tmp_src"
    local expected
    expected="$(sha256sum "$tmp_src" | awk '{print $1}')"

    local tmp_dst
    tmp_dst="$(mktemp -u)"

    run bash -c "source '$LIB_PATH'; utm::download_with_checksum 'file://$tmp_src' '$expected' '$tmp_dst'"
    [ "$status" -eq 0 ]
    [ -f "$tmp_dst" ]

    rm -f "$tmp_src" "$tmp_dst"
}

@test "utm::download_with_checksum fails when sha does not match" {
    local tmp_src
    tmp_src="$(mktemp)"
    printf 'real content\n' > "$tmp_src"
    local wrong="0000000000000000000000000000000000000000000000000000000000000000"

    local tmp_dst
    tmp_dst="$(mktemp -u)"

    run bash -c "source '$LIB_PATH'; utm::download_with_checksum 'file://$tmp_src' '$wrong' '$tmp_dst'"
    [ "$status" -ne 0 ]
    [ ! -f "$tmp_dst" ]
    [[ "$output" =~ "SHA256 mismatch" ]]

    rm -f "$tmp_src"
}

@test "utm::download_with_checksum is case-insensitive on sha" {
    local tmp_src
    tmp_src="$(mktemp)"
    printf 'x\n' > "$tmp_src"
    local expected_lower
    expected_lower="$(sha256sum "$tmp_src" | awk '{print $1}')"
    local expected_upper="${expected_lower^^}"

    local tmp_dst
    tmp_dst="$(mktemp -u)"

    run bash -c "source '$LIB_PATH'; utm::download_with_checksum 'file://$tmp_src' '$expected_upper' '$tmp_dst'"
    [ "$status" -eq 0 ]

    rm -f "$tmp_src" "$tmp_dst"
}
```

- [ ] **Step 3: Run tests**

```fish
bats tests/bash/
```

Expected: 12 tests pass.

- [ ] **Step 4: Commit**

```fish
git add lib/utm-common.sh tests/bash/test_utm_common.bats
git commit -m "Add utm::download_with_checksum with bats coverage

Curl-based download with SHA256 verification. Tests cover happy path,
mismatch (file deleted), and case-insensitive comparison.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — `lib/utm-common.sh` IO functions (no unit tests, smoke later)

### Task 6: Implement Grafana helpers and dashboard backup

**Files:**
- Modify: `lib/utm-common.sh`

- [ ] **Step 1: Append the four IO helpers**

```bash
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
```

- [ ] **Step 2: Run shellcheck**

```fish
shellcheck lib/utm-common.sh
```

Expected: 0 issues. If issues, address them — most likely `SC2155` (declare and assign separately) or `SC2154` (variable assigned externally) — fix or `# shellcheck disable=` with comment.

- [ ] **Step 3: Run all bats tests still pass**

```fish
bats tests/bash/
```

Expected: 12 tests pass (no new tests added — these IO helpers are tested via smoke test in Task 8).

- [ ] **Step 4: Commit**

```fish
git add lib/utm-common.sh
git commit -m "Add Grafana IO helpers (grafana_curl, login_loop, backup_*)

Replaces URL-embedded credentials (http://user:pass@host) with
curl --user. backup_all_dashboards iterates the canonical
UTM_DASHBOARDS array. IO helpers are smoke-tested rather than
unit-tested (depend on Grafana availability).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — `backup_utm_dashboards.sh`

### Task 7: Rewrite backup script and add compat symlink

**Files:**
- Create: `backup_utm_dashboards.sh`
- Delete: `backup_utm_bashboards.sh` (file)
- Create: `backup_utm_bashboards.sh` (symlink)

- [ ] **Step 1: Create the new backup script**

`/home/lucgomes/Downloads/ucs_traffic_monitor/backup_utm_dashboards.sh`:

```bash
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
```

Make it executable:

```fish
chmod +x backup_utm_dashboards.sh
```

- [ ] **Step 2: Replace the old typo'd file with a symlink**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
git rm backup_utm_bashboards.sh
ln -s backup_utm_dashboards.sh backup_utm_bashboards.sh
git add backup_utm_bashboards.sh
```

- [ ] **Step 3: Verify symlink resolves correctly**

```fish
ls -la backup_utm_bashboards.sh
readlink backup_utm_bashboards.sh
```

Expected: arrow points to `backup_utm_dashboards.sh`.

- [ ] **Step 4: shellcheck**

```fish
shellcheck backup_utm_dashboards.sh
```

Expected: 0 issues.

- [ ] **Step 5: bats still pass**

```fish
bats tests/bash/
```

Expected: 12 tests pass.

- [ ] **Step 6: Commit**

```fish
git add backup_utm_dashboards.sh
git commit -m "Rewrite backup_utm_dashboards.sh consuming lib/utm-common.sh

30 lines replacing the previous 62-line script with duplicated logic.
Uses utm::grafana_login_loop (no creds in URLs) and the canonical
UTM_DASHBOARDS array. Rename fixes the 'bashboards' typo;
backup_utm_bashboards.sh remains as a compat symlink for now.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Smoke test backup against the test-env

**Files:** none modified — verification only.

- [ ] **Step 1: Ensure test-env is up**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor/test-env
sg docker -c "docker compose ps"
```

If services aren't running:

```fish
sg docker -c "docker compose up -d"
```

Wait until `utm-grafana` is up.

- [ ] **Step 2: Run the backup script pointing to test-env Grafana**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
mkdir -p /tmp/utm-backup-test
UTM_DIR=/tmp/utm-backup-test \
    UTM_GRAFANA_HOST=localhost:3000 \
    ./backup_utm_dashboards.sh
```

When prompted: enter `admin` and your test-env Grafana password.

- [ ] **Step 3: Verify outputs**

The dashboards backed up here are by their original UCS UIDs (`ri2OFp4Wz` etc.). The test-env's Grafana doesn't necessarily have dashboards under those exact UIDs — it has the JSONs imported by uid found in the local files. So this test will likely produce JSON files containing Grafana error responses ("Dashboard not found") rather than real dashboards.

That's an acceptable smoke test outcome: it proves auth works, it proves the iteration over UTM_DASHBOARDS works, and the curl calls aren't using URL-creds. To verify auth specifically:

```fish
ls /tmp/utm-backup-test/grafana/dashboards_*/
cat /tmp/utm-backup-test/grafana/dashboards_*/locations.json | head -20
```

Expected: 8 JSON files. Their content will vary based on whether the UID exists in test-env Grafana.

- [ ] **Step 4: Confirm no creds leaked in the script's stderr**

```fish
UTM_DIR=/tmp/utm-backup-test ./backup_utm_dashboards.sh 2>&1 | grep -E '(@localhost|password)' | head
```

Enter creds when prompted. Expected: no output (no creds in stderr).

- [ ] **Step 5: Cleanup**

```fish
rm -rf /tmp/utm-backup-test
```

No commit (verification only).

---

## Phase 5 — `upgrade_utm.sh`

### Task 9: Compute SHA256 for default RPM versions

**Files:** none yet — captures values for next task.

- [ ] **Step 1: Fetch SHAs from publisher**

```fish
curl -fsSL https://dl.grafana.com/oss/release/grafana-7.5.7-1.x86_64.rpm.sha256 | head -1
curl -fsSL https://dl.influxdata.com/telegraf/releases/telegraf-1.18.3-1.x86_64.rpm.sha256 | head -1
```

Each command should print a 64-char hex string. Save these — they go into the script in the next task.

If either URL returns 404 (publisher rotated/removed), update the version constants to whatever's currently published (latest 7.x and 1.18.x). Document the choice in Task 10's commit.

No commit (just data capture).

---

### Task 10: Rewrite `upgrade_utm.sh`

**Files:**
- Modify: `upgrade_utm.sh` (full rewrite)

- [ ] **Step 1: Replace `upgrade_utm.sh` with the refactored version**

`/home/lucgomes/Downloads/ucs_traffic_monitor/upgrade_utm.sh`:

```bash
#!/bin/bash
# UTM upgrade script.
# Initial Version coded on 26-Jul-2020 by Paresh (with Kiara).
# Refactored 2026 to consume lib/utm-common.sh.

set -euo pipefail

# shellcheck source=lib/utm-common.sh
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
: "${GRAFANA_RPM_SHA256:=<INSERT GRAFANA SHA FROM TASK 9>}"
: "${TELEGRAF_VERSION:=1.18.3}"
: "${TELEGRAF_RPM_SHA256:=<INSERT TELEGRAF SHA FROM TASK 9>}"

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
```

**Replace `<INSERT GRAFANA SHA FROM TASK 9>` and `<INSERT TELEGRAF SHA FROM TASK 9>` with the values you captured in Task 9.** These two strings are the only manual interpolation in the file — no other placeholders.

- [ ] **Step 2: Verify the placeholders are gone**

```fish
grep '<INSERT' upgrade_utm.sh
```

Expected: empty (zero hits). If it returns lines, you forgot to substitute the SHAs.

- [ ] **Step 3: shellcheck**

```fish
shellcheck upgrade_utm.sh
```

Expected: 0 issues. If `SC2155` (declare and assign separately) — fix. If `SC1091` (can't follow non-constant source) — already disabled with `# shellcheck source=...`. Other issues likely warrant fixing.

- [ ] **Step 4: Syntax check**

```fish
bash -n upgrade_utm.sh
```

Expected: silent (no output) — no syntax errors.

- [ ] **Step 5: Commit**

```fish
git add upgrade_utm.sh
git commit -m "Rewrite upgrade_utm.sh consuming lib/utm-common.sh

Replaces the 291-line monolith with named phase functions and a
main() at the bottom (idiomatic bash). Eliminates URL-embedded
credentials, adds SHA256 verification on RPM downloads, removes
the weak-password hint, and gates downloads behind set -euo
pipefail. Versions parametrizable via env vars (GRAFANA_VERSION,
GRAFANA_RPM_SHA256, TELEGRAF_VERSION, TELEGRAF_RPM_SHA256) so
the operator can pin without editing the script. Kiara personality
preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Smoke test upgrade auth flow against test-env

**Files:** none modified.

The full upgrade script can't be smoke-tested end-to-end (it touches yum, systemctl, /etc/grafana/grafana.ini — destructive on a real system). What we CAN smoke-test is the auth + jq prerequisite gates.

- [ ] **Step 1: Run with quick "no" to everything to exercise the flow**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor

# Answer 'y' to "May I continue", 'n' to "Upgrade everything", 'n' to dashboards
printf 'y\nn\nn\n' | UTM_DIR=/tmp ./upgrade_utm.sh 2>&1 | head -30
```

Expected: Kiara intro, "May I continue?", then "Upgrade everything?", then "Are you ready to upgrade UI dashboards?" — exits cleanly (will `systemctl restart` at the end which fails on a non-RHEL host; that's acceptable for smoke purposes — verify it got to that line).

- [ ] **Step 2: Confirm grep checks pass**

```fish
grep -c '@localhost' upgrade_utm.sh backup_utm_dashboards.sh lib/utm-common.sh
grep -c 'set -euo pipefail' upgrade_utm.sh backup_utm_dashboards.sh
grep -c 'sha256' upgrade_utm.sh
grep -c 'Hint:admin/Utm_12345' upgrade_utm.sh
```

Expected:
- `@localhost`: 0
- `set -euo pipefail`: 2
- `sha256`: ≥ 4 (2 var assignments + 2 calls to download_with_checksum + 1 in comment)
- `Hint:admin/Utm_12345`: 0

No commit (verification only).

---

## Phase 6 — CI + docs

### Task 12: Update GitHub Actions CI

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Read the current workflow**

```fish
cat .github/workflows/ci.yml
```

- [ ] **Step 2: Append shellcheck and bats steps**

Edit `.github/workflows/ci.yml`. The current `test:` job ends with the pytest step. Add two new steps after the pytest step (still under `steps:`):

```yaml
      - name: Install shellcheck and bats
        run: sudo apt-get update && sudo apt-get install -y shellcheck bats

      - name: Lint shell scripts
        run: |
          shellcheck lib/utm-common.sh upgrade_utm.sh backup_utm_dashboards.sh

      - name: Run bats tests
        run: bats tests/bash/
```

Indent must match the existing steps (typically 6 spaces for the `- name:` line).

- [ ] **Step 3: Validate YAML**

```fish
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" 2>&1 && echo "YAML OK"
```

Expected: "YAML OK".

- [ ] **Step 4: Commit**

```fish
git add .github/workflows/ci.yml
git commit -m "CI: add shellcheck and bats for shell scripts

Lints lib/utm-common.sh and the two operator scripts; runs the
bats unit tests for pure functions. Runs only on Ubuntu (the
existing matrix entry) — the matrix is per-Python and the shell
checks don't vary by Python version.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Find the existing "Configuration" section**

```fish
grep -n '^##' README.md
```

The Configuration section was added in the credentials work — find the line number where it ends, just before the next `##` heading.

- [ ] **Step 2: Add a new subsection at the end of Configuration**

Insert these lines before the next top-level heading:

```markdown
### Customizing upgrade_utm.sh

The upgrade script's package versions are parametrizable via env vars.
To upgrade to a different Grafana or Telegraf version, override the
version and supply the matching SHA256 from the publisher's checksum
file:

```sh
GRAFANA_VERSION=7.5.7 \
GRAFANA_RPM_SHA256=$(curl -fsSL https://dl.grafana.com/oss/release/grafana-7.5.7-1.x86_64.rpm.sha256 | head -1) \
TELEGRAF_VERSION=1.18.3 \
TELEGRAF_RPM_SHA256=$(curl -fsSL https://dl.influxdata.com/telegraf/releases/telegraf-1.18.3-1.x86_64.rpm.sha256 | head -1) \
./upgrade_utm.sh
```

The script verifies SHA256 before installing — a mismatch aborts the
upgrade with the offending hash printed.
```

- [ ] **Step 3: Commit**

```fish
git add README.md
git commit -m "Document upgrade_utm.sh env-var customization

Explains how operators can pin different Grafana/Telegraf versions
and where to source the matching SHA256.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Final acceptance gate

**Files:** none modified — verification only.

Run all 9 acceptance criteria from the spec. Each should pass.

- [ ] **Step 1: Bash syntax**

```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
bash -n lib/utm-common.sh && \
bash -n upgrade_utm.sh && \
bash -n backup_utm_dashboards.sh && \
echo "PASS"
```

- [ ] **Step 2: shellcheck**

```fish
shellcheck lib/utm-common.sh upgrade_utm.sh backup_utm_dashboards.sh && echo "PASS"
```

- [ ] **Step 3: bats tests**

```fish
bats tests/bash/ && echo "PASS"
```

- [ ] **Step 4: No URL-embedded creds**

```fish
test "$(grep -c '@localhost' upgrade_utm.sh backup_utm_dashboards.sh)" -eq 0 && echo "PASS"
```

- [ ] **Step 5: set -euo pipefail in operator scripts**

```fish
test "$(grep -c 'set -euo pipefail' upgrade_utm.sh backup_utm_dashboards.sh)" -eq 2 && echo "PASS"
```

- [ ] **Step 6: SHA256 references in upgrade**

```fish
test "$(grep -c 'sha256\|SHA256' upgrade_utm.sh)" -ge 4 && echo "PASS"
```

- [ ] **Step 7: Weak password hint removed**

```fish
test "$(grep -c 'Hint:admin/Utm_12345' upgrade_utm.sh)" -eq 0 && echo "PASS"
```

- [ ] **Step 8: Symlink in place**

```fish
test -L backup_utm_bashboards.sh && \
test "$(readlink backup_utm_bashboards.sh)" = "backup_utm_dashboards.sh" && \
echo "PASS"
```

- [ ] **Step 9: Backup smoke test still works**

(Repeat the smoke test from Task 8 — this is the same procedure, included here for the final-gate completeness.)

```fish
mkdir -p /tmp/utm-final-smoke
UTM_DIR=/tmp/utm-final-smoke ./backup_utm_dashboards.sh < /dev/null 2>&1 || true
ls /tmp/utm-final-smoke/grafana/dashboards_*/ 2>&1 | head -5
rm -rf /tmp/utm-final-smoke
```

If you can't get an interactive prompt to work in a non-TTY context, just verify the script's first few lines print before the prompt — that proves the lib loads and main starts.

No commit (gate only).

---

### Task 15: Push to fork

**Files:** none modified — git push.

- [ ] **Step 1: Check branch**

```fish
git branch --show-current
```

Expected: `feat/credentials-env-vars`.

- [ ] **Step 2: Push**

```fish
git push origin feat/credentials-env-vars 2>&1 | tail -5
```

Expected: pushes the new commits from Tasks 2-13 to the fork.

- [ ] **Step 3: Verify on GitHub**

Open https://github.com/logomes/ucs_traffic_monitor/blob/feat/credentials-env-vars/lib/utm-common.sh

Expected: file exists with full content.

---

## Self-review notes

Spec coverage:
- ✅ `lib/utm-common.sh` with all 9 helpers (Tasks 2–6)
- ✅ Refactored `upgrade_utm.sh` (Task 10)
- ✅ Renamed `backup_utm_dashboards.sh` + symlink (Task 7)
- ✅ bats tests for pure functions (Tasks 2–5)
- ✅ shellcheck + bats in CI (Task 12)
- ✅ README updates (Task 13)
- ✅ All 9 acceptance criteria validated (Task 14)

Threat model coverage:
- ✅ Senha com chars especiais → curl `--user` (Task 6)
- ✅ Repo de RPM compromised → SHA256 verification (Tasks 5, 9, 10)
- ✅ Falha silenciosa → `set -euo pipefail` (Tasks 7, 10)
- ✅ Operador vendo "Hint:admin/Utm_12345" → removido (Task 10)

Items deliberately out of scope:
- Stack modernization (Grafana 12, InfluxDB 3, Telegraf 1.38) — separate project per Non-Goals
- Cross-distro support (apt, pacman) — RHEL/CentOS only per Non-Goals
- Rewriting in another language — Non-Goal

## Next step (after this plan)

Item #1b da roadmap original — **modernização da stack**. Brainstorm separado, decomposto em sub-projetos: 2a (Grafana 12 no test-env), 2b (migração JSON dashboards), 2c (InfluxDB 1.11 vs 3), 2d (bump real do upgrade consumindo as mudanças desta spec).
