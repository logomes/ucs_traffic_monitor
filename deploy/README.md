# UTM Production Deployment Tarball

Self-contained tarball that deploys the modernized UTM codebase to
a production VM running Grafana 12, Telegraf 1.38, InfluxDB 1.10 (or
1.11). Idempotent — safe to re-run.

## Quickstart

On your workstation:

```sh
./deploy/pack.sh
scp utm-prod-deploy-<sha>.tar.gz user@vm:/tmp/
```

On the VM:

```sh
cd /tmp
tar xzf utm-prod-deploy-<sha>.tar.gz -C /tmp/utm-deploy
cd /tmp/utm-deploy
sudo ./install.sh
```

The script is interactive — it asks for confirmation after the backup
phase and for Grafana admin credentials during the dashboard snapshot.

For non-interactive runs (CI, scripted deploys):

```sh
sudo SKIP_CONFIRMATIONS=1 SKIP_GRAFANA_BACKUP=1 ./install.sh
```

## What it does

| Phase | Action |
|---|---|
| 1 | Pre-flight: validates root, deps (python3/jq/sed/sha256sum/curl/systemctl), telegraf user exists, services installed, paths valid |
| 2 | Backup: copies current files to `/root/utm-pre-upgrade-<DATE>/`, snapshots dashboards via Grafana API, generates `rollback.sh` |
| 3 | Stops telegraf |
| 4 | Deploys script files: `credentials.py`, `ucs_traffic_monitor.py`, `lib/utm-common.sh`, `scripts/migrate_credentials.py`, `upgrade_utm.sh`, `backup_utm_dashboards.sh` (+ compat symlink) |
| 5 | Migrates credentials: converts `ucs_domains_group_*.txt` → `/etc/utm/creds.env` (chmod 600, owner telegraf) |
| 6 | Updates `telegraf.conf`: replaces legacy invocation with `--instance-name <name>` form |
| 7 | Sets up systemd EnvironmentFile drop-in for telegraf |
| 8 | Sets up Grafana provisioning + drops 9 migrated dashboards |
| 9 | Restarts telegraf and grafana-server, waits 60s |
| 10 | Validates: 6 advisory checks (InfluxDB/Grafana health, telegraf active, script log marker, recent data, dashboards present) |
| 11 | Prints summary with rollback command |

## Configuration via environment variables

| Variable | Default | Purpose |
|---|---|---|
| `UTM_DIR` | `/usr/local/telegraf` | Path to UTM repo on VM |
| `TELEGRAF_CONF_PATH` | `/etc/telegraf/telegraf.conf` | telegraf config |
| `CREDS_DIR` | `/etc/utm` | Where `creds.env` lives |
| `INSTANCE_NAME` | `utm` | Becomes `--instance-name` value + log file suffix |
| `SKIP_CONFIRMATIONS` | `0` | Set to `1` for non-interactive |
| `SKIP_GRAFANA_BACKUP` | `0` | Set to `1` to skip dashboard API snapshot (faster, no Grafana creds needed) |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `[ERROR] User 'telegraf' does not exist` | Telegraf not installed | `sudo zypper install telegraf` (or distro equivalent) |
| `[ERROR] UTM_DIR not found` | UTM in non-default path | `sudo UTM_DIR=/opt/utm ./install.sh` |
| `[ERROR] Failed to update telegraf.conf — invocation pattern not matched` | telegraf.conf doesn't have the legacy exec invocation | Either telegraf already configured for new format, or it lives elsewhere — inspect manually with `grep ucs_traffic_monitor /etc/telegraf/telegraf.conf` |
| Validation #5 fails (no FIEnvStats in 5m) | UCS unreachable from VM | Test: `curl -k https://<UCS-IP>/`. If fails, check firewall / network / credentials in `/etc/utm/creds.env` |
| Dashboards show "No data" | Time range too long, or `db` constant variable issue | Set time range to "Last 5 min" first; if still empty, see migration spec for known issues |

## Rollback

The install script generates a standalone rollback script at
`/root/utm-pre-upgrade-<DATE>/rollback.sh`. To roll back:

```sh
sudo bash /root/utm-pre-upgrade-<DATE>/rollback.sh
```

This restores the original `ucs_traffic_monitor.py`, `telegraf.conf`,
and `ucs_domains_group_*.txt`, removes the systemd drop-in and the
provisioning yaml, and restarts services. The new `creds.env` file is
left in place (harmless — old code doesn't read it).

If install.sh fails partway through (any phase 3-9), it auto-rolls
back via the same script.

## Multi-instance deployments

If your VM has multiple `ucs_domains_group_N.txt` files (multi-instance
collection), the script generates `creds.env`, `creds_2.env`, etc.
Only `creds.env` is wired into the systemd drop-in. To support
additional instances:

1. Edit `/etc/systemd/system/telegraf.service.d/utm-creds.conf`:
   ```ini
   [Service]
   EnvironmentFile=/etc/utm/creds.env
   EnvironmentFile=/etc/utm/creds_2.env
   ```
   (Multi-instance is non-trivial — env vars from later files override
   earlier ones if the same key is defined. Recommend separate
   telegraf instances instead.)
2. Or, more cleanly, run separate telegraf service units, each with
   its own drop-in pointing to one creds file.
3. Each invocation needs a unique `--instance-name` to keep log/pickle
   files separate.

## Build info

Each tarball includes a `BUILD_INFO` file with:
- `sha`: short git SHA of the branch built from
- `built`: ISO timestamp
- `branch`: branch name
- `host`: hostname of the build machine

Verify before running: `cat BUILD_INFO` after `tar xzf`.
