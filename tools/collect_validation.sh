#!/usr/bin/env bash
# Collect everything needed to validate the UTM quick fixes on this host,
# in the right order, into one report to paste back for analysis.
#
#     sudo ./tools/collect_validation.sh
#     less /tmp/utm-validacao/relatorio.txt
#
# Read-only for production: it never writes under UTM_DIR, never edits
# telegraf.conf and never restarts a service. Everything it runs lands in OUT.
# The before/after comparison runs copies of both collectors, as the telegraf
# user, with their own instance name, so they cannot touch the production
# pickle or log file.
#
# Works with both credential modes and detects which one production uses:
#   file mode  upstream / master: ucs_domains_group_*.txt
#   env  mode  feat/credentials-env-vars and later: /etc/utm/creds.env
#
# Everything is auto-detected from telegraf.conf; override when needed:
#   UTM_DIR        where production ucs_traffic_monitor.py lives
#   PY             interpreter telegraf runs the collector with
#   TG_USER        user telegraf runs as
#   CREDS_FILE     env mode credentials       (default /etc/utm/creds.env)
#   GRP            file mode domains file     (default: from telegraf.conf)
#   TELEGRAF_CONF  colon-separated configs/dirs (default telegraf.conf:telegraf.d)
#   DASHBOARD      dashboard JSON with [[polling_interval]]
#   OUT            output directory           (default /tmp/utm-validacao)
#   MASCARAR=0     keep IP addresses in the report (masked by default)
#   RUN_TIMEOUT    seconds per collector run  (default 180)

set -u

# Python would otherwise cache bytecode next to every module it imports,
# including a production collector.
export PYTHONDONTWRITEBYTECODE=1

PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UTM_DIR="${UTM_DIR:-/usr/local/telegraf}"
CREDS_FILE="${CREDS_FILE:-/etc/utm/creds.env}"
OUT="${OUT:-/tmp/utm-validacao}"
MASCARAR="${MASCARAR:-1}"
RUN_TIMEOUT="${RUN_TIMEOUT:-180}"
TELEGRAF_PATHS=()
IFS=: read -r -a _tg_candidates <<< "${TELEGRAF_CONF:-/etc/telegraf/telegraf.conf:/etc/telegraf/telegraf.d}"
for candidate in "${_tg_candidates[@]}"; do
    [ -e "$candidate" ] && TELEGRAF_PATHS+=("$candidate")
done

PROD_COLLECTOR="$UTM_DIR/ucs_traffic_monitor.py"
REPORT="$OUT/relatorio.txt"

die() { echo "erro: $*" >&2; exit 2; }

[ "$(id -u)" -eq 0 ] || die "rode com sudo: precisa ler o pickle e rodar como o usuario do telegraf"
[ -f "$PROD_COLLECTOR" ] || die "coletor de producao nao encontrado em $PROD_COLLECTOR (ajuste UTM_DIR)"
[ -d "$PKG_DIR/coletor" ] || die "rode a partir do pacote utm-validacao (falta $PKG_DIR/coletor)"

# --- detection ---------------------------------------------------------------

if grep -q '^import credentials' "$PROD_COLLECTOR"; then
    MODE="env"
else
    MODE="file"
fi

# The command telegraf actually runs, from the inputs.exec block
EXEC_LINES=""
if [ "${#TELEGRAF_PATHS[@]}" -gt 0 ]; then
    EXEC_LINES="$(grep -rhoE '"[^"]*ucs_traffic_monitor\.py[^"]*"' "${TELEGRAF_PATHS[@]}" 2>/dev/null | tr -d '"')"
fi
EXEC_COUNT="$(printf '%s\n' "$EXEC_LINES" | grep -c . || true)"
EXEC_CMD="$(printf '%s\n' "$EXEC_LINES" | head -n1)"

if [ -z "${PY:-}" ]; then
    PY="$(printf '%s' "$EXEC_CMD" | awk '{print $1}')"
    [ -n "$PY" ] || PY=python3
fi
PY="$(command -v "$PY" || echo "$PY")"

if [ -z "${GRP:-}" ] && [ "$MODE" = file ]; then
    GRP="$(printf '%s' "$EXEC_CMD" | awk '{for (i = 1; i < NF; i++) if ($i ~ /ucs_traffic_monitor\.py$/) {print $(i + 1); exit}}')"
fi

if [ -z "${TG_USER:-}" ]; then
    TG_USER="$(systemctl show -p User --value telegraf 2>/dev/null || true)"
    if [ -z "$TG_USER" ]; then
        if id telegraf >/dev/null 2>&1; then TG_USER=telegraf; else TG_USER=root; fi
    fi
fi
id "$TG_USER" >/dev/null 2>&1 || die "usuario '$TG_USER' nao existe (ajuste TG_USER)"

if [ -z "${DASHBOARD:-}" ]; then
    for candidate in /var/lib/grafana/dashboards/domain_traffic.json \
                     "$PKG_DIR/grafana/dashboards/domain_traffic.json"; do
        if [ -f "$candidate" ]; then DASHBOARD="$candidate"; break; fi
    done
fi

if [ "$MODE" = env ]; then
    CRED_ARGS=(--env-file "$CREDS_FILE")
else
    CRED_ARGS=(-i "${GRP:-}")
fi

# --- helpers -----------------------------------------------------------------

# Prefix that runs a command as the telegraf user. An array rather than a
# function, because `timeout` can only exec real programs.
if [ "$TG_USER" = root ]; then
    RUNAS=(env)
elif command -v runuser >/dev/null 2>&1; then
    RUNAS=(runuser -u "$TG_USER" --)
else
    RUNAS=(sudo -u "$TG_USER" --)
fi

# Network-facing runs get the proxy settings of the telegraf SERVICE, not of
# this shell: a corporate https_proxy in the admin's environment (on SUSE,
# /etc/sysconfig/proxy) would otherwise route the validation through a proxy
# that production never uses, and make reachable domains look unreachable.
NET_ENV=(env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY
         -u no_proxy -u NO_PROXY -u all_proxy -u ALL_PROXY)
SERVICE_PROXY=""
read -r -a _svc_env <<< "$(systemctl show -p Environment --value telegraf 2>/dev/null || true)"
for kv in ${_svc_env[@]+"${_svc_env[@]}"}; do
    case "$kv" in
        [Hh][Tt][Tt][Pp]_[Pp][Rr][Oo][Xx][Yy]=*|[Hh][Tt][Tt][Pp][Ss]_[Pp][Rr][Oo][Xx][Yy]=*|\
        [Nn][Oo]_[Pp][Rr][Oo][Xx][Yy]=*|[Aa][Ll][Ll]_[Pp][Rr][Oo][Xx][Yy]=*)
            NET_ENV+=("$kv")
            SERVICE_PROXY="${SERVICE_PROXY:+$SERVICE_PROXY }${kv%%=*} (do serviço)"
            ;;
    esac
done

as_tg() { "${RUNAS[@]}" "$@"; }

# as the telegraf user, with the telegraf service's proxy settings
as_tg_net() { "${RUNAS[@]}" "${NET_ENV[@]}" "$@"; }

section() { printf '\n===== %s =====\n' "$*"; }

series_keys() { awk 'NF {print $1}' "$1" | sort -u; }

measurements() { awk -F'[, ]' 'NF {print $1}' "$1" | sort | uniq -c | awk '{printf "%-26s %s\n", $2, $1}'; }

# --- staging: a copy of the package the telegraf user can read ---------------

case "$(basename "$OUT")" in
    *utm*) ;;
    *) die "OUT precisa ter 'utm' no nome (proteção do rm -rf): $OUT" ;;
esac
OUT="${OUT%/}"
case "$PKG_DIR/" in
    "$OUT"/*) die "o pacote está dentro de OUT ($OUT), que é apagado a cada execução; extraia em outro lugar (ex.: ~/utm-validacao) ou defina OUT=" ;;
esac
rm -rf "$OUT"
install -d -m 0750 -o "$TG_USER" "$OUT"
STAGE="$OUT/pkg"
mkdir -p "$STAGE"
cp -r "$PKG_DIR/tools" "$PKG_DIR/tests" "$PKG_DIR/coletor" "$STAGE/"
chown -R "$TG_USER" "$STAGE"
NEW_COLLECTOR="$STAGE/coletor/modo-$MODE/ucs_traffic_monitor.py"
[ -f "$NEW_COLLECTOR" ] || die "variante modo-$MODE ausente no pacote"
# The suite imports the collector under test (and its credentials.py); a
# copy keeps that import from touching anything under UTM_DIR.
mkdir -p "$STAGE/producao"
cp "$PROD_COLLECTOR" "$STAGE/producao/"
[ -f "$UTM_DIR/credentials.py" ] && cp "$UTM_DIR/credentials.py" "$STAGE/producao/"
PROD_COPY="$STAGE/producao/ucs_traffic_monitor.py"

PREFLIGHT_RC=1
PROD_TESTS="?"
NEW_TESTS="?"
PICKLE_RC="?"
AUDIT_RC="?"
RUN_SUMMARY="pulado"

{
section "0. contexto"
echo "data            : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
# shellcheck source=/dev/null
echo "sistema         : $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
echo "python          : $PY ($("$PY" --version 2>&1))"
echo "telegraf        : $(telegraf --version 2>/dev/null | head -n1)"
echo "usuario telegraf: $TG_USER"
echo "modo credencial : $MODE"
echo "coletor produção: $PROD_COLLECTOR"
echo "blocos exec UTM : $EXEC_COUNT"
echo "proxy na coleta : ${SERVICE_PROXY:-nenhum (o serviço telegraf não define; o do shell foi removido)}"
if [ "$MODE" = env ]; then
    echo "comando telegraf: $EXEC_CMD"
    echo "creds.env       : $(stat -c '%a %U:%G' "$CREDS_FILE" 2>&1)"
else
    echo "comando telegraf: $EXEC_CMD"
    echo "arquivo domínios: ${GRP:-não encontrado} ($(stat -c '%a %U:%G' "${GRP:-/nonexistent}" 2>&1))"
fi
[ "$EXEC_COUNT" -gt 1 ] && echo "aviso           : mais de um bloco exec do UTM; validando o primeiro"

section "1. preflight (como $TG_USER, com o python do telegraf)"
as_tg env UTM_COLLECTOR="$NEW_COLLECTOR" "$PY" "$STAGE/tools/preflight.py"
PREFLIGHT_RC=$?

section "2. integridade do pacote"
if [ -f "$PKG_DIR/MANIFEST.sha256" ]; then
    (cd "$PKG_DIR" && sha256sum -c --quiet MANIFEST.sha256 && echo "todos os arquivos conferem")
else
    echo "sem MANIFEST.sha256 (rodando fora do pacote?)"
fi

section "3. testes contra o coletor de PRODUÇÃO (esperado: 0/16)"
env UTM_COLLECTOR="$PROD_COPY" "$PY" "$STAGE/tests/test_quick_fixes.py" \
    > "$OUT/tests_producao.txt" 2>&1
grep -E '^(ok|FAIL) |^ {8}[A-Za-z]+(Error|Exception)' "$OUT/tests_producao.txt"
PROD_TESTS="$(tail -n1 "$OUT/tests_producao.txt")"
echo "$PROD_TESTS"

section "4. testes contra o coletor NOVO (esperado: 16/16)"
env UTM_COLLECTOR="$NEW_COLLECTOR" "$PY" "$STAGE/tests/test_quick_fixes.py" \
    > "$OUT/tests_novo.txt" 2>&1
grep -E '^FAIL ' "$OUT/tests_novo.txt"
NEW_TESTS="$(tail -n1 "$OUT/tests_novo.txt")"
echo "$NEW_TESTS"

section "5. F1 — senha em texto claro no .pickle?"
shopt -s nullglob
PICKLES=("$UTM_DIR"/*.pickle)
shopt -u nullglob
if [ "${#PICKLES[@]}" -eq 0 ]; then
    echo "nenhum .pickle em $UTM_DIR (o coletor grava ao lado de si mesmo)"
    PICKLE_RC=none
else
    as_tg "$PY" "$STAGE/tools/check_pickle_exposure.py" "${CRED_ARGS[@]}" "${PICKLES[@]}"
    PICKLE_RC=$?
fi

section "6. F6 — intervalos, lado local"
TG_ARGS=()
for path in ${TELEGRAF_PATHS[@]+"${TELEGRAF_PATHS[@]}"}; do TG_ARGS+=(-t "$path"); done
DASH_ARGS=()
[ -n "${DASHBOARD:-}" ] && DASH_ARGS=(-d "$DASHBOARD")
"$PY" "$STAGE/tools/audit_stats_interval.py" --no-ucs ${TG_ARGS[@]+"${TG_ARGS[@]}"} ${DASH_ARGS[@]+"${DASH_ARGS[@]}"}

section "7. F6 — intervalos, lado UCSM"
as_tg_net "$PY" "$STAGE/tools/audit_stats_interval.py" "${CRED_ARGS[@]}" ${TG_ARGS[@]+"${TG_ARGS[@]}"} ${DASH_ARGS[@]+"${DASH_ARGS[@]}"}
AUDIT_RC=$?
echo "exit=$AUDIT_RC  (0 = batem, 1 = divergem, 2 = não verificado)"

section "8. saída antes x depois (cópias isoladas, como $TG_USER)"
if [ "$PREFLIGHT_RC" -ne 0 ]; then
    echo "pulado: o preflight falhou, o coletor não roda neste host como está."
else
    RUN="$OUT/run"
    for side in antes depois; do mkdir -p "$RUN/$side"; done
    cp "$PROD_COLLECTOR" "$RUN/antes/ucs_traffic_monitor.py"
    cp "$NEW_COLLECTOR" "$RUN/depois/ucs_traffic_monitor.py"
    if [ "$MODE" = env ]; then
        cp "$UTM_DIR/credentials.py" "$RUN/antes/"
        cp "$STAGE/coletor/modo-env/credentials.py" "$RUN/depois/"
    else
        install -m 0600 -o "$TG_USER" "$GRP" "$RUN/validacao_grp.txt"
    fi
    chown -R "$TG_USER" "$RUN"

    for side in antes depois; do
        collector="$RUN/$side/ucs_traffic_monitor.py"
        if [ "$MODE" = env ]; then
            timeout "$RUN_TIMEOUT" "${RUNAS[@]}" "${NET_ENV[@]}" \
                "$PY" "$STAGE/tools/credsource.py" exec "$CREDS_FILE" -- \
                "$PY" "$collector" influxdb-lp --instance-name "validacao_$side" -dss \
                > "$RUN/$side.lp" 2> "$RUN/$side.err"
        else
            timeout "$RUN_TIMEOUT" "${RUNAS[@]}" "${NET_ENV[@]}" "$PY" "$collector" "$RUN/validacao_grp.txt" \
                influxdb-lp -dss > "$RUN/$side.lp" 2> "$RUN/$side.err"
        fi
        rc=$?
        lines="$(grep -c . "$RUN/$side.lp")"
        echo "$side: exit=$rc linhas=$lines"
        if [ "$side" = antes ]; then
            RC_antes=$rc; LINES_antes=$lines
        else
            RC_depois=$rc; LINES_depois=$lines
        fi
    done

    echo
    echo "--- linhas por medição (antes | depois) ---"
    join -a1 -a2 -e 0 -o 0,1.2,2.2 \
        <(measurements "$RUN/antes.lp" | sort) <(measurements "$RUN/depois.lp" | sort) \
        | awk '{printf "  %-26s %6s | %s\n", $1, $2, $3}'

    echo
    echo "--- séries só no depois (primeiras 10) ---"
    comm -13 <(series_keys "$RUN/antes.lp") <(series_keys "$RUN/depois.lp") | head -n 10
    echo "--- séries só no antes (primeiras 10) ---"
    comm -23 <(series_keys "$RUN/antes.lp") <(series_keys "$RUN/depois.lp") | head -n 10

    echo
    echo "--- F3: linhas malformadas (antes) ---"
    "$PY" "$STAGE/tools/lp_lint.py" "$RUN/antes.lp" | tee "$RUN/lint_antes.txt"
    echo "--- F3: linhas malformadas (depois) ---"
    "$PY" "$STAGE/tools/lp_lint.py" "$RUN/depois.lp" | tee "$RUN/lint_depois.txt"
    bad_antes="$(awk '/malformed:/ {print $NF; exit}' "$RUN/lint_antes.txt")"
    bad_depois="$(awk '/malformed:/ {print $NF; exit}' "$RUN/lint_depois.txt")"
    RUN_SUMMARY="linhas ${LINES_antes:-?} -> ${LINES_depois:-?}, malformadas ${bad_antes:-?} -> ${bad_depois:-?}, exit ${RC_antes:-?} -> ${RC_depois:-?}"

    echo
    echo "--- F4: saúde da coleta (depois) ---"
    grep '^UTMCollectorHealth' "$RUN/depois.lp" || echo "nenhuma linha UTMCollectorHealth"

    echo
    echo "--- logs criados pelas execuções de validação (pode apagar) ---"
    ls -1 /var/log/telegraf/ucs_traffic_monitor/*validacao* 2>/dev/null || echo "  nenhum"

    for side in antes depois; do
        if [ -s "$RUN/$side.err" ]; then
            echo
            echo "--- stderr $side (últimas 8 linhas) ---"
            tail -n 8 "$RUN/$side.err"
        fi
    done
fi

section "9. resumo"
printf '  %-34s %s\n' \
    "preflight"                        "$([ "$PREFLIGHT_RC" -eq 0 ] && echo OK || echo FALHOU)" \
    "testes x produção (esperado 0/16)" "$PROD_TESTS" \
    "testes x novo     (esperado 16/16)" "$NEW_TESTS" \
    "senha em claro no pickle"          "$(case "$PICKLE_RC" in 1) echo SIM;; 0) echo não;; none) echo "sem .pickle";; *) echo "erro ($PICKLE_RC)";; esac)" \
    "saída antes -> depois"             "$RUN_SUMMARY" \
    "intervalos UCSM/telegraf/dash"     "$(case "$AUDIT_RC" in 0) echo batem;; 1) echo DIVERGEM;; 2) echo "não verificado (UCSM inacessível?)";; *) echo "erro ($AUDIT_RC)";; esac)"
} > "$REPORT.raw" 2>&1

# IP addresses become IP-1, IP-2... consistently, so the analysis still works
if [ "$MASCARAR" = 1 ]; then
    "$PY" - "$REPORT.raw" > "$REPORT" <<'PY'
import re
import sys

seen = {}

def mask(match):
    ip = match.group(0)
    if ip not in seen:
        seen[ip] = "IP-{}".format(len(seen) + 1)
    return seen[ip]

with open(sys.argv[1]) as handle:
    sys.stdout.write(re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", mask, handle.read()))
PY
else
    cp "$REPORT.raw" "$REPORT"
fi
rm -f "$REPORT.raw"
chmod 0640 "$REPORT"

echo "relatório: $REPORT"
echo "revise antes de enviar (MASCARAR=$MASCARAR)."
