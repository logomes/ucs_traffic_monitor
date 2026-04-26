# UTM Test Environment

Local Docker stack for validating the UTM credentials refactor before
deploying to production. Four containers (InfluxDB 1.11, Telegraf 1.32,
Grafana 11, syn-data Python generator) wired together via Docker Compose.

## Prerequisites

- Docker 24+ with the `compose` plugin (Arch/CachyOS: `sudo pacman -S docker docker-compose`)
- The `docker` daemon enabled and your user in the `docker` group

## Quickstart

```fish
cd test-env
cp .env.example .env
cp creds.env.example creds.env
chmod 600 creds.env
docker compose up -d --build
docker compose logs -f
```

After ~60 seconds:

- InfluxDB: http://localhost:8086 (no auth)
- Grafana: http://localhost:3000 (admin / admin)

## What you can validate

| Question | How |
|---|---|
| Did Grafana provision dashboards? | http://localhost:3000 → folder `UTM` |
| Is synthetic data flowing? | Open dashboard `domain_overview`; panels should show data |
| Did Telegraf load env vars? | `docker compose exec telegraf cat /var/log/telegraf/ucs_traffic_monitor/ucs_traffic_monitor_utm.log \| grep "Added"` |
| Did Telegraf execute the script? | Check the same log for the script's INFO output |

The script is **expected to fail** to reach `10.0.0.99`. That failure
in the log proves the env-var pipeline works end-to-end.

## Switching to a real UCS

1. Edit `creds.env`: replace `UTM_lab1_HOST` with a real UCS IP and
   set real user/password.
2. Stop the synthetic generator:
   ```fish
   docker compose stop syn-data
   ```
3. Restart telegraf so it re-reads `creds.env`:
   ```fish
   docker compose restart telegraf
   ```
4. Within ~60 seconds the script will collect from the real UCS and
   write Line Protocol to InfluxDB.

## Reset

```fish
docker compose down -v   # nukes volumes (InfluxDB data, Grafana state)
docker compose up -d --build
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Error response from daemon: Ports are not available` | Port 3000 or 8086 occupied | Edit `.env`, set `GRAFANA_PORT=3001` (or similar), `docker compose up -d` |
| `permission denied while trying to connect to the Docker daemon socket` | User not in docker group | `sudo usermod -aG docker $USER`, then `newgrp docker` or new terminal |
| Grafana panel: "Panel plugin not found: agenty-flowcharting-panel" | Plugin failed to install (Grafana 11 incompatibility) | Edit dashboard panel to a built-in type, or accept the limitation |
| `docker compose ps` shows `unhealthy` for InfluxDB | InfluxDB still booting | Wait 10–20s and re-check; if persistent, `docker compose logs influxdb` |
| Telegraf log empty / no "Added domain" message | Script fails before logger init | `docker compose logs telegraf \| grep -i "Traceback"` to find Python error |

## Architecture

See `docs/superpowers/specs/2026-04-26-utm-test-environment-design.md`.
