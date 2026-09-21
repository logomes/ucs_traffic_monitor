#!/usr/bin/python3
"""Audit the three intervals that must agree for UTM bandwidth to be correct.

UTM does not compute a rate. It exports `bytes_rx_delta` / `total_bytes_delta`
exactly as UCSM reports them, and UCSM computes those deltas over the
interval of its own stats collection policy. The conversion to a rate happens
only in Grafana, which divides by the dashboard constant [[polling_interval]].

So a bandwidth figure is only correct when all three agree:

    UCSM stats collection policy interval        (set per stat type in UCSM)
        == telegraf inputs.exec interval          (set in telegraf.conf)
        == Grafana [[polling_interval]] variable  (set in each dashboard)

Nothing validates that today. If the port policy sits at 2 minutes while
[[polling_interval]] is 60, every uplink bandwidth panel reads 2x high, with
no error anywhere. This tool reports the three values side by side.

The stat types UTM actually reads are port (FI ports), adapter (vNIC/vHBA)
and chassis (backplane ports).

Usage:
    ./audit_stats_interval.py -i ucs_domains_group_1.txt \
                              -t /etc/telegraf/telegraf.conf \
                              -d ../grafana/dashboards/domain_traffic.json

    ./audit_stats_interval.py -i ucs_domains_group_1.txt --no-ucs   # offline

Exits 0 when the intervals agree, 1 when they diverge, 2 on an error.
"""

# Kept compatible with Python 3.6, which is what the CentOS 7 UTM VM ships:
# no PEP 604 unions and no `from __future__ import annotations`.
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Stat types whose deltas UTM exports. Others are collected by UCSM but
# unused here, so a mismatch on them does not skew any UTM panel.
STAT_TYPES_USED_BY_UTM = ("port", "adapter", "chassis")

# StatsCollectionPolicyConsts.COLLECTION_INTERVAL_* -> seconds
INTERVAL_SECONDS = {
    "30seconds": 30,
    "1minute": 60,
    "2minutes": 120,
    "5minutes": 300,
}


def parse_domains(input_file):
    # type: (Path) -> List[Tuple[str, str, str]]
    """Read the UTM input file: IP,user,password per line, [Location] headers."""
    domains = []
    for raw_line in input_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        parts = line.split(",")
        if len(parts) < 3:
            print(f"  ! ignoring malformed line: {raw_line!r}", file=sys.stderr)
            continue
        domains.append((parts[0], parts[1], parts[2]))
    return domains


def telegraf_exec_interval(telegraf_conf):
    # type: (Path) -> Optional[int]
    """Pull the interval of the inputs.exec block that runs this collector."""
    try:
        text = telegraf_conf.read_text()
    except OSError as exc:
        print(f"  ! cannot read {telegraf_conf}: {exc}", file=sys.stderr)
        return None

    # Only look at inputs.exec blocks that actually invoke UTM
    blocks = re.split(r"^\s*\[\[", text, flags=re.MULTILINE)
    for block in blocks:
        if not block.startswith("inputs.exec"):
            continue
        if "ucs_traffic_monitor" not in block:
            continue
        match = re.search(r'^\s*interval\s*=\s*"(\d+)([smh])"',
                          block, flags=re.MULTILINE)
        if match:
            value, unit = int(match.group(1)), match.group(2)
            return value * {"s": 1, "m": 60, "h": 3600}[unit]
    return None


def dashboard_polling_interval(dashboard_json):
    # type: (Path) -> Optional[int]
    """Read the [[polling_interval]] template variable out of a dashboard."""
    try:
        dashboard = json.loads(dashboard_json.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ! cannot read {dashboard_json}: {exc}", file=sys.stderr)
        return None

    for variable in dashboard.get("templating", {}).get("list", []):
        if variable.get("name") != "polling_interval":
            continue

        # UTM declares it as a constant variable, which carries its value in
        # "query". Fall back to "current" for the other variable types.
        candidates = [variable.get("query")]
        current = variable.get("current")
        if isinstance(current, dict):
            candidates += [current.get("value"), current.get("text")]

        for value in candidates:
            if isinstance(value, list):
                value = value[0] if value else None
            if value is None or value == "":
                continue
            try:
                # Some dashboards store it as "60", others as "60.0"
                seconds = float(str(value))
            except (TypeError, ValueError):
                continue
            if seconds != int(seconds):
                print(f"  ! polling_interval is fractional ({seconds}) in "
                      f"{dashboard_json.name}", file=sys.stderr)
            return int(seconds)

        print(f"  ! polling_interval found but not numeric in "
              f"{dashboard_json.name}", file=sys.stderr)
        return None
    return None


def ucsm_policy_intervals(host, user, password):
    # type: (str, str, str) -> Dict[str, str]
    """Query StatsCollectionPolicy from a UCS domain. Returns name -> interval."""
    from ucsmsdk.ucshandle import UcsHandle

    handle = UcsHandle(host, user, password)
    handle.login(timeout=30)
    try:
        policies = handle.query_classid("StatsCollectionPolicy")
        return {policy.name: policy.collection_interval for policy in policies}
    finally:
        handle.logout()


def report_domain(host, policies, telegraf_s, dashboard_s):
    # type: (str, Dict[str, str], Optional[int], Optional[int]) -> bool
    """Print one domain's comparison. Returns True when everything agrees."""
    print(f"\n{host}")
    print(f"  {'stat type':<10} {'UCSM policy':<14} {'telegraf':<10} "
          f"{'dashboard':<10} verdict")
    print(f"  {'-' * 62}")

    agreed = True
    for stat_type in STAT_TYPES_USED_BY_UTM:
        raw = policies.get(stat_type)
        if raw is None:
            print(f"  {stat_type:<10} {'not found':<14} "
                  f"{'-':<10} {'-':<10} UNKNOWN")
            agreed = False
            continue

        ucsm_s = INTERVAL_SECONDS.get(raw)
        if ucsm_s is None:
            print(f"  {stat_type:<10} {raw:<14} {'-':<10} {'-':<10} "
                  f"UNKNOWN INTERVAL")
            agreed = False
            continue

        values = [v for v in (ucsm_s, telegraf_s, dashboard_s) if v is not None]
        if len(values) < 2:
            verdict = "INCOMPLETE"
            agreed = False
        elif len(set(values)) == 1:
            verdict = "ok"
        else:
            verdict = "MISMATCH"
            agreed = False
            if dashboard_s and ucsm_s != dashboard_s:
                factor = ucsm_s / dashboard_s
                verdict += f"  (panels read {factor:.3g}x off)"

        print(f"  {stat_type:<10} {f'{raw} ({ucsm_s}s)':<14} "
              f"{str(telegraf_s) + 's' if telegraf_s else '?':<10} "
              f"{str(dashboard_s) + 's' if dashboard_s else '?':<10} {verdict}")

    return agreed


def main():
    # type: () -> int
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-i", "--input-file", type=Path, required=True,
                        help="UTM input file (ucs_domains_group_*.txt)")
    parser.add_argument("-t", "--telegraf-conf", type=Path,
                        default=Path("/etc/telegraf/telegraf.conf"),
                        help="telegraf.conf holding the inputs.exec block")
    parser.add_argument("-d", "--dashboard", type=Path,
                        help="dashboard JSON carrying [[polling_interval]]")
    parser.add_argument("--no-ucs", action="store_true",
                        help="skip the UCS queries, report the local side only")
    args = parser.parse_args()

    try:
        domains = parse_domains(args.input_file)
    except OSError as exc:
        print(f"cannot read {args.input_file}: {exc}", file=sys.stderr)
        return 2

    if not domains:
        print(f"no domains in {args.input_file}", file=sys.stderr)
        return 2

    telegraf_s = telegraf_exec_interval(args.telegraf_conf)
    dashboard_s = (dashboard_polling_interval(args.dashboard)
                   if args.dashboard else None)

    print(f"telegraf inputs.exec interval : "
          f"{f'{telegraf_s}s' if telegraf_s else 'not found'}")
    print(f"dashboard [[polling_interval]]: "
          f"{f'{dashboard_s}s' if dashboard_s else 'not checked'}")

    if args.no_ucs:
        print("\n--no-ucs: skipping the UCSM side. Run without it for the "
              "verdict that matters.")
        return 0

    all_agreed = True
    for host, user, password in domains:
        try:
            policies = ucsm_policy_intervals(host, user, password)
        except Exception as exc:
            print(f"\n{host}\n  ! query failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            all_agreed = False
            continue
        if not report_domain(host, policies, telegraf_s, dashboard_s):
            all_agreed = False

    if all_agreed:
        print("\nAll intervals agree. Bandwidth figures are on the right scale.")
        return 0

    print("\nIntervals diverge. Until they match, bandwidth panels are off by "
          "the ratio shown above.\nFix by aligning the UCSM policy to the "
          "scrape interval, or by setting [[polling_interval]] to the UCSM "
          "value.\nThe durable fix is F6 in the RFC: read timeCollected / "
          "intervals in the collector\nand export a real rate, so no dashboard "
          "constant is involved.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
