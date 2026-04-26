"""Synthetic Line Protocol generator for the UTM test environment.

Writes plausible measurements that match the schema produced by the real
ucs_traffic_monitor.py so the existing Grafana dashboards render with
data while no real UCS is connected.

Configuration via env vars (with defaults):
    INTERVAL_SECONDS  10
    DOMAINS           "10.0.0.10,10.0.0.20"  (comma-separated)
    LOCATIONS         "lab,lab"              (parallel to DOMAINS)
    INFLUX_URL        http://influxdb:8086
    INFLUX_DB         utm
"""

from __future__ import annotations

import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Iterator

import requests


@dataclass
class Counter:
    """Monotonic counter that increments by a delta each tick."""
    value: int = 0
    delta_min: int = 100_000
    delta_max: int = 5_000_000

    def tick(self) -> tuple[int, int]:
        delta = random.randint(self.delta_min, self.delta_max)
        self.value += delta
        return self.value, delta


@dataclass
class State:
    """Per-port/per-vnic accumulating state."""
    rx: Counter = field(default_factory=Counter)
    tx: Counter = field(default_factory=Counter)
    rx_pkt: Counter = field(default_factory=lambda: Counter(delta_min=100, delta_max=10_000))
    tx_pkt: Counter = field(default_factory=lambda: Counter(delta_min=100, delta_max=10_000))


def parse_csv_env(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def lp_escape(value: str) -> str:
    """Minimal escaping for Line Protocol tag/field values."""
    return value.replace(" ", "\\ ").replace(",", "\\,")


def emit_line(measurement: str, tags: dict[str, str], fields: dict[str, object]) -> str:
    tag_part = ",".join(f"{k}={lp_escape(v)}" for k, v in tags.items())
    field_parts = []
    for k, v in fields.items():
        if isinstance(v, str):
            field_parts.append(f'{k}="{v}"')
        elif isinstance(v, bool):
            field_parts.append(f"{k}={str(v).lower()}")
        elif isinstance(v, int):
            field_parts.append(f"{k}={v}i")
        else:
            field_parts.append(f"{k}={v}")
    field_part = ",".join(field_parts)
    return f"{measurement},{tag_part} {field_part}"


def generate_lines(
    domains: list[str],
    locations: list[str],
    state: dict[str, State],
    tick_index: int,
) -> Iterator[str]:
    """Yield Line Protocol lines for one tick across all measurements."""
    fi_ids = ["A", "B"]
    server_ports = [f"1/{i}" for i in range(1, 9)]
    uplink_ports = [f"1/{i}" for i in range(13, 17)]
    chassis_ids = ["1", "2"]
    blade_ids = [str(i) for i in range(1, 9)]
    vnic_names = ["eth0", "eth1", "fc0", "fc1"]

    # Sinusoidal load 0.05..0.85 over ~60 ticks
    load_now = 0.45 + 0.4 * math.sin(tick_index / 10.0)
    mem_used_pct = 35.0 + 15.0 * math.sin(tick_index / 7.5)

    for domain, location in zip(domains, locations, strict=True):
        # Servers measurement (used by welcome.json)
        yield emit_line(
            "Servers",
            {"domain": domain, "location": location, "type": "blade"},
            {"total": 16, "associated": 12, "unassociated": 4},
        )
        yield emit_line(
            "Servers",
            {"domain": domain, "location": location, "type": "rack"},
            {"total": 4, "associated": 3, "unassociated": 1},
        )

        for fi_id in fi_ids:
            # FIEnvStats — one line per FI
            yield emit_line(
                "FIEnvStats",
                {"domain": domain, "location": location, "fi_id": fi_id},
                {
                    "load": round(load_now, 3),
                    "total_memory": 8192,
                    "mem_available": int(8192 * (1 - mem_used_pct / 100)),
                    "model": "UCS-FI-6332",
                    "serial": f"FOX{tick_index:04d}-{fi_id}",
                    "oob_if_ip": f"10.0.0.{200 + (0 if fi_id == 'A' else 1)}",
                    "mode": "end-host",
                    "name": f"fi-{fi_id}",
                    "ucsm_fw_ver": "4.2(2c)",
                    "fi_fw_sys_ver": "5.0(3)N2(4.22c)",
                    "ha_ready": "yes",
                    "leadership": "primary" if fi_id == "A" else "subordinate",
                    "sys_uptime": 86400 * 30 + tick_index,
                    "utm_collector_ver": "0.53.0-test",
                },
            )

            # FIServerPortStats — bytes_rx_delta, bytes_tx_delta, pause_rx, pause_tx
            for port in server_ports:
                key = f"{domain}|{fi_id}|server|{port}"
                st = state.setdefault(key, State())
                rx_total, rx_delta = st.rx.tick()
                tx_total, tx_delta = st.tx.tick()
                yield emit_line(
                    "FIServerPortStats",
                    {
                        "domain": domain,
                        "location": location,
                        "fi_id": fi_id,
                        "port": port,
                        "transport": "ethernet",
                        "channel": "single",
                        "peer": f"chassis-{((int(port.split('/')[1]) - 1) % 2) + 1}",
                    },
                    {
                        "bytes_rx_delta": rx_delta,
                        "bytes_tx_delta": tx_delta,
                        "pause_rx": random.randint(0, 2) if random.random() < 0.05 else 0,
                        "pause_tx": random.randint(0, 2) if random.random() < 0.05 else 0,
                    },
                )

            # FIUplinkPortStats — same shape, different ports
            for port in uplink_ports:
                key = f"{domain}|{fi_id}|uplink|{port}"
                st = state.setdefault(key, State())
                rx_total, rx_delta = st.rx.tick()
                tx_total, tx_delta = st.tx.tick()
                yield emit_line(
                    "FIUplinkPortStats",
                    {
                        "domain": domain,
                        "location": location,
                        "fi_id": fi_id,
                        "port": port,
                        "transport": "ethernet",
                        "channel": "single",
                    },
                    {
                        "bytes_rx_delta": rx_delta,
                        "bytes_tx_delta": tx_delta,
                        "pause_rx": 0,
                        "pause_tx": 0,
                    },
                )

            # BackplanePortStats — per-blade
            for chassis in chassis_ids:
                for blade in blade_ids:
                    bp_port = f"{chassis}/{blade}"
                    key = f"{domain}|{fi_id}|bp|{chassis}|{blade}"
                    st = state.setdefault(key, State())
                    rx_total, rx_delta = st.rx.tick()
                    tx_total, tx_delta = st.tx.tick()
                    yield emit_line(
                        "BackplanePortStats",
                        {
                            "domain": domain,
                            "location": location,
                            "fi_id": fi_id,
                            "chassis": chassis,
                            "bp_port": bp_port,
                            "peer_service_profile": f"sp-{chassis}-{blade}",
                        },
                        {
                            "bytes_rx_delta": rx_delta,
                            "bytes_tx_delta": tx_delta,
                            "pause_rx": 0,
                            "pause_tx": 0,
                        },
                    )

        # VnicStats — per-blade per-vnic, no fi_id at this level (it's a tag inside)
        for chassis in chassis_ids:
            for blade in blade_ids:
                for vnic in vnic_names:
                    fi_id = "A" if vnic.endswith("0") else "B"
                    key = f"{domain}|vnic|{chassis}|{blade}|{vnic}"
                    st = state.setdefault(key, State())
                    rx_total, rx_delta = st.rx.tick()
                    tx_total, tx_delta = st.tx.tick()
                    yield emit_line(
                        "VnicStats",
                        {
                            "domain": domain,
                            "location": location,
                            "fi_id": fi_id,
                            "chassis": chassis,
                            "blade": blade,
                            "vif_name": vnic,
                            "service_profile": f"sp-{chassis}-{blade}",
                            "peer_port": f"{chassis}/{blade}",
                        },
                        {
                            "bytes_rx_delta": rx_delta,
                            "bytes_tx_delta": tx_delta,
                        },
                    )

        # BladeServers — slow-changing inventory
        for chassis in chassis_ids:
            for blade in blade_ids:
                yield emit_line(
                    "BladeServers",
                    {
                        "domain": domain,
                        "location": location,
                        "chassis": chassis,
                        "blade": blade,
                        "id": f"{chassis}/{blade}",
                    },
                    {
                        "service_profile": f"sp-{chassis}-{blade}",
                        "operational_state": "ok",
                        "model": "UCSB-B200-M5",
                    },
                )


def write_to_influx(url: str, db: str, lines: list[str]) -> None:
    """POST a batch of Line Protocol to InfluxDB v1 /write endpoint."""
    if not lines:
        return
    payload = "\n".join(lines).encode()
    backoff = 1.0
    for attempt in range(5):
        try:
            resp = requests.post(
                f"{url}/write",
                params={"db": db, "precision": "s"},
                data=payload,
                timeout=5,
            )
            if resp.status_code in (200, 204):
                return
            sys.stderr.write(
                f"InfluxDB write returned {resp.status_code}: {resp.text[:200]}\n"
            )
        except requests.RequestException as exc:
            sys.stderr.write(f"InfluxDB write failed (attempt {attempt + 1}): {exc}\n")
        time.sleep(backoff)
        backoff = min(backoff * 2, 30)
    sys.stderr.write("Giving up on this batch.\n")


def main() -> None:
    interval = int(os.environ.get("INTERVAL_SECONDS", "10"))
    domains = parse_csv_env("DOMAINS", "10.0.0.10,10.0.0.20")
    locations = parse_csv_env("LOCATIONS", ",".join(["lab"] * len(domains)))
    if len(locations) != len(domains):
        sys.stderr.write("LOCATIONS must have the same number of entries as DOMAINS\n")
        sys.exit(2)
    influx_url = os.environ.get("INFLUX_URL", "http://influxdb:8086")
    influx_db = os.environ.get("INFLUX_DB", "utm")

    print(
        f"syn-data: domains={domains} locations={locations} "
        f"interval={interval}s influx={influx_url} db={influx_db}",
        flush=True,
    )

    state: dict[str, State] = {}
    tick = 0
    while True:
        lines = list(generate_lines(domains, locations, state, tick))
        write_to_influx(influx_url, influx_db, lines)
        print(f"tick {tick}: wrote {len(lines)} lines", flush=True)
        tick += 1
        time.sleep(interval)


if __name__ == "__main__":
    main()
