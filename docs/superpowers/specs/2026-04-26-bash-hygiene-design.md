# UTM Bash Hygiene — Design Spec

**Date:** 2026-04-26
**Status:** Approved
**Owner:** lucgomes
**Target:** internal fork now, upstream PR later (compat-friendly choices)
**Branch:** `feat/credentials-env-vars` (or follow-up branch)

---

## Problem

Os dois scripts shell do projeto (`upgrade_utm.sh`, `backup_utm_bashboards.sh`) carregam três classes de problema reais:

1. **Credenciais Grafana embutidas em URLs** (`http://$USER:$PASS@host/...`) — quebra com senhas que contenham `@`, `/`, `?`, `#`, `:`, `[` ou `]`, e expõe as credenciais em listagens de processo, logs de proxy e qualquer mensagem de erro que ecoe a URL.
2. **Downloads de RPMs sem verificação de integridade** (`wget` direto + `yum -y install`) — instala pacotes como root sem checar checksum publicado pelo distribuidor.
3. **Sem `set -euo pipefail`** — após falhas silenciosas o script segue executando, levando a estados inconsistentes (ex.: backup quebrado mas upgrade prossegue).

Há também duplicação literal entre os dois scripts (declaração do array `utm_dashboard_arr`, loop de auth Grafana) e um typo no nome (`bashboards` em vez de `dashboards`).

## Goals

1. Eliminar os três vetores de segurança acima.
2. Extrair lógica compartilhada para `lib/utm-common.sh` — uma única source of truth para a lista de dashboards e fluxo de auth Grafana.
3. Refatorar `upgrade_utm.sh` em funções nomeadas com `main()` no final (idiomático bash).
4. Renomear `backup_utm_bashboards.sh` → `backup_utm_dashboards.sh` mantendo symlink temporário para compat.
5. Adicionar shellcheck + bats ao CI existente.
6. Manter "voz Kiara" e UX existente — escolha consistente com o objetivo de também aceitar upstream.

## Non-Goals

- Modernizar versões da stack (Grafana 12, InfluxDB 3, Telegraf 1.38). Tópico separado, do item #1b da roadmap, escopo bem maior (inclui migração de dashboards JSON).
- Suporte a outros gerenciadores de pacote além de yum/dnf. RHEL/CentOS é o alvo.
- Reescrever em Python ou outra linguagem.
- Mudar o cron/operacional do operador.

## Threat Model

- **Operador rodando script com senha que contém caracteres especiais**: hoje quebra; após mudança, funciona.
- **Atacante com acesso a `/proc` ou logs de proxy**: hoje vê credenciais Grafana em URLs; após mudança, credenciais ficam só no header `Authorization` do curl.
- **Repositório de RPM compromised**: hoje script instala qualquer payload; após mudança, falha o instalado se SHA não casar com expected.
- **Operador rodando script numa rede não confiável**: HTTPS já protege em trânsito; checksum protege contra package repository compromise.
- **Atacante com root no host**: fora de escopo — assume-se que root pode tudo.

---

## Architecture

```
ucs_traffic_monitor/
├── lib/
│   └── utm-common.sh            # NOVO — helpers compartilhados
├── upgrade_utm.sh               # REFATORADO (era 291 linhas → ~150-180)
├── backup_utm_dashboards.sh     # RENOMEADO de backup_utm_bashboards.sh
├── backup_utm_bashboards.sh     # SYMLINK pro novo nome (compat)
└── tests/
    └── bash/                    # NOVO — bats tests para lib
        ├── test_utm_common.bats
        └── ...
```

**Princípio:** `upgrade_utm.sh` e `backup_utm_dashboards.sh` viram clientes finos da `lib/utm-common.sh`. Lib concentra:
- Helpers de I/O (log, confirm, require)
- Wrappers seguros do curl Grafana
- Definição canônica do array de dashboards
- Função de download com verificação SHA256

---

## Components

### 1. `lib/utm-common.sh` (novo)

Funções públicas (prefixo `utm::` para evitar colisão):

| Função | Assinatura | Comportamento |
|---|---|---|
| `utm::require_jq` | `()` | `command -v jq` ou exit 1 com mensagem clara |
| `utm::dashboards_list` | `()` | Echo do array associativo (chave=nome, valor=UID) |
| `utm::log` | `(level, msg)` | Print formatado com timestamp |
| `utm::confirm` | `(prompt) -> 0\|1` | `read -n 1 -r`, retorna 0 se Y/y, 1 se N/n |
| `utm::grafana_login_loop` | `()` | Lê GRAFANA_USER/PASSWORD interativo, valida via `/api/org`, repete até OK |
| `utm::grafana_curl` | `(method, path, ...extra)` | Wrapper do curl com `--user`, headers JSON; sem URL-creds |
| `utm::backup_dashboard` | `(uid, output_file)` | GET `/api/dashboards/uid/<uid>` salvo em arquivo |
| `utm::backup_all_dashboards` | `(dest_dir)` | Itera `dashboards_list`, chama `backup_dashboard` para cada |
| `utm::download_with_checksum` | `(url, sha256, output_path)` | wget/curl + verifica SHA256, falha rápido se diferente |

**Convenções internas:**
- `set -euo pipefail` esperado no script chamador (lib não força)
- Funções não chamam `exit` exceto helpers de pré-requisito (`require_jq`, `download_with_checksum` em caso de mismatch)
- Variáveis globais usadas: `GRAFANA_USER`, `GRAFANA_PASSWORD` (preenchidas por `grafana_login_loop`)
- Constante `UTM_GRAFANA_HOST` (default `localhost:3000`) override via env

**Array canônico de dashboards:**
```bash
declare -gA UTM_DASHBOARDS=(
    ["locations"]="ri2OFp4Wz"
    ["domain_overview"]="Inte2EIWk"
    ["domain_traffic"]="W7LSukHWz"
    ["chassis_traffic"]="KOM8ZHNWz"
    ["service_profile"]="Z0M_N1vWz"
    ["ingress_congestion"]="Sve32sDZk"
    ["chassis_pause"]="SVO-VNiWk"
    ["local_sys"]="9CXO3jTWz"
)
```

Quem precisa dos UIDs lê `${UTM_DASHBOARDS[locations]}` etc. Adicionar dashboard novo = editar 1 linha aqui.

### 2. `upgrade_utm.sh` (refatorado)

Estrutura:
```bash
#!/bin/bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/utm-common.sh"

# Versions parametrizáveis via env
: "${UTM_VERSION:=5}"
: "${UTM_DIR:=/usr/local/telegraf}"
: "${GRAFANA_IMG_DIR:=/usr/share/grafana/public/img}"
: "${GRAFANA_VERSION:=7.5.7}"
: "${GRAFANA_RPM_SHA256:=<placeholder>}"
: "${TELEGRAF_VERSION:=1.18.3}"
: "${TELEGRAF_RPM_SHA256:=<placeholder>}"

intro_kiara() { ... }              # mantém personalidade
upgrade_packages_phase() { ... }   # download_with_checksum + yum localinstall
upgrade_images_phase() { ... }     # cp images/*
upgrade_collector_phase() { ... }  # backup + cp ucs_traffic_monitor.py
toggle_legacy_grafana_settings() { ... }
backup_existing_dashboards() { ... }   # via utm::backup_all_dashboards
upgrade_dashboards() { ... }       # POST modificado pra cada dashboard
bye_kiara() { ... }

main() {
    intro_kiara
    utm::confirm "May I continue?" || exit 0
    utm::require_jq

    if utm::confirm "Upgrade everything (a) or just dashboards?"; then
        upgrade_packages_phase
        upgrade_images_phase
        upgrade_collector_phase
        toggle_legacy_grafana_settings
    fi

    if utm::confirm "Are you ready to upgrade UI dashboards?"; then
        utm::grafana_login_loop
        backup_existing_dashboards
        upgrade_dashboards
    fi

    systemctl restart grafana-server
    bye_kiara
}

main "$@"
```

**SHA256 placeholders documentados:**
Comentário no topo do script ensina como obter SHAs:
```bash
# To pin to a different version, override via env vars and supply the matching
# SHA256. Get the SHA from the publisher:
#   Grafana:  https://dl.grafana.com/oss/release/grafana-X.Y.Z-1.x86_64.rpm.sha256
#   Telegraf: https://dl.influxdata.com/telegraf/releases/telegraf-X.Y.Z-1.x86_64.rpm.sha256
```

Default SHAs no script são os reais para Grafana 7.5.7 e Telegraf 1.18.3 (computados durante implementação).

### 3. `backup_utm_dashboards.sh` (renomeado e simplificado)

```bash
#!/bin/bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/utm-common.sh"

: "${UTM_DIR:=/usr/local/telegraf}"

main() {
    utm::require_jq
    utm::grafana_login_loop

    local dest_dir="$UTM_DIR/grafana/dashboards_$(date +%M%H%m%d%y)"
    mkdir -p "$dest_dir"
    utm::backup_all_dashboards "$dest_dir"

    echo "Backup saved to $dest_dir"
}

main "$@"
```

~30 linhas (era 62 com tudo inline e duplicado).

### 4. Symlink de compat

```bash
ln -s backup_utm_dashboards.sh backup_utm_bashboards.sh
```

Commit message documenta que o symlink será removido numa versão futura. Permite migração sem quebrar quem já chama o nome com typo.

### 5. `tests/bash/test_utm_common.bats` (novo)

Casos cobertos:
- `utm::download_with_checksum` falha rápido com SHA mismatch (gera arquivo temp, computa SHA, compara)
- `utm::download_with_checksum` sucesso com SHA correto (deixa arquivo intacto)
- `utm::confirm` retorna 0 em "Y", "y" e 1 em "N", "n", outras chars
- `utm::log` formato `[YYYY-MM-DD HH:MM:SS] LEVEL: msg`
- `UTM_DASHBOARDS` array tem 8 entradas (sanity check contra remoção acidental)

Helpers (não-puros) com I/O de rede (`grafana_curl`, `grafana_login_loop`, `backup_dashboard`) **não são testados unitariamente** — testados manualmente no test-env Docker.

### 6. CI updates (`.github/workflows/ci.yml`)

Adicionar steps:
```yaml
- name: Install shellcheck and bats
  run: sudo apt install -y shellcheck bats

- name: Lint shell scripts
  run: shellcheck lib/utm-common.sh upgrade_utm.sh backup_utm_dashboards.sh

- name: Run bats tests
  run: bats tests/bash/
```

### 7. README updates

Nova subseção em `## Configuration`:

```markdown
### Customizing upgrade_utm.sh

The upgrade script accepts environment variable overrides for Grafana
and Telegraf versions:

  GRAFANA_VERSION=7.5.7 GRAFANA_RPM_SHA256=<sha256> \
  TELEGRAF_VERSION=1.18.3 TELEGRAF_RPM_SHA256=<sha256> \
  ./upgrade_utm.sh

Get the SHA256 from the publisher's signed checksum file alongside
the RPM (e.g., `grafana-X.Y.Z-1.x86_64.rpm.sha256`).
```

---

## Error handling

| Cenário | Detecção | Comportamento |
|---|---|---|
| `jq` ausente | `utm::require_jq` no startup | Exit 1, mensagem com hint de instalação |
| Grafana auth falha | `utm::grafana_login_loop` retorna inválido | Repete prompt (UX preservada) |
| SHA256 mismatch no download | `utm::download_with_checksum` | Apaga arquivo temp + exit 1 + mensagem com SHA esperado vs computado |
| `wget` falha (timeout, 404) | exit não-zero do wget | `set -e` mata o script + log do utm::log |
| `yum localinstall` falha | exit não-zero | `set -e` mata o script |
| Senha com `@` ou `:` | NÃO é mais problema | curl `--user` aceita qualquer string |
| `systemctl restart` falha | exit não-zero | `set -e` mata o script (operador vê e age) |
| Operador respondeu N em "May I continue?" | `utm::confirm` retorna 1 | `|| exit 0` — sai limpo |

**Princípios:**
- Falha rápida em qualquer etapa que afete sistema (downloads, instalações).
- Mensagens identificam **qual recurso** falhou e **o que esperar fazer**.
- Sem retry automático em downloads — operador escolhe rerun.
- Sem rollback automático de `yum localinstall` — fora de escopo.

---

## Acceptance criteria

| # | Verificação | Esperado |
|---|---|---|
| 1 | `bash -n` em todos os 3 scripts | sem erro de sintaxe |
| 2 | `shellcheck lib/utm-common.sh upgrade_utm.sh backup_utm_dashboards.sh` | 0 warnings (ou disables explícitos com comentário) |
| 3 | `bats tests/bash/` | todos green |
| 4 | `grep -c '@localhost' upgrade_utm.sh backup_utm_dashboards.sh` | 0 ocorrências |
| 5 | `grep -c 'set -euo pipefail' upgrade_utm.sh backup_utm_dashboards.sh lib/utm-common.sh` | ≥ 2 (lib pode optar por não forçar) |
| 6 | `grep -c 'sha256' upgrade_utm.sh` | ≥ 4 (2 var de version + 2 chamadas de download_with_checksum) |
| 7 | `grep -c "Hint:admin/Utm_12345" upgrade_utm.sh` | 0 |
| 8 | `ls -la backup_utm_bashboards.sh` | symlink → backup_utm_dashboards.sh |
| 9 | Smoke test: `backup_utm_dashboards.sh` apontando pro test-env Grafana | 9 JSONs salvos no diretório |

---

## Migration / setup

Operador atualiza fork local:
```fish
cd ~/Downloads/ucs_traffic_monitor
git pull origin feat/credentials-env-vars
```

Os scripts antigos foram substituídos in-place. Symlink mantém o nome com typo funcionando.

Para rodar com versões diferentes (ex.: bumpar Grafana sem recodar):
```fish
GRAFANA_VERSION=7.5.7 GRAFANA_RPM_SHA256=abcdef... \
TELEGRAF_VERSION=1.18.3 TELEGRAF_RPM_SHA256=fedcba... \
./upgrade_utm.sh
```

Sem migração de estado — scripts não persistem nada além do que já persistiam.

---

## Delivery

Single delivery, branch `feat/credentials-env-vars` (mesma do trabalho anterior). Tasks (~10-12) cobrem:

1. `lib/utm-common.sh` esqueleto + shellcheck verde
2. Funções puras (`utm::confirm`, `utm::log`, `utm::require_jq`, `UTM_DASHBOARDS`) + bats tests
3. `utm::download_with_checksum` + bats tests (com SHA256 sintético)
4. `utm::grafana_curl`, `utm::grafana_login_loop`, `utm::backup_dashboard`, `utm::backup_all_dashboards`
5. `backup_utm_dashboards.sh` reescrito + symlink
6. Smoke test do backup contra test-env
7. `upgrade_utm.sh` reescrito (phase functions)
8. SHA256 placeholders preenchidos com valores reais para Grafana 7.5.7, Telegraf 1.18.3
9. README updates
10. CI updates (shellcheck + bats)
11. Push + considerar PR upstream
12. Validação final dos 9 acceptance criteria

Estimativa: 1 dia de trabalho focado.

---

## Open questions

Nenhuma. Design fechado em conversa de 2026-04-26.

## Next step (after this delivery)

Conforme roadmap original:
- **Item #1b — modernização da stack** (Grafana 7→12, Telegraf 1.18→1.38, possivelmente InfluxDB 1→3). Decompor em sub-projetos:
  - 2a: subir Grafana 12 no test-env e descobrir o que quebra
  - 2b: pipeline de migração dos dashboards JSON (schema v26 → atual)
  - 2c: avaliação InfluxDB 1.11 (último v1) vs 3 (exige rewrite de queries)
  - 2d: bump real do upgrade_utm.sh (consumindo o trabalho desta spec)

Cada sub-spec tem brainstorm → spec → plan → implementação separados.
