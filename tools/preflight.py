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

import glob
import os
import re
import shlex
import sys

# Importing credentials.py next to a production collector must not leave a
# __pycache__ directory behind there.
sys.dont_write_bytecode = True



def telegraf_configs():
    """TELEGRAF_CONF (colon-separated files or dirs, as in
    collect_validation.sh), else the packaged telegraf locations."""
    entries = (os.environ.get("TELEGRAF_CONF")
               or "/etc/telegraf/telegraf.conf:/etc/telegraf/telegraf.d")
    paths = []
    for entry in entries.split(":"):
        if os.path.isdir(entry):
            paths.extend(sorted(glob.glob(os.path.join(entry, "*.conf"))))
        elif entry:
            paths.append(entry)
    return paths


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


def telegraf_command():
    """The first UTM command in telegraf's config, split into argv, or None."""
    for path in telegraf_configs():
        try:
            with open(path) as handle:
                text = handle.read()
        except (IOError, OSError):
            continue
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            match = re.search(r'"([^"]*ucs_traffic_monitor\.py[^"]*)"', line)
            if match:
                return shlex.split(match.group(1))
    return None


def production_collector():
    argv = telegraf_command()
    if not argv:
        return None
    for arg in argv:
        if arg.endswith("ucs_traffic_monitor.py"):
            return arg
    return None


def find_collector():
    """UTM_COLLECTOR, else the repo layout, else the package variant that
    matches the production collector's credential mode."""
    explicit = os.environ.get("UTM_COLLECTOR")
    if explicit:
        return explicit
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    for candidate in (os.path.join(root, "telegraf", "ucs_traffic_monitor.py"),
                      os.path.join(root, "ucs_traffic_monitor.py")):
        if os.path.exists(candidate):
            return candidate
    production = production_collector()
    if production and os.path.exists(production):
        variant = os.path.join(root, "coletor", "modo-" + collector_mode(production),
                               "ucs_traffic_monitor.py")
        if os.path.exists(variant):
            return variant
    return None


def resolve_interpreter(name):
    if os.sep not in name:
        # telegraf's systemd unit searches the standard PATH, not root's
        for directory in ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin",
                          "/usr/bin", "/sbin", "/bin"):
            candidate = os.path.join(directory, name)
            if os.access(candidate, os.X_OK):
                name = candidate
                break
        else:
            return None
    return os.path.realpath(name)


def check_telegraf_python():
    """This run only means something with the interpreter telegraf uses."""
    argv = telegraf_command()
    if not argv:
        return True, "no UTM inputs.exec found in the telegraf config; not compared"
    telegraf_python = resolve_interpreter(argv[0])
    if telegraf_python is None:
        return False, "telegraf runs '{}', which is not on the standard PATH".format(argv[0])
    if telegraf_python != os.path.realpath(sys.executable):
        return False, "telegraf runs {} -> {}; rerun this with it".format(
            argv[0], telegraf_python)
    return True, "{} (same as this run)".format(argv[0])


def collector_mode(path):
    with open(path) as handle:
        source = handle.read()
    return "env" if "import credentials" in source else "file"


def check_collector_syntax():
    import ast

    path = find_collector()
    if not path or not os.path.exists(path):
        production = production_collector()
        if production and not os.path.exists(production):
            return False, "telegraf points at {}, which does not exist".format(production)
        return False, "collector not found; set UTM_COLLECTOR=/path/to/it"
    with open(path) as handle:
        ast.parse(handle.read(), filename=path)
    return True, "{} ({} mode)".format(path, collector_mode(path))


def check_credentials_module():
    """Env mode only: credentials.py must sit next to the collector."""
    path = find_collector()
    if not path or not os.path.exists(path):
        return False, "skipped: collector not found"
    if collector_mode(path) != "env":
        return True, "not needed (file mode)"
    if sys.version_info < (3, 7):
        return False, "env mode needs Python 3.7+ (project declares 3.10+)"
    sys.path.insert(0, os.path.dirname(path))
    import credentials                                        # noqa: F401
    return True, os.path.join(os.path.dirname(path), "credentials.py")


def main():
    print("UTM preflight")
    print("-" * 60)
    results = [
        check("python", check_python),
        check("telegraf python", check_telegraf_python),
        check("ucsmsdk", check_ucsmsdk),
        check("netmiko", check_netmiko),
        check("collector syntax", check_collector_syntax),
        check("credentials module", check_credentials_module),
    ]
    print("-" * 60)

    if all(results):
        print("Host can run the collector. Continue with the validation steps.")
        return 0

    print("Host CANNOT run the collector as is.")
    print("")
    print("Missing or old ucsmsdk / netmiko for THIS interpreter:")
    print("    {} -m pip install -U ucsmsdk 'netmiko>=4.4.0'".format(sys.executable))
    print("Install them only into the interpreter telegraf runs (line")
    print("'telegraf python'); anything else does not change production.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
