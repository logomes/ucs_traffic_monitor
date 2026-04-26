# UTM — Roteiro de teste na VM

Guia de retomada após reboot. Tudo que você precisa pra testar a refatoração de credenciais (Phase 4) na VM de produção.

## O que está pronto

- **Branch local:** `feat/credentials-env-vars` em `~/Downloads/ucs_traffic_monitor/` (22 commits)
- **No GitHub (seu fork `logomes/ucs_traffic_monitor`):**
  - `master` — base + docs internos (spec + plan)
  - `feat/credentials-env-vars-upstream` — só Phase 4 (16 commits, pra PR upstream)
  - `feat/credentials-env-vars` — Phase 4 + Phase 5 SOPS (22 commits, versão completa)
- **Tarball pronto:** `~/utm-changes.tar.gz` (28 KB) — só Phase 4, pronto pra deploy

## Resumo rápido da mudança

- Antes: credenciais em `ucs_domains_group_*.txt` plaintext
- Depois: credenciais em env vars carregadas via `EnvironmentFile` do systemd
- Breaking: invocação muda de `script.py /path/file.txt influxdb-lp` → `script.py influxdb-lp --instance-name utm`

---

## Deploy na VM — passos

### 1. Copiar tarball

Do seu laptop (CachyOS):
```fish
scp ~/utm-changes.tar.gz seu-usuario@ip-da-vm:/tmp/
```

### 2. Backup na VM (CRÍTICO)

```sh
# Identifique onde está instalado:
ls -la /usr/local/telegraf/ 2>/dev/null || ls -la /opt/utm/

# Backup completo da instalação:
sudo tar czf /root/utm-backup-$(date +%F).tar.gz /usr/local/telegraf/

# Backup do telegraf.conf:
sudo cp /etc/telegraf/telegraf.conf /root/telegraf.conf.bak

# Backup das credenciais antigas (perms restritas):
sudo cp /usr/local/telegraf/ucs_domains_group_*.txt /root/
sudo chmod 600 /root/ucs_domains_group_*.txt
```

### 3. Extrair changes

```sh
cd /usr/local/telegraf  # ajuste se for outro path
sudo tar xzf /tmp/utm-changes.tar.gz
```

### 4. Migrar credenciais

```sh
sudo install -d -m 0700 -o telegraf -g telegraf /etc/utm

sudo python3 /usr/local/telegraf/scripts/migrate_credentials.py \
    --input /usr/local/telegraf/ucs_domains_group_1.txt \
    --output /etc/utm/creds.env

sudo chown telegraf:telegraf /etc/utm/creds.env
sudo chmod 600 /etc/utm/creds.env

# Verifique o conteúdo (atenção, contém senhas):
sudo cat /etc/utm/creds.env
```

Se você tem mais de um group (`group_2.txt`, etc.), repita com `--instance-name` diferente e gere `creds-group2.env` separado.

### 5. Atualizar `/etc/telegraf/telegraf.conf`

Localize o bloco `[[inputs.exec]]` que invoca `ucs_traffic_monitor.py` e troque:

**De:**
```toml
commands = [
    "python3 /usr/local/telegraf/ucs_traffic_monitor.py /usr/local/telegraf/ucs_domains_group_1.txt influxdb-lp -vv",
]
```

**Para:**
```toml
commands = [
    "python3 /usr/local/telegraf/ucs_traffic_monitor.py influxdb-lp --instance-name utm -vv",
]
```

### 6. Carregar env vars no telegraf

Como o script é filho do telegraf, ele herda o environment. Crie um drop-in:

```sh
sudo systemctl edit telegraf
```

Adicione:
```ini
[Service]
EnvironmentFile=/etc/utm/creds.env
```

Salve e:
```sh
sudo systemctl daemon-reload
sudo systemctl restart telegraf
```

### 7. Validação

Logs em tempo real:
```sh
sudo journalctl -u telegraf -f
```

Em outra sessão, force coleta manual:
```sh
sudo -u telegraf bash -c 'set -a; . /etc/utm/creds.env; set +a; \
    python3 /usr/local/telegraf/ucs_traffic_monitor.py influxdb-lp --instance-name utm -vv'
```

Saída esperada: dados em formato InfluxDB Line Protocol no stdout, sem erros.

Log do script:
```sh
sudo tail -f /var/log/telegraf/ucs_traffic_monitor/ucs_traffic_monitor_utm.log
```

Procure por: `Added <ip> to domain dict`. Esse é o sinal de que credenciais carregaram.

### 8. Validar dashboards Grafana

Abra os dashboards. Confira que filtros por `location` ainda agrupam (a migration script preserva os grupos `[Production]` etc).

---

## Rollback (se algo quebrar)

```sh
# Restaurar arquivos:
sudo tar xzf /root/utm-backup-*.tar.gz -C /

# Restaurar telegraf.conf:
sudo cp /root/telegraf.conf.bak /etc/telegraf/telegraf.conf

# Remover drop-in do EnvironmentFile:
sudo systemctl revert telegraf

sudo systemctl restart telegraf
```

---

## Após 24-48h sem regressões

```sh
# Apagar plaintext antigo de forma segura:
sudo shred -u /usr/local/telegraf/ucs_domains_group_*.txt
sudo shred -u /root/ucs_domains_group_*.txt

# Quando quiser ativar SOPS (Phase 5): seguir docs/SOPS_SETUP.md
```

---

## Como retomar a conversa com Claude após o reboot

1. Abra o terminal.
2. Vá pro diretório onde a sessão começou:
   ```fish
   cd ~/Downloads/dashboard
   ```
3. Rode:
   ```fish
   claude --continue
   ```
   Esse comando reabre a conversa mais recente desse projeto. Se não funcionar, alternativas:
   - `claude --resume` — abre um seletor das conversas anteriores
   - Veja transcripts em `~/.claude/projects/-home-lucgomes-Downloads-dashboard/` (lista de JSONs)

4. Quando voltar, me diga o que aconteceu na VM. Se travar em algum passo, paste o output e eu te ajudo.

---

## Arquivos importantes

- Este doc: `~/Downloads/ucs_traffic_monitor/docs/DEPLOY_TEST.md`
- Tarball: `~/utm-changes.tar.gz`
- Repo local: `~/Downloads/ucs_traffic_monitor/` (branch `feat/credentials-env-vars`)
- Spec/design: `~/Downloads/ucs_traffic_monitor/docs/superpowers/specs/2026-04-25-utm-credentials-design.md`
- Plano: `~/Downloads/ucs_traffic_monitor/docs/superpowers/plans/2026-04-25-utm-credentials.md`
- Doc SOPS (Phase 5, futuro): `~/Downloads/ucs_traffic_monitor/docs/SOPS_SETUP.md`
