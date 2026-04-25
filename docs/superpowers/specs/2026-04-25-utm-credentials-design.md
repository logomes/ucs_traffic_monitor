# UTM Credentials Management — Design Spec

**Date:** 2026-04-25
**Status:** Approved
**Owner:** lucgomes
**Target:** `paregupt/ucs_traffic_monitor` (upstream PR) + internal fork

---

## Problem

Credenciais de domínios UCS (host, usuário, senha) hoje vivem em arquivo plaintext (`telegraf/ucs_domains_group_*.txt`) lido diretamente pelo `ucs_traffic_monitor.py`. O serviço roda numa VM cujos snapshots vão para storage externo, então qualquer backup carrega senhas legíveis. Vetores secundários: shell scripts (`backup_utm_bashboards.sh`, `upgrade_utm.sh`) interpolam credenciais Grafana em URLs sem aspas e o repositório não tem CI que detecte regressões.

## Goals

1. Eliminar credenciais em texto plano em disco persistente.
2. Falha rápida e auditável quando configuração de credenciais está incompleta ou inválida.
3. Manter compatibilidade com deploy não-interativo (Telegraf exec / systemd).
4. Entregar mudança em duas camadas separadas: uma genérica e portável (upstream PR), outra opinada para a VM interna (fork).
5. Introduzir testes automatizados e CI no projeto, focados no novo módulo.

## Non-Goals

- Refatorar o monolito `ucs_traffic_monitor.py` (2960 linhas) — fora de escopo.
- Hot-reload de credenciais sem restart do serviço.
- Healthcheck endpoint.
- Suporte a múltiplos backends de segredos no script (Vault, AWS Secrets Manager, etc.) — esses ficam como camada externa que produz env vars.
- Mudanças em `backup_utm_bashboards.sh` / `upgrade_utm.sh` (próximo item da roadmap).

## Threat Model

- **Atacante com acesso ao backup/snapshot da VM** (storage externo, replicação DR): não deve obter credenciais legíveis.
- **Usuário não-privilegiado dentro da VM**: não deve ler credenciais.
- **Hypervisor admin com acesso ao disco da VM**: deve precisar da chave `age` (mantida fora do backup) para decifrar segredos.
- **Atacante com root na VM em execução**: fora de escopo — assume-se que root pode tudo.

---

## Architecture

Duas camadas separadas, conectadas por uma única interface: variáveis de ambiente.

```
┌─────────────────────────────────────────────────────────────┐
│  Camada Fork (opt-in, não vai upstream)                     │
│  ┌──────────────────────┐    ┌──────────────────────┐       │
│  │ credentials.sops.yaml│ →  │ sops + age key       │       │
│  │ (cifrado, em git)    │    │ (decifra em boot)    │       │
│  └──────────────────────┘    └────────┬─────────────┘       │
│                                       ▼                     │
│                              gera /run/utm/creds.env        │
│                              (tmpfs, chmod 600, efêmero)    │
└───────────────────────────────────────┬─────────────────────┘
                                        │
        ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
                                        │
┌───────────────────────────────────────┼─────────────────────┐
│  Camada Upstream (vai no PR)          ▼                     │
│  systemd unit (utm.service)                                 │
│    └─ EnvironmentFile=/run/utm/creds.env                    │
│    └─ ExecStart=ucs_traffic_monitor.py                      │
│                                                             │
│  ucs_traffic_monitor.py                                     │
│    └─ lê os.environ['UTM_DOMAINS'] (lista de IDs)           │
│    └─ para cada id, lê UTM_<id>_HOST/USER/PASS              │
│    └─ falha rápido se faltar variável                       │
└─────────────────────────────────────────────────────────────┘
```

**Princípio:** o script Python não conhece SOPS. Ele só lê env vars. SOPS é uma camada externa, opt-in, que entrega as env vars.

---

## Boot sequence

1. systemd inicia `utm-creds.service` (oneshot, camada fork).
2. `utm-creds.service` executa `utm-decrypt-creds.sh`, que lê `/etc/utm/credentials.sops.yaml` (cifrado), usa `/etc/utm/age.key` para decifrar, escreve `/run/utm/creds.env` atomicamente (chmod 600, owner telegraf).
3. systemd inicia `utm.service` (depende de `utm-creds.service`).
4. `utm.service` carrega `/run/utm/creds.env` via `EnvironmentFile=`.
5. `ucs_traffic_monitor.py` lê env vars e processa domínios.

Em reboot: `/run/utm/creds.env` evapora (tmpfs); o oneshot regenera. Zero ação manual.

---

## Components

### Camada upstream

#### 1. `telegraf/credentials.py` (novo)

Módulo isolado, importável, sem efeitos colaterais.

API pública:
- `@dataclass(frozen=True)` `Domain` com campos `id: str`, `host: str`, `user: str`, `password: str`, `group: str`.
- `load_domains_from_env(env: Mapping[str, str] | None = None) -> list[Domain]`
  - Se `env` é `None`, usa `os.environ`.
  - Lê `UTM_DOMAINS` (CSV de IDs, whitespace tolerado).
  - Para cada id, lê `UTM_<id>_HOST`, `UTM_<id>_USER`, `UTM_<id>_PASS`, `UTM_<id>_GROUP` (último opcional, default `"default"`).
  - Falha com `SystemExit(2)` em qualquer ausência ou input vazio.
  - Mensagens de erro listam **nomes** de variáveis faltantes, nunca valores.

#### 2. `telegraf/ucs_traffic_monitor.py` (modificado)

- Remove a função que parseia `ucs_domains_group_*.txt`.
- Substitui por chamada a `credentials.load_domains_from_env()`.
- CLI: o argumento posicional do arquivo de credenciais é removido. Demais flags não-relacionadas a credenciais são preservadas inalteradas. Comentário no header documenta breaking change.

#### 3. `systemd/utm.service.example` (novo)

Unit file de referência. Aponta para `EnvironmentFile=/etc/utm/creds.env` por padrão (camada fork sobrescreve para `/run/utm/creds.env`).

#### 4. `scripts/migrate_credentials.py` (novo, one-shot)

- Lê `ucs_domains_group_*.txt` antigo.
- Gera `creds.env` no formato esperado pelo módulo novo.
- Imprime instruções pós-migração: `chmod 600`, ownership, `shred` do arquivo antigo.
- Não apaga nada automaticamente. Operador faz a deleção manualmente após validar.

#### 5. `tests/test_credentials.py` (novo)

Casos cobertos:
- `UTM_DOMAINS=dom1` + 3 vars completas → retorna `[Domain(...)]` correto.
- `UTM_DOMAINS` ausente → `SystemExit(2)`.
- `UTM_DOMAINS=dom1` faltando `UTM_dom1_PASS` → `SystemExit(2)`, mensagem lista a var ausente.
- Mensagem de erro **não contém** valores das vars existentes (regressão de vazamento).
- `UTM_DOMAINS=dom1, dom2 ,dom3` (whitespace variado) → parseia 3 domínios.
- `UTM_DOMAINS=` (vazio) → `SystemExit(2)`.
- `UTM_<id>_GROUP` ausente → default `"default"`.

Todos os testes usam `monkeypatch.setenv`. Nenhum I/O de disco ou rede.

#### 6. `pyproject.toml` (novo)

- Declara `python_requires = ">=3.10"`.
- Dev deps: `pytest`, `ruff`.
- Configura ruff (lint + format) e pytest.

#### 7. `.github/workflows/ci.yml` (novo)

- Trigger: push e pull_request.
- Jobs: `pytest`, `ruff check`, `ruff format --check`.
- Matrix Python: 3.10, 3.11, 3.12.

#### 8. `README.md` (modificado)

- Seção "Configuration" reescrita: documenta env vars + exemplo de `creds.env`.
- Nova seção "Migrating existing deployments" descreve uso do `migrate_credentials.py`.
- Aviso explícito: `chmod 600`, owner `telegraf`.

### Camada fork (não vai upstream)

#### 9. `secrets/credentials.sops.yaml.example` (novo)

Template do YAML cifrado pelo SOPS. Estrutura:

```yaml
domains:
  dom1:
    host: 10.0.0.10
    user: monitoring
    password: ENC[AES256_GCM,...]
    group: production
  dom2:
    host: 10.0.0.20
    user: monitoring
    password: ENC[AES256_GCM,...]
    group: production
```

`host`, `user`, `group` ficam em claro (operacionalmente úteis no diff). Apenas `password` é cifrado, controlado por regra em `.sops.yaml`.

#### 10. `secrets/.sops.yaml` (novo)

Config do SOPS. Define a chave `age` recipient e regex que cifra apenas campos `password`.

#### 11. `systemd/utm-creds.service` (novo)

Oneshot. Cria `/run/utm` (tmpfs), executa `utm-decrypt-creds.sh`. `RemainAfterExit=yes`. `ExecStop` remove `/run/utm/creds.env`.

#### 12. `bin/utm-decrypt-creds.sh` (novo)

- `set -euo pipefail`.
- `sops -d /etc/utm/credentials.sops.yaml` para stdout.
- Converte YAML para `KEY=VALUE` via `yq` (ou Python inline).
- Escreve em `/run/utm/creds.env.tmp`, faz `chmod 600` e `mv` atômico para `/run/utm/creds.env`.
- Falha não deixa arquivo parcial.

#### 13. `docs/SOPS_SETUP.md` (novo)

- Bootstrap: gerar `age.key`, configurar `.sops.yaml`, cifrar primeiro YAML.
- Rotação de senha: `sops credentials.sops.yaml` (abre editor, salva cifrado).
- Adicionar/remover domínio: passos.
- **Importante:** instrução explícita para operador coordenar exclusão de `/etc/utm/age.key` da política de backup.

---

## Error handling

| Falha | Onde detecta | Comportamento |
|---|---|---|
| `UTM_DOMAINS` ausente/vazio | `credentials.py` no startup | `SystemExit(2)`. Log: "no domains configured — set UTM_DOMAINS env var". |
| Domínio listado mas falta `UTM_<id>_HOST/USER/PASS` | `credentials.py` no startup | `SystemExit(2)`. Log lista quais vars faltam. Não imprime valores. |
| `creds.env` não existe | systemd | `utm.service` não inicia (EnvironmentFile obrigatório). |
| `creds.env` com perms erradas (não 600) | startup do script | Warning no log; segue. Reportado como hardening, não bloqueante. |
| SOPS falha ao decifrar | `utm-creds.service` (oneshot) | Falha o oneshot. `utm.service` não inicia (depende). Log claro: "age key not found at /etc/utm/age.key". |
| YAML cifrado malformado | `utm-decrypt-creds.sh` | Falha oneshot. Não escreve `creds.env` parcial (writes em tmp + mv atômico). |
| Credencial UCS errada (em runtime) | já existe — `set_ucs_connection` | Comportamento atual mantido (log + skip do domínio). |

**Princípios:**
- Falha rápida no startup — credencial faltando = serviço não sobe.
- Mensagens nunca vazam valores de variáveis (testado).
- Atomic writes para `creds.env`.
- Sem retry/backoff em SOPS (problema operacional, não transitório).
- Sem hot-reload (restart resolve).

---

## Migration plan (VM em produção)

1. **Backup de segurança:**
   ```fish
   sudo cp /etc/telegraf/ucs_domains_group_*.txt /root/utm-backup-$(date +%F).txt
   sudo chmod 600 /root/utm-backup-*.txt
   ```
2. **Deploy do código novo** (pull do fork).
3. **Migração:**
   ```fish
   sudo python3 scripts/migrate_credentials.py \
       --input /etc/telegraf/ucs_domains_group_1.txt \
       --output /etc/utm/creds.env
   sudo chmod 600 /etc/utm/creds.env
   sudo chown telegraf:telegraf /etc/utm/creds.env
   ```
4. **Validar:** `systemctl restart utm && journalctl -u utm -f`. Confirmar coleta normal.
5. **Após 24-48h sem regressões:**
   - `shred -u /etc/telegraf/ucs_domains_group_*.txt`.
   - Migrar para SOPS (camada fork): cifrar `creds.env` em `credentials.sops.yaml`, ativar `utm-creds.service`, mover `creds.env` para `/run/utm/`.
6. **Coordenar com infra:** excluir `/etc/utm/age.key` da política de backup.

**Rollback:** restaurar `.txt` do `/root/utm-backup-*` e reverter o pull. Mudança é só de config — rollback trivial.

---

## Delivery order

| # | Entrega | Repositório alvo | Tamanho estimado |
|---|---|---|---|
| 1 | Refactor + módulo + tests + CI + docs | PR upstream | ~400 linhas |
| 2 | SOPS yaml + utm-creds.service + decrypt script + docs | fork interno | ~150 linhas |
| 3 | Bootstrap SOPS na VM + migração on-host | operação | — |

A Entrega 2 pode ser desenvolvida em paralelo no fork enquanto a Entrega 1 está em review upstream.

---

## Next step (após esta entrega)

Recomendado: **consolidar `upgrade_utm.sh` + `backup_utm_bashboards.sh`** (item #3 do punch list). Mesmo vetor de segurança (credenciais em URLs sem aspas, downloads sem checksum), escopo contido (~1-2 dias), fecha o capítulo de segurança crítica antes de tocar em modernização (Grafana 7→10, com risco de regressão de dashboards).

Itens postergados explicitamente:
- Bump de versões (Grafana/Telegraf): requer testes de migração de dashboards. Fazer após CI estar maduro.
- Refactor do monolito `ucs_traffic_monitor.py`: alto risco sem cobertura ampla de testes. Não justificável agora.

---

## Open questions

Nenhuma. Design fechado em conversa de 2026-04-25.
