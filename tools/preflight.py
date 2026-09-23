#!/usr/bin/python3
"""Check that this machine can run the UTM collector before anything is changed.

The collector itself is plain Python with no version-sensitive syntax, but its
two dependencies are not equally portable:

  ucsmsdk  - pure Python, no known upper bound
  netmiko  - versions below 4.4.0 import the stdlib `telnetlib`, which Python
             3.13 removed. netmiko 4.4.0 vendors it as netmiko._telnetlib.
             The project's ansible playbook pins netmiko==4.0.0, so a host on
             a modern Python that followed the playbook cannot even import the
             collector: it dies at startup with ModuleNotFoundError, producing
             no metrics at all.

Run this first. It changes nothing.

    python3 tools/preflight.py

Exits 0 when the host can run the collector, 1 when it cannot.
"""

# Kept runnable on Python 3.6 through at least 3.14 so it can diagnose any host.
from __future__ import print_function

import os
import sys

# netmiko below this vendors nothing and needs the stdlib telnetlib
NETMIKO_MIN_ON_PY313 = (4, 4, 0)


def parse_version(raw):
    parts = []
    for chunk in str(raw).split(".")[:3]:
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def check(label, fn):
    try:
        ok, detail = fn()
    except Exception as exc:                                  # noqa: BLE001
        ok, detail = False, "{}: {}".format(type(exc).__name__, exc)
    print("  [{}] {:<22} {}".format("OK" if ok else "!!", label, detail))
    return ok


def check_python():
    v = sys.version_info
    detail = "{}.{}.{} ({})".format(v[0], v[1], v[2], sys.executable)
    return v[0] == 3 and v >= (3, 6), detail


def check_ucsmsdk():
    import ucsmsdk
    from ucsmsdk.ucshandle import UcsHandle                   # noqa: F401
    return True, getattr(ucsmsdk, "__version__", "version unknown")


def check_netmiko():
    import netmiko
    from netmiko import ConnectHandler                        # noqa: F401
    raw = getattr(netmiko, "__version__", "0")
    if sys.version_info >= (3, 13) and parse_version(raw) < NETMIKO_MIN_ON_PY313:
        return False, "{} — needs >= {} on Python 3.13+".format(
            raw, ".".join(str(n) for n in NETMIKO_MIN_ON_PY313))
    return True, raw


def check_collector_syntax():
    import ast

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), "telegraf", "ucs_traffic_monitor.py")
    if not os.path.exists(path):
        path = os.path.join(here, "ucs_traffic_monitor.py")
    if not os.path.exists(path):
        return False, "ucs_traffic_monitor.py not found next to tools/"

    with open(path) as handle:
        ast.parse(handle.read(), filename=path)
    return True, path


def main():
    print("UTM preflight")
    print("-" * 60)
    results = [
        check("python", check_python),
        check("ucsmsdk", check_ucsmsdk),
        check("netmiko", check_netmiko),
        check("collector syntax", check_collector_syntax),
    ]
    print("-" * 60)

    if all(results):
        print("Host can run the collector. Continue with the validation steps.")
        return 0

    print("Host CANNOT run the collector as is.")
    if sys.version_info >= (3, 13):
        print("")
        print("If netmiko is the failing line, this fixes it:")
        print("    python3 -m pip install -U 'netmiko>=4.4.0'")
        print("")
        print("The ansible playbook in this repo pins netmiko==4.0.0, which")
        print("cannot import on Python 3.13+. That pin needs updating too.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
