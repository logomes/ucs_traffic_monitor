# UTM Production Rollout — Design Spec

**Date:** 2026-04-26
**Status:** Approved
**Owner:** lucgomes
**Target:** internal fork (sub-project 2 of stack modernization roadmap)
**Branch:** `feat/prod-rollout-grafana-12` (new, branched off `feat/grafana-12-modernization`)

---

## Problem

A VM de produção do operador roda Grafana 12 / Telegraf 1.38 / InfluxDB 1.10 (já atualizada externamente), mas a codebase UTM é **toda original**: script monolítico antigo (sem `credentials.py`), credenciais em `ucs_domains_group_*.txt` plaintext, dashboards Angular (legacy schema 22/26/27) imported via API, sem provisioning, sem operator scripts refatorados.

Os 4 sub-projetos completados (Phase 4 credentials, Phase 5 SOPS, bash-hygiene, grafana-12-modernization) só vivem no GitHub fork. Precisamos transportar esse trabalho pro VM com:
1. **Backup automático** (rollback trivial se algo quebrar)
2. **Idempotência** (re-run seguro)
3. **Mínimo downtime** (~30s de telegraf parado)
4. **Auto-validação** (operador confirma estado pós-deploy via comandos)

## Goals

1. Tarball self-contained (`utm-prod-deploy-<sha>.tar.gz`) que o operador `scp`-ia pra VM e roda `sudo ./install.sh`.
2. Deploy do credentials refactor (script + lib + creds.env workflow + systemd EnvironmentFile drop-in).
3. Deploy dos 9 dashboards migrados via Grafana provisioning (substitui o método API antigo).
4. Deploy dos operator scripts (`upgrade_utm.sh`, `backup_utm_dashboards.sh`, `lib/utm-common.sh`).
5. Rollback automático embutido (em caso de erro durante o install) + rollback script standalone gerado (pra usar 24h depois se necessário).
6. Tempo total de janela de manutenção ≤ 15 min (3 min de install + 10 min de validação visual).

## Non-Goals

- Migração da stack de versões (Grafana, Telegraf, InfluxDB) — já feita pelo operador externamente.
- Deploy de SOPS layer (Phase 5 do credentials project) — ficou opt-in. Operador pode adicionar depois lendo `docs/SOPS_SETUP.md`.
- Setup de monitoring/alerting do próprio UTM — fora de escopo.
- Conversão de dashboards API-imported existentes para provisioning-managed — provisioning auto-update por UID resolve sem ação extra.
- Execução real na VM — eu entrego o tarball, operador executa.

## Threat Model

- Operador roda script com sudo numa VM de produção que coleta dados de UCS de produção. Erro derruba telegraf temporariamente, mas:
  - Backup automático preserva estado anterior
  - Rollback automático em qualquer falha do install
  - Downtime real é ~30s, dentro de tolerância de 1 ciclo de coleta
- Tarball pode ser inspecionado antes de rodar (`tar tzf` lista conteúdo).
- Script é POSIX-compliant + roda em SUSE (operador confirmou).

---

## Architecture

### Layout final na VM

```
/usr/local/telegraf/                   # repo do UTM
├── ucs_traffic_monitor.py             # SUBSTITUÍDO (versão 0.53 com env vars)
├── credentials.py                     # NOVO
├── lib/
│   └── utm-common.sh                  # NOVO
├── scripts/
│   └── migrate_credentials.py         # NOVO
├── upgrade_utm.sh                     # SUBSTITUÍDO (refatorado)
├── backup_utm_dashboards.sh           # NOVO
└── backup_utm_bashboards.sh           # SYMLINK (compat)

/etc/utm/                              # NOVO
└── creds.env                          # chmod 600, owner telegraf

/etc/grafana/provisioning/dashboards/
└── utm.yml                            # NOVO

/var/lib/grafana/dashboards/
└── *.json                             # 9 JSONs migrados

/etc/systemd/system/telegraf.service.d/
└── utm-creds.conf                     # NOVO — drop-in EnvironmentFile

/etc/telegraf/telegraf.conf            # MODIFICADO — invocação muda

/root/utm-pre-upgrade-<YYYY-MM-DD>/    # backup automático
├── ucs_traffic_monitor.py
├── ucs_domains_group_*.txt
├── telegraf.conf
├── dashboards-snapshot/               # via Grafana API
│   └── *.json
├── rollback.sh                        # standalone, executável
└── README.txt
```

### Estrutura do tarball

```
utm-prod-deploy-<sha>.tar.gz
├── install.sh                         # entrypoint, idempotente
├── files/
│   ├── ucs_traffic_monitor.py         # do branch grafana-12-modernization
│   ├── credentials.py
│   ├── lib/
│   │   └── utm-common.sh
│   ├── scripts/
│   │   └── migrate_credentials.py
│   ├── upgrade_utm.sh
│   ├── backup_utm_dashboards.sh
│   ├── grafana/
│   │   ├── dashboards/                # 9 JSONs
│   │   │   └── *.json
│   │   └── provisioning/
│   │       └── utm.yml
│   └── systemd/
│       └── telegraf-utm-creds.conf
└── README.md                          # quickstart + troubleshooting + rollback
```

### Build do tarball

Script `deploy/pack.sh` no repo monta o tarball a partir do branch atual. Não-commitado (gerado fresh por run). SHA do branch entra no nome do tarball pra rastreabilidade (`utm-prod-deploy-77dfc49.tar.gz`).

---

## install.sh — fluxo

11 passos lineares com `set -euo pipefail` e `trap rollback ERR`:

1. **Pre-flight**: confirma root, detecta paths (`UTM_DIR`, `GRAFANA_IMG_DIR`, `telegraf.conf`), valida deps (`python3`, `jq`, `sed`, `sha256sum`), confirma user `telegraf`, confirma `telegraf` + `grafana-server` rodando.
2. **Backup**: cria `/root/utm-pre-upgrade-<DATE>/`, copia arquivos chave, snapshota dashboards via Grafana API (interativo: pede credencial, ou skip via `SKIP_GRAFANA_BACKUP=1`), gera `rollback.sh` standalone, pede confirmação ao operador.
3. **Stop telegraf**: `systemctl stop telegraf`, aguarda confirmação stopped.
4. **Deploy scripts**: `install -m 644/755` dos arquivos pra `/usr/local/telegraf/`, criando subdirs `lib/` e `scripts/`. Symlink de compat `backup_utm_bashboards.sh`.
5. **Migrate credentials**: cria `/etc/utm/` (chmod 0700 owner telegraf), roda `migrate_credentials.py` pra cada `ucs_domains_group_*.txt`, gera `creds.env` (chmod 600 owner telegraf).
6. **Update telegraf.conf**: localiza linha do exec input (grep), substitui invocação old → new (`--instance-name utm`), backup `.bak` lateral.
7. **Setup systemd EnvironmentFile**: `mkdir -p /etc/systemd/system/telegraf.service.d/`, escreve `utm-creds.conf` com `[Service]\nEnvironmentFile=/etc/utm/creds.env`, `systemctl daemon-reload`.
8. **Setup Grafana provisioning**: copia `utm.yml` pra `/etc/grafana/provisioning/dashboards/`, cria `/var/lib/grafana/dashboards/` (owner grafana), copia 9 JSONs.
9. **Restart services**: `systemctl daemon-reload && systemctl restart telegraf grafana-server`, aguarda 60s.
10. **Validate**: 6 checks via curl/grep (InfluxDB ping 204, Grafana health 200, log mostra "Added domain dict", InfluxDB recebe dados, 9 dashboards listed, sample query > 0).
11. **Exit**: imprime resumo + paths importantes + comando de rollback. Exit 0 se todos checks OK; warn se algum falhou (mas não rollback automático nessa fase — checks são informativos pós-deploy).

### Idempotência

Cada passo verifica antes de agir:
- `creds.env` já existe? Skip migração.
- `telegraf.conf` já tem `--instance-name`? Skip edit (compara com sed dry-run).
- Provisioning yaml já existe com mesmo SHA? Skip.
- Drop-in já existe? Diff e re-criar só se diferente.

### Modos de execução

```sh
# Default — interativo
sudo ./install.sh

# Não-interativo
sudo SKIP_CONFIRMATIONS=1 SKIP_GRAFANA_BACKUP=1 ./install.sh

# Dry-run
sudo ./install.sh --dry-run

# Paths customizados
sudo UTM_DIR=/opt/utm TELEGRAF_CONF_PATH=/etc/telegraf/telegraf.conf ./install.sh

# Rollback explícito
sudo ./install.sh --rollback /root/utm-pre-upgrade-2026-04-26
```

---

## Rollback strategy

### Automático (durante install)

`trap rollback ERR` no install.sh. Em qualquer falha de passos 3-9:
1. Stop telegraf + grafana-server
2. Restaura arquivos do backup (`ucs_traffic_monitor.py`, `telegraf.conf`, `ucs_domains_group_*.txt`)
3. Remove drop-in systemd
4. Remove provisioning yaml + JSONs em `/var/lib/grafana/dashboards/`
5. `systemctl daemon-reload && systemctl start telegraf grafana-server`
6. **NÃO toca em `/etc/utm/creds.env`** (safe pra deixar; telegraf antigo não lê)
7. Exit 1 com mensagem indicando path do backup pra inspeção

### Manual (após sucesso aparente, problema descoberto depois)

Backup gera `/root/utm-pre-upgrade-<date>/rollback.sh` standalone. Operador roda:
```sh
sudo bash /root/utm-pre-upgrade-<date>/rollback.sh
```

Faz exatamente o mesmo que o automático.

---

## Edge cases

| Cenário | Detecção | Ação |
|---|---|---|
| User não é root | `[[ $EUID -ne 0 ]]` | Exit 1 |
| `python3`/`jq`/`sed`/`sha256sum` ausente | `command -v` | Exit 1 com hint de instalação |
| User `telegraf` não existe | `id telegraf` | Exit 1 |
| `telegraf.service` não existe | `systemctl cat telegraf` | Exit 1 |
| `/usr/local/telegraf/` não existe | `[[ -d ... ]]` | Exit 1, sugere `UTM_DIR=...` |
| Múltiplos `ucs_domains_group_*.txt` | Loop em `*.txt` | Cria `creds_N.env` por arquivo; primeiro vira `creds.env`; documenta multi-instance no README |
| `telegraf.conf` em path não-padrão | Detecta via `systemctl cat` | Pede `TELEGRAF_CONF_PATH=...` |
| Senha do Grafana pra backup de dashboards | Prompt interativo | Skip via `SKIP_GRAFANA_BACKUP=1` |
| Dashboards com mesmo UID já no Grafana DB | Provisioning auto-update | Aceita — comportamento padrão |
| `/var/lib/grafana/dashboards/` tem JSONs de outra origem | List warn, não apaga | Operador decide |
| Conexão UCS falhar pós-deploy | Grep no log durante validação | Warn (não rollback — problema fora do escopo do install) |
| Re-run do script | Cada step é idempotente | Re-aplica só o necessário, sem dano |

---

## Acceptance criteria

| # | Critério | Como verificar |
|---|---|---|
| 1 | install.sh termina exit 0 | `echo $?` |
| 2 | Backup completo em `/root/utm-pre-upgrade-<date>/` | `ls -la /root/utm-pre-upgrade-*` |
| 3 | `creds.env` perms corretas | `stat -c '%a %U:%G' /etc/utm/creds.env` = `600 telegraf:telegraf` |
| 4 | Drop-in systemd ativo | `systemctl cat telegraf \| grep EnvironmentFile` |
| 5 | Telegraf rodando sem erros | `journalctl -u telegraf -n 20 \| grep -i error` vazio (ou só transitórios UCS) |
| 6 | Script lê credenciais | `grep "Added.*to domain dict" /var/log/telegraf/.../ucs_traffic_monitor_utm.log` ≥ 1 |
| 7 | InfluxDB recebendo dados reais | `curl -G localhost:8086/query --data-urlencode 'q=SELECT count(*) FROM FIEnvStats WHERE time > now() - 5m'` > 0 |
| 8 | Grafana up | `curl localhost:3000/api/health` = 200 |
| 9 | 9 dashboards no folder UTM | API search ou `ls /var/lib/grafana/dashboards/*.json \| wc -l` = 9 |
| 10 | Dashboards renderizam visualmente | Operador navega pelos 9 no browser |
| 11 | Operator scripts disponíveis | `ls /usr/local/telegraf/{lib,scripts,upgrade_utm.sh,backup_utm_dashboards.sh}` |
| 12 | Rollback script standalone gerado | `bash /root/utm-pre-upgrade-<date>/rollback.sh --dry-run` |

---

## Estimates

**Implementation (dev side):**
- Escrever install.sh: ~150 linhas, 1.5h
- Escrever pack.sh: ~30 linhas, 15min
- Escrever README do tarball: ~80 linhas, 30min
- Smoke test contra container SUSE local: ~30min (opcional)
- Commits + push: 15min
- **Total: 2-3h focadas**

**Operator execution (VM side):**
- `scp` tarball: <30s
- `tar xzf` + `sudo ./install.sh`: ~3 min
- Validação visual: ~10 min
- **Total: ~15 min de janela de manutenção**

Downtime real do telegraf: ~30s entre stop e start.

---

## Open questions

Nenhuma. Design fechado em conversa de 2026-04-26.

## Next step (after this delivery)

Sub-projetos futuros possíveis:
- **Migração dos dashboards Angular nos 4 dashboards "broken" se o operador usar UCS real e quiser visualização** — atualmente já estão migrados pra native panels via JSON edit, mas alguns multi_text panels podem precisar de UX refinement com dados reais.
- **InfluxDB v2/v3 evaluation** — projeto de pesquisa antes de implementação.
- **CI testando install.sh em containers SUSE/CentOS** — confidence pra futuras releases do tarball.
- **Adicionar um servidor proxy ou hardening adicional na VM** — fora do escopo do UTM mas relevante.
