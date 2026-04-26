"""One-shot backfill: emit synthetic Line Protocol with timestamps in the past.

Reuses generate_lines() from generate.py and tags each batch with explicit
nanosecond timestamps stepping back from now. Default: 6 hours of data at
the same interval as the live generator.

Usage (inside the syn-data container):
    HOURS=6 INTERVAL=10 python3 /app/backfill.py
"""

from __future__ import annotations

import os
import sys
import time

import requests

from generate import State, generate_lines, parse_csv_env


def emit_line_with_ts(line: str, ts_ns: int) -> str:
    return f"{line} {ts_ns}"


def main() -> None:
    hours = float(os.environ.get("HOURS", "6"))
    interval = int(os.environ.get("INTERVAL", "10"))
    domains = parse_csv_env("DOMAINS", "10.0.0.10,10.0.0.20")
    locations = parse_csv_env("LOCATIONS", ",".join(["lab"] * len(domains)))
    influx_url = os.environ.get("INFLUX_URL", "http://influxdb:8086")
    influx_db = os.environ.get("INFLUX_DB", "telegraf")
    batch_size = int(os.environ.get("BATCH_SIZE", "5000"))

    total_seconds = int(hours * 3600)
    total_ticks = total_seconds // interval
    now_ns = int(time.time() * 1_000_000_000)
    interval_ns = interval * 1_000_000_000

    print(
        f"backfill: hours={hours} ticks={total_ticks} interval={interval}s "
        f"domains={domains} db={influx_db}"
    )

    state: dict[str, State] = {}
    pending: list[str] = []
    posted = 0

    for i in range(total_ticks):
        # Walk forward in time from (now - total_seconds) to now
        tick_index = i
        ts_ns = now_ns - (total_ticks - 1 - i) * interval_ns

        for line in generate_lines(domains, locations, state, tick_index):
            pending.append(emit_line_with_ts(line, ts_ns))

        if len(pending) >= batch_size:
            _post(influx_url, influx_db, pending)
            posted += len(pending)
            pending = []
            if posted % 50000 == 0:
                print(f"  posted {posted} lines so far...", flush=True)

    if pending:
        _post(influx_url, influx_db, pending)
        posted += len(pending)

    print(f"done: {posted} lines written across {total_ticks} ticks")


def _post(url: str, db: str, lines: list[str]) -> None:
    payload = "\n".join(lines).encode()
    resp = requests.post(
        f"{url}/write",
        params={"db": db, "precision": "ns"},
        data=payload,
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        sys.stderr.write(
            f"InfluxDB write failed {resp.status_code}: {resp.text[:300]}\n"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
