#!/usr/bin/python3
"""Regression tests for the five quick fixes (RFC 2026-09-20, section 9).

These import the real telegraf/ucs_traffic_monitor.py and exercise the fixed
code paths. ucsmsdk and netmiko are stubbed, so no UCS and no third-party
package is needed.

Runs standalone or under pytest:
    python3 tests/test_quick_fixes.py
    pytest tests/test_quick_fixes.py
"""

# Kept compatible with Python 3.6, the CentOS 7 UTM VM's interpreter.
import importlib.util
import io
import os
import pickle
import stat
import sys
import tempfile
import types
from contextlib import redirect_stdout
from pathlib import Path

# The suite is pointed at production collectors too; importing one must not
# leave a __pycache__ directory behind in the production directory.
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parent.parent
# UTM_COLLECTOR points the suite at another copy of the collector, which is
# how these tests are checked against the pre-fix code: they must fail there.
COLLECTOR = Path(os.environ.get(
    "UTM_COLLECTOR", REPO_ROOT / "telegraf" / "ucs_traffic_monitor.py"))


def _load_collector():
    """Import the collector with its UCS dependencies stubbed out."""
    for name, attr in (("ucsmsdk", None),
                       ("ucsmsdk.ucshandle", "UcsHandle"),
                       ("netmiko", "ConnectHandler")):
        if name in sys.modules:
            continue
        module = types.ModuleType(name)
        if attr:
            setattr(module, attr, object)
        sys.modules[name] = module

    if not COLLECTOR.is_file():
        raise SystemExit(
            "collector not found: {}\n"
            "set UTM_COLLECTOR=/path/to/ucs_traffic_monitor.py".format(COLLECTOR))

    # The env-mode collector does `import credentials`, which lives next to it
    sys.path.insert(0, str(COLLECTOR.parent))

    spec = importlib.util.spec_from_file_location("utm_under_test", COLLECTOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


utm = _load_collector()


def _reset_state():
    """Clear the collector's module-level state between tests."""
    for name in ("stats_dict", "domain_dict", "conn_dict",
                 "raw_sdk_stats", "raw_cli_stats", "pickled_connections"):
        getattr(utm, name).clear()
    utm.user_args.clear()


def _minimal_domain(fex_peer_type="S-rack", with_rack_unit=False):
    """Smallest stats_dict that reaches the FEX backplane branch of the output."""
    fi = {
        "load": "1", "total_memory": "1", "mem_available": "1",
        "model": "UCS-FI-6454", "serial": "SAL0000", "oob_if_ip": "10.0.0.2",
        "fi_fw_sys_ver": "4.2(3d)", "ha_ready": "yes", "leadership": "primary",
        "fi_ports": {},
    }
    domain = {
        "location": "DC1", "mode": "cluster", "name": "utm-lab", "uptime": 1,
        "ucsm_fw_ver": "4.2(3d)",
        "A": dict(fi), "B": dict(fi),
        "chassis": {}, "ru": {}, "fex": {
            "fex-3": {"bp_ports": {"1": {"01": {
                "fi_id": "A",
                "peer_type": fex_peer_type,
                "peer": "rack-unit-5",
                "peer_port": "1/1",
                "oper_state": "up",
                "oper_speed": 40,
            }}}}
        },
    }
    if with_rack_unit:
        # Full key set, because the rack unit loop runs before the FEX loop
        # and feeds influxdb_lp_server_fields()
        domain["ru"] = {"rack-unit-5": {
            "service_profile": "SP-ESX-05",
            "admin_state": "in-service", "association": "associated",
            "operability": "operable", "oper_state": "ok",
            "oper_state_code": 0, "memory": "262144",
            "model": "UCSC-C220-M5SX", "num_adaptors": "1",
            "num_cores": "32", "num_cpus": "2",
            "num_vEths": "2", "num_vFCs": "2", "serial": "WZP0000",
            "adaptors": {},
        }}
    return domain


# --------------------------------------------------------------------------
# F5 — leaked loop variable in print_output_in_influxdb_lp()  (:2793)
# --------------------------------------------------------------------------
def test_f5_fex_peer_without_rack_units_still_emits_output():
    """Blade-only domain plus a FEX with a rack peer used to raise
    UnboundLocalError, which dropped the whole run's output."""
    _reset_state()
    utm.user_args.update(output_format="influxdb-lp", verify_only=False)
    utm.stats_dict["10.0.0.1"] = _minimal_domain(with_rack_unit=False)

    captured = io.StringIO()
    with redirect_stdout(captured):
        utm.print_output_in_influxdb_lp()

    output = captured.getvalue()
    assert "FIEnvStats" in output, "run produced no output at all"
    assert "BackplanePortStats" in output, "FEX backplane line missing"
    # No peer in ru_dict, so the tag must simply be absent - not a crash
    assert "peer_service_profile" not in output


def test_f5_fex_peer_with_rack_unit_emits_peer_service_profile():
    """When the peer IS in ru_dict the tag must appear. Before the fix the
    lookup hit the leaked loop variable and silently never matched."""
    _reset_state()
    utm.user_args.update(output_format="influxdb-lp", verify_only=False)
    utm.stats_dict["10.0.0.1"] = _minimal_domain(with_rack_unit=True)

    captured = io.StringIO()
    with redirect_stdout(captured):
        utm.print_output_in_influxdb_lp()

    assert "peer_service_profile=SP-ESX-05" in captured.getvalue()


# --------------------------------------------------------------------------
# F11 — cleanup_ucs_connections() with --no-ssh or a failed login  (:607)
# --------------------------------------------------------------------------
class _FakeHandle:
    def __init__(self):
        self.closed = False

    def disconnect(self):
        self.closed = True

    def logout(self):
        self.closed = True


class _RaisingHandle:
    def disconnect(self):
        raise OSError("socket already gone")

    def logout(self):
        raise OSError("socket already gone")


def _run_cleanup(conn_dict):
    _reset_state()
    utm.user_args.update(output_format="influxdb-lp")
    utm.conn_dict.update(conn_dict)
    with tempfile.TemporaryDirectory() as tmp:
        original_prefix = utm.FILENAME_PREFIX
        utm.FILENAME_PREFIX = str(Path(tmp) / "utm")
        try:
            utm.cleanup_ucs_connections()
        finally:
            utm.FILENAME_PREFIX = original_prefix


def test_f11_missing_cli_key_does_not_raise():
    """--no-ssh returns before setting conn_dict[ip]['cli'] -> used to KeyError."""
    sdk = _FakeHandle()
    _run_cleanup({"10.0.0.1": {"sdk": sdk}})
    assert sdk.closed, "SDK session was not logged out"


def test_f11_none_handles_do_not_raise():
    """A failed login leaves None handles -> used to AttributeError."""
    _run_cleanup({"10.0.0.1": {"cli": None, "sdk": None}})


def test_f11_one_broken_handle_does_not_block_the_others():
    """A domain whose disconnect raises must not strand the other domains."""
    healthy = _FakeHandle()
    _run_cleanup({
        "10.0.0.1": {"cli": _RaisingHandle(), "sdk": _RaisingHandle()},
        "10.0.0.2": {"cli": healthy, "sdk": _FakeHandle()},
    })
    assert healthy.closed, "second domain was skipped after the first raised"


# --------------------------------------------------------------------------
# F1/F2 — pickle file permissions and refusal to load an unsafe file
# --------------------------------------------------------------------------
def test_f1_pickle_file_is_created_owner_only():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "sessions.pickle"
        handle = utm.open_pickle_file_for_write(str(target))
        assert handle is not None
        pickle.dump({"x": 1}, handle)
        handle.close()

        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600, f"expected 0600, got {mode:o}"


def test_f1_existing_loose_file_is_tightened():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "sessions.pickle"
        target.write_bytes(b"old")
        target.chmod(0o644)

        handle = utm.open_pickle_file_for_write(str(target))
        assert handle is not None
        handle.close()

        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600, f"loose file kept mode {mode:o}"


def test_f2_group_writable_pickle_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "sessions.pickle"
        target.write_bytes(pickle.dumps({}))
        target.chmod(0o660)
        assert utm.pickle_file_is_safe_to_load(str(target)) is False


def test_f2_owner_only_pickle_is_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "sessions.pickle"
        target.write_bytes(pickle.dumps({}))
        target.chmod(0o600)
        assert utm.pickle_file_is_safe_to_load(str(target)) is True


def test_f2_missing_pickle_is_treated_as_first_run():
    assert utm.pickle_file_is_safe_to_load("/nonexistent/utm.pickle") is True


# --------------------------------------------------------------------------
# F4 — health line is emitted even when the run failed
# --------------------------------------------------------------------------
def _health_output(*, output_ok, sdk, cli, no_ssh=False):
    _reset_state()
    utm.user_args.update(output_format="influxdb-lp", verify_only=False,
                         no_ssh=no_ssh)
    utm.domain_dict["10.0.0.1"] = ["user", "pass"]
    if sdk:
        utm.raw_sdk_stats["10.0.0.1"] = {"TopSystem": ["mo"]}
    if cli:
        utm.raw_cli_stats["10.0.0.1"] = {"A": {"pfc_stats": "..."}}

    captured = io.StringIO()
    with redirect_stdout(captured):
        utm.print_collector_health(output_ok, 12.5)
    return captured.getvalue()


def test_f4_healthy_run_reports_success():
    line = _health_output(output_ok=True, sdk=True, cli=True)
    assert "UTMCollectorHealth,domain=10.0.0.1" in line
    assert "success=1i" in line
    assert line.endswith("\n")


def test_f4_failed_collection_reports_failure():
    """The whole point: a failed run must still produce a line saying so."""
    line = _health_output(output_ok=True, sdk=False, cli=False)
    assert "success=0i" in line
    assert "sdk_ok=0i" in line


def test_f4_failed_output_reports_failure():
    line = _health_output(output_ok=False, sdk=True, cli=True)
    assert "success=0i" in line
    assert "output_ok=0i" in line


def test_f4_no_ssh_does_not_count_as_a_cli_failure():
    line = _health_output(output_ok=True, sdk=True, cli=False, no_ssh=True)
    assert "success=1i" in line
    assert "cli_skipped=1i" in line


def test_f4_is_silent_for_the_dict_output_format():
    _reset_state()
    utm.user_args.update(output_format="dict", verify_only=False)
    utm.domain_dict["10.0.0.1"] = ["user", "pass"]
    captured = io.StringIO()
    with redirect_stdout(captured):
        utm.print_collector_health(True, 1.0)
    assert captured.getvalue() == ""


def test_f4_emits_one_line_per_domain():
    _reset_state()
    utm.user_args.update(output_format="influxdb-lp", verify_only=False,
                         no_ssh=True)
    utm.domain_dict.update({"10.0.0.1": ["u", "p"], "10.0.0.2": ["u", "p"]})
    utm.raw_sdk_stats["10.0.0.1"] = {"TopSystem": ["mo"]}

    captured = io.StringIO()
    with redirect_stdout(captured):
        utm.print_collector_health(True, 1.0)

    lines = captured.getvalue().strip().splitlines()
    assert len(lines) == 2, f"expected 2 lines, got {len(lines)}"
    assert "domain=10.0.0.1 success=1i" in lines[0]
    assert "domain=10.0.0.2 success=0i" in lines[1]


def main():
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = []
    for name, test in tests:
        try:
            test()
        except Exception as exc:
            failed.append(name)
            print(f"FAIL  {name}\n        {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {name}")

    print(f"\n{len(tests) - len(failed)}/{len(tests)} passaram")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
