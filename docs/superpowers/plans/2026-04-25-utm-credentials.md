# UTM Credentials Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir leitura de credenciais UCS de arquivo plaintext (`ucs_domains_group_*.txt`) por variáveis de ambiente, adicionar testes/CI no projeto, e (camada fork) acoplar SOPS+age para entregar credenciais via tmpfs em boot.

**Architecture:** Duas camadas. (1) Upstream: módulo isolado `credentials.py` lê env vars e expõe `load_domains_from_env() -> list[Domain]`; `ucs_traffic_monitor.py` consome a função; tooling (pytest, ruff, GitHub Actions) entra junto. (2) Fork: oneshot systemd executa `sops -d` em boot, escreve `/run/utm/creds.env` em tmpfs, `utm.service` lê via `EnvironmentFile=`.

**Tech Stack:** Python 3.10+, pytest, ruff, GitHub Actions, systemd, SOPS, age, fish shell (operador local), bash (script de decifragem).

**Spec:** `docs/superpowers/specs/2026-04-25-utm-credentials-design.md`

**Repository:** `/home/lucgomes/Downloads/ucs_traffic_monitor`

---

## Phase 1 — Project tooling

### Task 1: Add pyproject.toml with pytest and ruff

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore` (append if existe)

- [ ] **Step 1: Create pyproject.toml**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/pyproject.toml`:

```toml
[project]
name = "ucs-traffic-monitor"
version = "0.53.0"
description = "Cisco UCS metrics collector for Telegraf/InfluxDB/Grafana"
requires-python = ">=3.10"
dependencies = [
    "ucsmsdk",
    "netmiko>=4.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "ruff>=0.6",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-v --tb=short"

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP"]
ignore = ["E501"]

[tool.ruff.lint.per-file-ignores]
"telegraf/ucs_traffic_monitor.py" = ["E", "F", "W", "B", "UP"]
```

Note: o `per-file-ignores` para `ucs_traffic_monitor.py` é deliberado — o monolito pré-existente vai produzir centenas de findings de ruff e fora do escopo deste plano corrigir. Só queremos que o módulo novo passe.

- [ ] **Step 2: Append to .gitignore**

Verifique se `.gitignore` existe. Se não existir, crie. Adicione (sem duplicar entradas existentes):

```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.ruff_cache/
.venv/
```

- [ ] **Step 3: Verify ruff installs and runs**

Run:
```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
python3 -m venv .venv
.venv/bin/pip install -e .[dev]
.venv/bin/ruff --version
.venv/bin/pytest --version
```

Expected: ambos imprimem versão sem erro.

- [ ] **Step 4: Commit**

```fish
git add pyproject.toml .gitignore
git commit -m "Add pyproject.toml with pytest and ruff (dev tooling)

Establishes Python 3.10+ baseline and dev dependencies. Per-file
ignore for the legacy monolith keeps ruff useful for new modules
without forcing a full cleanup in this PR.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — credentials.py module (TDD)

### Task 2: First failing test — happy path

**Files:**
- Create: `tests/__init__.py` (arquivo vazio)
- Create: `tests/conftest.py`
- Create: `tests/test_credentials.py`

- [ ] **Step 1: Create empty package marker**

Create empty file `/home/lucgomes/Downloads/ucs_traffic_monitor/tests/__init__.py`.

- [ ] **Step 2: Create conftest.py**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/tests/conftest.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegraf"))
```

(Adiciona o diretório `telegraf/` ao sys.path para que `import credentials` funcione nos testes sem instalar o pacote.)

- [ ] **Step 3: Write the first failing test**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/tests/test_credentials.py`:

```python
import pytest

from credentials import Domain, load_domains_from_env


def test_loads_single_domain_with_all_vars(monkeypatch):
    monkeypatch.setenv("UTM_DOMAINS", "dom1")
    monkeypatch.setenv("UTM_dom1_HOST", "10.0.0.10")
    monkeypatch.setenv("UTM_dom1_USER", "monitoring")
    monkeypatch.setenv("UTM_dom1_PASS", "s3cret")
    monkeypatch.setenv("UTM_dom1_GROUP", "production")

    domains = load_domains_from_env()

    assert domains == [
        Domain(
            id="dom1",
            host="10.0.0.10",
            user="monitoring",
            password="s3cret",
            group="production",
        )
    ]
```

- [ ] **Step 4: Run test, confirm it fails**

Run:
```fish
cd /home/lucgomes/Downloads/ucs_traffic_monitor
.venv/bin/pytest tests/test_credentials.py -v
```

Expected: FAIL com `ModuleNotFoundError: No module named 'credentials'`.

- [ ] **Step 5: Commit the failing test**

```fish
git add tests/__init__.py tests/conftest.py tests/test_credentials.py
git commit -m "Add failing test for credentials.load_domains_from_env happy path

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Implement Domain dataclass and happy path

**Files:**
- Create: `telegraf/credentials.py`

- [ ] **Step 1: Write minimal implementation**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/telegraf/credentials.py`:

```python
"""Load UCS domain credentials from environment variables.

Replaces the legacy plaintext file-based configuration. The script
reads three required env vars per domain plus one optional group label.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Domain:
    id: str
    host: str
    user: str
    password: str
    group: str


def load_domains_from_env(
    env: Mapping[str, str] | None = None,
) -> list[Domain]:
    if env is None:
        env = os.environ

    raw = env.get("UTM_DOMAINS", "")
    ids = [item.strip() for item in raw.split(",") if item.strip()]
    if not ids:
        sys.stderr.write(
            "UTM_DOMAINS is empty or unset; set UTM_DOMAINS to a "
            "comma-separated list of domain ids.\n"
        )
        raise SystemExit(2)

    domains: list[Domain] = []
    for domain_id in ids:
        host = env.get(f"UTM_{domain_id}_HOST")
        user = env.get(f"UTM_{domain_id}_USER")
        password = env.get(f"UTM_{domain_id}_PASS")
        group = env.get(f"UTM_{domain_id}_GROUP", "default")

        missing = [
            name
            for name, value in (
                (f"UTM_{domain_id}_HOST", host),
                (f"UTM_{domain_id}_USER", user),
                (f"UTM_{domain_id}_PASS", password),
            )
            if not value
        ]
        if missing:
            sys.stderr.write(
                f"Missing required environment variables for domain "
                f"'{domain_id}': {', '.join(missing)}\n"
            )
            raise SystemExit(2)

        domains.append(
            Domain(
                id=domain_id,
                host=host,
                user=user,
                password=password,
                group=group,
            )
        )

    return domains
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```fish
.venv/bin/pytest tests/test_credentials.py::test_loads_single_domain_with_all_vars -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```fish
git add telegraf/credentials.py
git commit -m "Implement credentials.load_domains_from_env (happy path)

Adds isolated module that reads UTM_DOMAINS plus per-domain
HOST/USER/PASS/GROUP env vars and returns frozen Domain dataclasses.
SystemExit(2) on missing required variables.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Test — UTM_DOMAINS unset

**Files:**
- Modify: `tests/test_credentials.py`

- [ ] **Step 1: Add failing test**

Append to `/home/lucgomes/Downloads/ucs_traffic_monitor/tests/test_credentials.py`:

```python
def test_exits_when_utm_domains_unset(monkeypatch, capsys):
    monkeypatch.delenv("UTM_DOMAINS", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        load_domains_from_env({})

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "UTM_DOMAINS" in captured.err
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```fish
.venv/bin/pytest tests/test_credentials.py::test_exits_when_utm_domains_unset -v
```

Expected: PASS (já implementado em Task 3).

- [ ] **Step 3: Commit**

```fish
git add tests/test_credentials.py
git commit -m "Test: SystemExit(2) when UTM_DOMAINS is unset or empty

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Test — UTM_DOMAINS empty string

**Files:**
- Modify: `tests/test_credentials.py`

- [ ] **Step 1: Add test**

Append:

```python
def test_exits_when_utm_domains_empty_string(monkeypatch, capsys):
    monkeypatch.setenv("UTM_DOMAINS", "")

    with pytest.raises(SystemExit) as exc_info:
        load_domains_from_env()

    assert exc_info.value.code == 2
    assert "UTM_DOMAINS" in capsys.readouterr().err
```

- [ ] **Step 2: Run test**

```fish
.venv/bin/pytest tests/test_credentials.py::test_exits_when_utm_domains_empty_string -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```fish
git add tests/test_credentials.py
git commit -m "Test: SystemExit(2) when UTM_DOMAINS is empty string

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Test — missing per-domain variables

**Files:**
- Modify: `tests/test_credentials.py`

- [ ] **Step 1: Add test**

Append:

```python
def test_exits_when_per_domain_vars_missing(monkeypatch, capsys):
    monkeypatch.setenv("UTM_DOMAINS", "dom1")
    monkeypatch.setenv("UTM_dom1_HOST", "10.0.0.10")
    monkeypatch.setenv("UTM_dom1_USER", "monitoring")
    monkeypatch.delenv("UTM_dom1_PASS", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        load_domains_from_env()

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "UTM_dom1_PASS" in err
    assert "UTM_dom1_HOST" not in err
    assert "UTM_dom1_USER" not in err
```

- [ ] **Step 2: Run test**

```fish
.venv/bin/pytest tests/test_credentials.py::test_exits_when_per_domain_vars_missing -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```fish
git add tests/test_credentials.py
git commit -m "Test: error message lists only missing per-domain env vars

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Test — error messages do not leak secret values

**Files:**
- Modify: `tests/test_credentials.py`

- [ ] **Step 1: Add test**

Append:

```python
def test_error_message_does_not_leak_existing_values(monkeypatch, capsys):
    secret_value = "super-secret-password-12345"
    monkeypatch.setenv("UTM_DOMAINS", "dom1,dom2")
    monkeypatch.setenv("UTM_dom1_HOST", "10.0.0.10")
    monkeypatch.setenv("UTM_dom1_USER", "monitoring")
    monkeypatch.setenv("UTM_dom1_PASS", secret_value)
    # dom2 missing all vars

    with pytest.raises(SystemExit):
        load_domains_from_env()

    err = capsys.readouterr().err
    assert secret_value not in err
    assert "10.0.0.10" not in err
    assert "monitoring" not in err
```

- [ ] **Step 2: Run test**

```fish
.venv/bin/pytest tests/test_credentials.py::test_error_message_does_not_leak_existing_values -v
```

Expected: PASS (current implementation only logs variable names, not values).

- [ ] **Step 3: Commit**

```fish
git add tests/test_credentials.py
git commit -m "Test: error messages must not leak existing credential values

Codifies the no-leak invariant as a regression test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Test — whitespace tolerance in UTM_DOMAINS

**Files:**
- Modify: `tests/test_credentials.py`

- [ ] **Step 1: Add test**

Append:

```python
def test_whitespace_in_utm_domains_is_tolerated(monkeypatch):
    monkeypatch.setenv("UTM_DOMAINS", "  dom1 , dom2,  dom3  ")
    for domain_id in ("dom1", "dom2", "dom3"):
        monkeypatch.setenv(f"UTM_{domain_id}_HOST", f"10.0.0.{domain_id[-1]}")
        monkeypatch.setenv(f"UTM_{domain_id}_USER", "u")
        monkeypatch.setenv(f"UTM_{domain_id}_PASS", "p")

    domains = load_domains_from_env()

    assert [d.id for d in domains] == ["dom1", "dom2", "dom3"]
```

- [ ] **Step 2: Run test**

```fish
.venv/bin/pytest tests/test_credentials.py::test_whitespace_in_utm_domains_is_tolerated -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```fish
git add tests/test_credentials.py
git commit -m "Test: whitespace around domain ids is stripped

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Test — group defaults to "default"

**Files:**
- Modify: `tests/test_credentials.py`

- [ ] **Step 1: Add test**

Append:

```python
def test_group_defaults_to_default_when_unset(monkeypatch):
    monkeypatch.setenv("UTM_DOMAINS", "dom1")
    monkeypatch.setenv("UTM_dom1_HOST", "10.0.0.10")
    monkeypatch.setenv("UTM_dom1_USER", "u")
    monkeypatch.setenv("UTM_dom1_PASS", "p")
    monkeypatch.delenv("UTM_dom1_GROUP", raising=False)

    domains = load_domains_from_env()

    assert domains[0].group == "default"
```

- [ ] **Step 2: Run test**

```fish
.venv/bin/pytest tests/ -v
```

Expected: TODOS os 7 testes passam.

- [ ] **Step 3: Run lint**

```fish
.venv/bin/ruff check telegraf/credentials.py tests/
.venv/bin/ruff format --check telegraf/credentials.py tests/
```

Expected: nenhum issue. Se houver, rode `.venv/bin/ruff check --fix` e `.venv/bin/ruff format`, depois commit separado.

- [ ] **Step 4: Commit**

```fish
git add tests/test_credentials.py
git commit -m "Test: GROUP defaults to 'default' when env var is unset

Closes the test suite for credentials.load_domains_from_env.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Wire credentials.py into ucs_traffic_monitor.py

### Task 10: Add --instance-name CLI flag (replacement for INPUT_FILE_PREFIX)

**Files:**
- Modify: `telegraf/ucs_traffic_monitor.py:31-32` (constants)
- Modify: `telegraf/ucs_traffic_monitor.py:142-183` (parse_cmdline_arguments)
- Modify: `telegraf/ucs_traffic_monitor.py:197` (logfile name)
- Modify: `telegraf/ucs_traffic_monitor.py:319, 617, 652` (pickle file names)

`INPUT_FILE_PREFIX` derivava do nome do `.txt` para separar instâncias (group_1 vs group_2 → log files distintos, pickle files distintos). Substituímos por flag `--instance-name`, default `utm`.

- [ ] **Step 1: Replace INPUT_FILE_PREFIX with INSTANCE_NAME constant**

Em `telegraf/ucs_traffic_monitor.py`, troque a linha 32:

De:
```python
INPUT_FILE_PREFIX = ''
```

Para:
```python
INSTANCE_NAME = 'utm'
```

- [ ] **Step 2: Update parse_cmdline_arguments**

Em `parse_cmdline_arguments` (linhas 142-183), faça as seguintes mudanças:

a) **Remova** o argumento posicional `input_file` (linhas 144-145):
```python
parser.add_argument('input_file', action='store', help='file containing \
                the UCS domain information in the format: IP,user,password')
```

b) **Adicione** novos argumentos antes de `args = parser.parse_args()`:
```python
parser.add_argument('--instance-name', dest='instance_name', default='utm',
                help='Logical name for this instance, used as suffix for log '
                     'files and pickle files (default: utm)')
```

c) **Remova** as duas linhas que populam `user_args['input_file']` e o bloco `global INPUT_FILE_PREFIX` (linhas 171 e 182-183):
```python
user_args['input_file'] = args.input_file
...
global INPUT_FILE_PREFIX
INPUT_FILE_PREFIX = ((((user_args['input_file']).split('/'))[-1]).split('.'))[0]
```

d) **Substitua** por:
```python
user_args['instance_name'] = args.instance_name
global INSTANCE_NAME
INSTANCE_NAME = args.instance_name
```

- [ ] **Step 3: Replace INPUT_FILE_PREFIX in logfile/pickle names**

Substituir todas as ocorrências de `INPUT_FILE_PREFIX` por `INSTANCE_NAME`:

- Linha 197 (`setup_logging`):
  ```python
  logfile_name = logfile_prefix + '_' + INPUT_FILE_PREFIX + '.log'
  ```
  → 
  ```python
  logfile_name = logfile_prefix + '_' + INSTANCE_NAME + '.log'
  ```

- Linhas 319, 617, 652:
  ```python
  pickle_file_name = FILENAME_PREFIX + '_' + INPUT_FILE_PREFIX + '.pickle'
  ```
  →
  ```python
  pickle_file_name = FILENAME_PREFIX + '_' + INSTANCE_NAME + '.pickle'
  ```

- [ ] **Step 4: Smoke check — script imports without error**

Run:
```fish
.venv/bin/python -c "import sys; sys.path.insert(0, 'telegraf'); import ucs_traffic_monitor"
```

Expected: sem erro (pode haver warnings de ucsmsdk se não instalado, mas o módulo deve importar). Se faltar `ucsmsdk` no venv:
```fish
.venv/bin/pip install ucsmsdk
```

- [ ] **Step 5: Smoke check — argparse aceita --instance-name e rejeita arquivo posicional**

Run:
```fish
.venv/bin/python telegraf/ucs_traffic_monitor.py --help
```

Expected: help output mostra `--instance-name` e **não** mostra `input_file` posicional. `output_format` posicional ainda aparece.

```fish
.venv/bin/python telegraf/ucs_traffic_monitor.py influxdb-lp --instance-name testname 2>&1 | head -5
```

Expected: o argparse aceita os args (depois pode falhar pq UTM_DOMAINS não está setado, mas argparse passou).

- [ ] **Step 6: Commit**

```fish
git add telegraf/ucs_traffic_monitor.py
git commit -m "Replace INPUT_FILE_PREFIX with --instance-name flag

Removes the positional input_file argument; adds --instance-name
(default: utm) which preserves multi-instance log/pickle file
separation without coupling to a config file path.

BREAKING CHANGE: callers must update their telegraf exec config
to use --instance-name instead of passing the credentials file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Replace get_ucs_domains body with credentials.load_domains_from_env

**Files:**
- Modify: `telegraf/ucs_traffic_monitor.py:6-19` (imports)
- Modify: `telegraf/ucs_traffic_monitor.py:219-286` (get_ucs_domains)

Mantemos a função `get_ucs_domains()` e o formato de `domain_dict[ip] = [user, password]` para evitar mudar todos os consumers. Trocamos só o que está dentro da função.

- [ ] **Step 1: Add import for credentials module**

Em `telegraf/ucs_traffic_monitor.py`, no bloco de imports (depois da linha 19), adicione:

```python
import credentials
```

(Como `credentials.py` está no mesmo diretório `telegraf/`, o import funciona quando o script é invocado diretamente.)

- [ ] **Step 2: Replace get_ucs_domains body**

Substitua a função inteira (linhas 219-286) por:

```python
def get_ucs_domains():
    """
    Load UCS domain credentials from environment variables and initialize
    the global state structures (domain_dict, stats_dict, conn_dict,
    response_time_dict).

    Credentials are read by the credentials module from env vars:
    UTM_DOMAINS=dom1,dom2,...
    UTM_<id>_HOST, UTM_<id>_USER, UTM_<id>_PASS, UTM_<id>_GROUP (optional)

    Exits with code 2 (via SystemExit raised by credentials module) if
    required env vars are missing.

    Parameters:
    None

    Returns:
    None
    """
    global domain_dict

    domains = credentials.load_domains_from_env()

    for domain in domains:
        ip = domain.host
        domain_dict[ip] = [domain.user, domain.password]
        logger.info('Added {} to domain dict'.format(ip))

        stats_dict[ip] = {}
        stats_dict[ip]['location'] = domain.group
        stats_dict[ip]['A'] = {}
        stats_dict[ip]['A']['fi_ports'] = {}
        stats_dict[ip]['B'] = {}
        stats_dict[ip]['B']['fi_ports'] = {}
        stats_dict[ip]['chassis'] = {}
        stats_dict[ip]['ru'] = {}
        stats_dict[ip]['fex'] = {}

        conn_dict[ip] = {}

        response_time_dict[ip] = {}
        response_time_dict[ip]['cli_start'] = 0
        response_time_dict[ip]['cli_login'] = 0
        response_time_dict[ip]['cli_end'] = 0
        response_time_dict[ip]['sdk_start'] = 0
        response_time_dict[ip]['sdk_login'] = 0
        response_time_dict[ip]['sdk_end'] = 0
```

Note: o atributo `location` em `stats_dict[ip]` agora recebe `domain.group` (era a string entre colchetes no antigo `.txt`). Comportamento equivalente — `[US]` virou `UTM_dom1_GROUP=US`.

- [ ] **Step 3: Smoke check — without env vars, get_ucs_domains exits with code 2**

Cria um script de teste manual:
```fish
.venv/bin/python -c "
import sys
sys.path.insert(0, 'telegraf')
import os
for k in list(os.environ):
    if k.startswith('UTM_'):
        del os.environ[k]
from credentials import load_domains_from_env
try:
    load_domains_from_env()
except SystemExit as e:
    print(f'Exited with code {e.code}')
"
```

Expected: imprime `Exited with code 2` + mensagem de UTM_DOMAINS unset.

- [ ] **Step 4: Smoke check — with env vars, get_ucs_domains succeeds**

```fish
env UTM_DOMAINS=dom1 \
    UTM_dom1_HOST=10.0.0.99 \
    UTM_dom1_USER=u \
    UTM_dom1_PASS=p \
    .venv/bin/python -c "
import sys
sys.path.insert(0, 'telegraf')
import ucs_traffic_monitor as utm
utm.get_ucs_domains()
print('domain_dict:', utm.domain_dict)
print('location:', utm.stats_dict['10.0.0.99']['location'])
"
```

Expected: imprime `domain_dict: {'10.0.0.99': ['u', 'p']}` e `location: default`.

- [ ] **Step 5: Run full test suite**

```fish
.venv/bin/pytest tests/ -v
```

Expected: 7 testes passam (mesmos de antes).

- [ ] **Step 6: Commit**

```fish
git add telegraf/ucs_traffic_monitor.py
git commit -m "Wire credentials.load_domains_from_env into get_ucs_domains

Function signature unchanged; consumers still see domain_dict in the
same shape. Internal source switched from plaintext file parsing to
environment variables. The location field is now sourced from
UTM_<id>_GROUP (default: 'default').

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Tooling around the change

### Task 12: Migration script

**Files:**
- Create: `scripts/migrate_credentials.py`

Lê o `.txt` antigo e gera um `creds.env` no formato esperado.

- [ ] **Step 1: Create script**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/scripts/migrate_credentials.py`:

```python
#!/usr/bin/env python3
"""Migrate legacy ucs_domains_group_*.txt to env-var creds.env.

Reads the old plaintext format:

    [location_name]
    192.168.1.1,admin,passwd
    192.168.1.2,admin,passwd

Emits an env file:

    UTM_DOMAINS=dom1,dom2
    UTM_dom1_HOST=192.168.1.1
    UTM_dom1_USER=admin
    UTM_dom1_PASS=passwd
    UTM_dom1_GROUP=location_name
    ...

The operator is expected to:
  1. Run this script once.
  2. Set chmod 600 and chown telegraf:telegraf on the output file.
  3. Validate the new deployment.
  4. After 24-48h, shred the original plaintext file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def shell_quote(value: str) -> str:
    """Quote a value for inclusion in a systemd EnvironmentFile.

    EnvironmentFile uses POSIX-shell-like quoting. We single-quote and
    escape any embedded single quotes.
    """
    escaped = value.replace("'", "'\\''")
    return f"'{escaped}'"


def parse_legacy_file(path: Path) -> list[tuple[str, str, str, str]]:
    """Parse the old format. Returns list of (host, user, password, group)."""
    domains = []
    location = "default"

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            if not line.endswith("]"):
                sys.stderr.write(f"Malformed location line: {raw_line!r}\n")
                sys.exit(1)
            location = line[1:-1].strip() or "default"
            continue
        parts = line.split(",")
        if len(parts) < 3:
            sys.stderr.write(f"Skipping malformed line: {raw_line!r}\n")
            continue
        host, user, password = parts[0].strip(), parts[1].strip(), parts[2].strip()
        domains.append((host, user, password, location))

    return domains


def emit_env_file(domains: list[tuple[str, str, str, str]], out_path: Path) -> None:
    if not domains:
        sys.stderr.write("No domains found in input file. Aborting.\n")
        sys.exit(1)

    ids = [f"dom{i + 1}" for i in range(len(domains))]
    lines = [f"UTM_DOMAINS={','.join(ids)}", ""]
    for domain_id, (host, user, password, group) in zip(ids, domains):
        lines.append(f"UTM_{domain_id}_HOST={shell_quote(host)}")
        lines.append(f"UTM_{domain_id}_USER={shell_quote(user)}")
        lines.append(f"UTM_{domain_id}_PASS={shell_quote(password)}")
        lines.append(f"UTM_{domain_id}_GROUP={shell_quote(group)}")
        lines.append("")

    out_path.write_text("\n".join(lines))
    out_path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                        help="Path to legacy ucs_domains_group_*.txt")
    parser.add_argument("--output", required=True, type=Path,
                        help="Path to write the new creds.env")
    args = parser.parse_args()

    if not args.input.exists():
        sys.stderr.write(f"Input file not found: {args.input}\n")
        sys.exit(1)

    domains = parse_legacy_file(args.input)
    emit_env_file(domains, args.output)

    print(f"Wrote {len(domains)} domain(s) to {args.output}")
    print()
    print("Next steps:")
    print(f"  sudo chown telegraf:telegraf {args.output}")
    print(f"  sudo chmod 600 {args.output}  # already done by script, but verify")
    print(f"  Validate the service, then: sudo shred -u {args.input}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test the migration script**

Run on the existing example file:
```fish
.venv/bin/python scripts/migrate_credentials.py \
    --input telegraf/ucs_domains_group_1.txt \
    --output /tmp/test-creds.env

cat /tmp/test-creds.env
```

Expected: o arquivo `/tmp/test-creds.env` é criado. Como o `ucs_domains_group_1.txt` só tem entradas comentadas, deve abortar com "No domains found" — isso é correto.

Faça um teste positivo:
```fish
printf '[Production]\n10.0.0.10,admin,p@ss w0rd\n10.0.0.11,admin,otherpass\n' > /tmp/legacy-test.txt
.venv/bin/python scripts/migrate_credentials.py \
    --input /tmp/legacy-test.txt \
    --output /tmp/test-creds.env

cat /tmp/test-creds.env
```

Expected output:
```
UTM_DOMAINS=dom1,dom2

UTM_dom1_HOST='10.0.0.10'
UTM_dom1_USER='admin'
UTM_dom1_PASS='p@ss w0rd'
UTM_dom1_GROUP='Production'

UTM_dom2_HOST='10.0.0.11'
UTM_dom2_USER='admin'
UTM_dom2_PASS='otherpass'
UTM_dom2_GROUP='Production'
```

Verify chmod 600:
```fish
stat -c '%a' /tmp/test-creds.env
```

Expected: `600`.

Cleanup:
```fish
rm /tmp/legacy-test.txt /tmp/test-creds.env
```

- [ ] **Step 3: Commit**

```fish
git add scripts/migrate_credentials.py
git commit -m "Add scripts/migrate_credentials.py for legacy file migration

One-shot tool that converts the old plaintext format to the new
env-var creds.env. Uses POSIX-style single-quote escaping so passwords
containing spaces or special characters survive the round trip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: systemd unit example

**Files:**
- Create: `systemd/utm.service.example`

- [ ] **Step 1: Create unit file**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/systemd/utm.service.example`:

```ini
# UCS Traffic Monitor — example systemd unit
# Copy to /etc/systemd/system/utm.service and adjust paths.
#
# This unit assumes:
#  - The script lives at /opt/utm/ucs_traffic_monitor.py
#  - Credentials are in /etc/utm/creds.env (chmod 600, owner telegraf)
#  - Output goes to telegraf via stdout (configure telegraf exec accordingly)
#
# For the SOPS-based fork deployment, use:
#  - EnvironmentFile=/run/utm/creds.env  (tmpfs, regenerated each boot)
#  - After=utm-creds.service
#  - Requires=utm-creds.service

[Unit]
Description=UCS Traffic Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=telegraf
Group=telegraf
EnvironmentFile=/etc/utm/creds.env
ExecStart=/usr/bin/python3 /opt/utm/ucs_traffic_monitor.py influxdb-lp --instance-name utm
Restart=on-failure
RestartSec=30s

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/telegraf

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Validate syntax with systemd-analyze (if available)**

Run:
```fish
systemd-analyze verify systemd/utm.service.example 2>&1 || echo "(systemd-analyze unavailable or strict mode failed; non-blocking)"
```

Expected: sem erros graves. Warnings sobre `EnvironmentFile` ou `ReadWritePaths` paths não existentes são esperados — esse arquivo é template.

- [ ] **Step 3: Commit**

```fish
git add systemd/utm.service.example
git commit -m "Add systemd/utm.service.example with hardening defaults

Reference unit using EnvironmentFile for credentials. Includes
NoNewPrivileges, PrivateTmp, ProtectSystem=strict for defense in depth.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Update README

**Files:**
- Modify: `README.md`

A seção "Configuration" do README atual descreve o formato `.txt`. Reescrevê-la para env vars + apontar para o script de migração.

- [ ] **Step 1: Replace the Configuration section (README.md lines 72-92)**

A seção atual (`## Configuration` até o fim do bloco ```` ```shell ```` que mostra o telegraf.conf) descreve o arquivo `ucs_domains_group*.txt` e usa `input_file` posicional no exemplo do telegraf. Substitua o trecho exato das linhas 72-92 pela seguinte versão (mantém o nível `##`):

```markdown
## Configuration

UCS Traffic Monitor reads credentials from environment variables (no
plaintext file is read at runtime).

### Required environment variables

```sh
# Comma-separated list of logical domain ids
UTM_DOMAINS=dom1,dom2

# Per-domain credentials
UTM_dom1_HOST=10.0.0.10
UTM_dom1_USER=monitoring
UTM_dom1_PASS=secret-password

# Optional grouping label (default: "default")
UTM_dom1_GROUP=production
```

### Recommended deployment

Place credentials in `/etc/utm/creds.env`:

```sh
sudo install -d -m 0700 -o telegraf -g telegraf /etc/utm
sudo install -m 0600 -o telegraf -g telegraf /dev/null /etc/utm/creds.env
sudo $EDITOR /etc/utm/creds.env
```

Use the provided `systemd/utm.service.example` and reference the env
file with `EnvironmentFile=/etc/utm/creds.env`.

For multi-instance deployments (previously `ucs_domains_group_1.txt` and
`ucs_domains_group_2.txt`), pass `--instance-name <name>` to keep log
files and pickle caches separate per instance.

### Telegraf exec input

```toml
[[inputs.exec]]
   interval = "60s"
   commands = [
       "python3 /usr/local/telegraf/ucs_traffic_monitor.py influxdb-lp --instance-name utm -vv",
   ]
   timeout = "50s"
   data_format = "influx"
```

When telegraf invokes the script, it inherits the environment from
its systemd unit. Add `EnvironmentFile=/etc/utm/creds.env` to the
telegraf systemd drop-in (or use a wrapper systemd service that
exports the vars before exec'ing telegraf).

### Migrating existing deployments

If you already have `ucs_domains_group_*.txt` files, use the migration
helper:

```sh
sudo python3 scripts/migrate_credentials.py \
    --input /etc/telegraf/ucs_domains_group_1.txt \
    --output /etc/utm/creds.env
sudo chown telegraf:telegraf /etc/utm/creds.env
sudo chmod 600 /etc/utm/creds.env
```

After validating the new deployment runs cleanly for 24-48h, securely
delete the legacy file:

```sh
sudo shred -u /etc/telegraf/ucs_domains_group_1.txt
```
```

- [ ] **Step 3: Commit**

```fish
git add README.md
git commit -m "Update README: document env-var configuration and migration

Replaces the legacy plaintext-file instructions with env-var setup,
hardened install commands (chmod 700/600, telegraf ownership), and a
migration walkthrough using scripts/migrate_credentials.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create workflow**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main, master]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e .[dev]

      - name: Lint with ruff
        run: |
          ruff check telegraf/credentials.py tests/ scripts/
          ruff format --check telegraf/credentials.py tests/ scripts/

      - name: Run tests
        run: pytest tests/ -v
```

Note: o lint roda só nos arquivos novos (`credentials.py`, `tests/`, `scripts/`). O monolito legado fica fora — está no `per-file-ignores` do ruff e fora do CI por enquanto.

- [ ] **Step 2: Validate YAML locally**

Run:
```fish
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" 2>&1 || echo "PyYAML not installed — skipping local validation"
```

Expected: sem erro de parsing (ou nota dizendo que pyyaml não está instalado, o que é OK).

- [ ] **Step 3: Commit**

```fish
git add .github/workflows/ci.yml
git commit -m "Add GitHub Actions CI: pytest + ruff on Python 3.10/3.11/3.12

Lint runs only on new module + tests + scripts. The legacy monolith
remains exempt via pyproject per-file-ignores until a focused
refactoring effort.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: Final upstream PR validation

- [ ] **Step 1: Run full test suite**

```fish
.venv/bin/pytest tests/ -v
```

Expected: 7 testes passam.

- [ ] **Step 2: Run lint**

```fish
.venv/bin/ruff check telegraf/credentials.py tests/ scripts/
.venv/bin/ruff format --check telegraf/credentials.py tests/ scripts/
```

Expected: zero issues.

- [ ] **Step 3: Verify final shape of upstream branch**

```fish
git log --oneline master..HEAD  # ou main..HEAD dependendo do branch
git diff --stat master..HEAD
```

Expected: ~14 commits, alterações concentradas em:
- `pyproject.toml` (novo)
- `.gitignore` (modificado)
- `tests/` (3 arquivos novos)
- `telegraf/credentials.py` (novo)
- `telegraf/ucs_traffic_monitor.py` (modificado, ~50 linhas trocadas)
- `scripts/migrate_credentials.py` (novo)
- `systemd/utm.service.example` (novo)
- `README.md` (modificado)
- `.github/workflows/ci.yml` (novo)

**Fim da Phase 4 = ponto de corte para o PR upstream.** A partir daqui, Tasks 17-20 são fork-only.

---

## Phase 5 — Fork-only: SOPS layer

> Tasks 17-20 NÃO entram no PR upstream. Implementar em branch separado do fork interno.

### Task 17: SOPS config and example encrypted yaml

**Files:**
- Create: `secrets/.sops.yaml`
- Create: `secrets/credentials.sops.yaml.example`

- [ ] **Step 1: Verify sops and age are installed**

```fish
sops --version
age --version
```

Se não estiverem instalados:
```fish
sudo pacman -S sops age   # Arch/CachyOS
```

- [ ] **Step 2: Generate example age key (DON'T USE IN PRODUCTION)**

Crie um keypair de exemplo:
```fish
mkdir -p /tmp/utm-bootstrap
age-keygen -o /tmp/utm-bootstrap/example-age.key
grep '^# public key:' /tmp/utm-bootstrap/example-age.key
```

Copie a public key (algo como `age1xyz...`) — você vai usar no .sops.yaml a seguir.

- [ ] **Step 3: Create .sops.yaml**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/secrets/.sops.yaml`:

```yaml
# SOPS configuration for UTM credentials.
#
# Replace the example public key below with your real age public key.
# The matching private key (used for decryption at boot) lives at
# /etc/utm/age.key on the production VM and MUST be excluded from backups.

creation_rules:
  - path_regex: secrets/credentials\.sops\.yaml$
    encrypted_regex: '^(password)$'
    age: age1exampleexampleexampleexampleexampleexampleexampleexamplexyz0
```

`encrypted_regex: '^(password)$'` faz com que SOPS cifre apenas os campos `password`. `host`, `user`, `group` ficam em claro — útil para diff e operação.

- [ ] **Step 4: Create example yaml structure**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/secrets/credentials.sops.yaml.example`:

```yaml
# Example structure of credentials.sops.yaml (BEFORE SOPS encryption).
#
# To create the real file:
#   1. Copy this to credentials.sops.yaml
#   2. Replace placeholders with real values
#   3. Encrypt: sops -e -i credentials.sops.yaml
#
# The "password" field will be encrypted in place; the rest stays
# readable for operational diffs.

domains:
  dom1:
    host: 10.0.0.10
    user: monitoring
    password: REPLACE_WITH_REAL_PASSWORD
    group: production
  dom2:
    host: 10.0.0.20
    user: monitoring
    password: REPLACE_WITH_REAL_PASSWORD
    group: production
```

- [ ] **Step 5: Cleanup the temp key**

```fish
rm -rf /tmp/utm-bootstrap
```

- [ ] **Step 6: Commit**

```fish
git add secrets/.sops.yaml secrets/credentials.sops.yaml.example
git commit -m "Add SOPS+age config and example credentials yaml structure

Defines per-field encryption (only 'password' is encrypted, leaving
host/user/group in cleartext for operational diffs). The age public
key in .sops.yaml is a placeholder — replace with a real key during
bootstrap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 18: SOPS decryption helper script

**Files:**
- Create: `bin/utm-decrypt-creds.sh`

- [ ] **Step 1: Create the script**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/bin/utm-decrypt-creds.sh`:

```bash
#!/usr/bin/env bash
#
# Decrypt UTM credentials and write /run/utm/creds.env atomically.
#
# Reads:
#   /etc/utm/credentials.sops.yaml  (SOPS-encrypted YAML)
#   /etc/utm/age.key                (age private key, chmod 600)
#
# Writes:
#   /run/utm/creds.env              (chmod 600, owner telegraf:telegraf)
#
# Run by utm-creds.service oneshot before utm.service starts.

set -euo pipefail

SOPS_INPUT="/etc/utm/credentials.sops.yaml"
AGE_KEY="/etc/utm/age.key"
OUT_DIR="/run/utm"
OUT_FILE="${OUT_DIR}/creds.env"
TMP_FILE="${OUT_FILE}.tmp.$$"

if [[ ! -f "${SOPS_INPUT}" ]]; then
    echo "ERROR: ${SOPS_INPUT} not found" >&2
    exit 1
fi

if [[ ! -f "${AGE_KEY}" ]]; then
    echo "ERROR: ${AGE_KEY} not found" >&2
    exit 1
fi

mkdir -p "${OUT_DIR}"
chmod 0700 "${OUT_DIR}"
chown telegraf:telegraf "${OUT_DIR}"

# Decrypt to a YAML stream, then convert to KEY=VALUE.
# We use Python (stdlib only) to avoid an extra yq dependency.
SOPS_AGE_KEY_FILE="${AGE_KEY}" \
    sops -d "${SOPS_INPUT}" | python3 - <<'PY' > "${TMP_FILE}"
import sys
import yaml

data = yaml.safe_load(sys.stdin)
domains = data.get("domains", {})

ids = list(domains.keys())
print(f"UTM_DOMAINS={','.join(ids)}")
print()

for domain_id, fields in domains.items():
    for key, env_suffix in (
        ("host", "HOST"),
        ("user", "USER"),
        ("password", "PASS"),
        ("group", "GROUP"),
    ):
        value = fields.get(key, "")
        # Single-quote escape for systemd EnvironmentFile.
        escaped = str(value).replace("'", "'\\''")
        print(f"UTM_{domain_id}_{env_suffix}='{escaped}'")
    print()
PY

chmod 0600 "${TMP_FILE}"
chown telegraf:telegraf "${TMP_FILE}"
mv "${TMP_FILE}" "${OUT_FILE}"

echo "Wrote ${OUT_FILE}"
```

- [ ] **Step 2: Make it executable**

```fish
chmod +x bin/utm-decrypt-creds.sh
```

- [ ] **Step 3: Smoke test (without SOPS)**

Como precisamos de SOPS + age key + arquivo cifrado pra testar de verdade, esse smoke test fica para a etapa de bootstrap on-VM. Aqui só validamos sintaxe:

```fish
bash -n bin/utm-decrypt-creds.sh && echo "syntax OK"
```

Expected: `syntax OK`.

E que o script Python embutido também é válido:
```fish
.venv/bin/python -c "
import yaml
data = {'domains': {'dom1': {'host': '10.0.0.1', 'user': 'u', 'password': 'p', 'group': 'g'}}}
ids = list(data['domains'].keys())
print(f\"UTM_DOMAINS={','.join(ids)}\")
"
```

Expected: `UTM_DOMAINS=dom1`.

- [ ] **Step 4: Commit**

```fish
git add bin/utm-decrypt-creds.sh
git commit -m "Add bin/utm-decrypt-creds.sh for boot-time SOPS decryption

Reads /etc/utm/credentials.sops.yaml, decrypts via age key at
/etc/utm/age.key, emits /run/utm/creds.env atomically. Uses
PyYAML stdin pipeline to avoid an extra yq dependency.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 19: utm-creds.service unit

**Files:**
- Create: `systemd/utm-creds.service`

- [ ] **Step 1: Create unit**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/systemd/utm-creds.service`:

```ini
# Decrypt UTM credentials at boot.
# Install to /etc/systemd/system/utm-creds.service.
#
# Pairs with utm.service which has:
#   After=utm-creds.service
#   Requires=utm-creds.service
#   EnvironmentFile=/run/utm/creds.env

[Unit]
Description=Decrypt UTM credentials (SOPS+age)
After=local-fs.target
Before=utm.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/utm-decrypt-creds.sh
ExecStop=/bin/rm -f /run/utm/creds.env

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/run/utm

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Validate syntax**

```fish
systemd-analyze verify systemd/utm-creds.service 2>&1 || echo "(non-fatal warnings expected — paths don't exist on dev host)"
```

Expected: sem erros fatais.

- [ ] **Step 3: Commit**

```fish
git add systemd/utm-creds.service
git commit -m "Add systemd/utm-creds.service oneshot for SOPS decryption

Runs once at boot before utm.service. Hardened with NoNewPrivileges,
PrivateTmp, ProtectSystem=strict; ReadWritePaths limited to /run/utm.
ExecStop wipes the decrypted creds on shutdown.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 20: SOPS_SETUP.md operator documentation

**Files:**
- Create: `docs/SOPS_SETUP.md`

- [ ] **Step 1: Create operator guide**

Create `/home/lucgomes/Downloads/ucs_traffic_monitor/docs/SOPS_SETUP.md`:

```markdown
# SOPS-based credentials setup (fork-only)

This guide covers the optional SOPS+age layer used in the internal
fork. Upstream users can stop at the env-var configuration described
in the main README.

## Why this layer exists

VM snapshots in this deployment go to external backup storage. A
plaintext `creds.env` on disk would leak credentials in any captured
snapshot. SOPS+age encrypts credentials in a YAML committable to git;
the matching private key lives only on the production VM and is
explicitly excluded from backups.

## Bootstrap (one-time per environment)

### 1. Install SOPS and age

```sh
# Arch / CachyOS
sudo pacman -S sops age

# Debian / Ubuntu (>=22.04)
sudo apt install sops age
```

### 2. Generate the age key on the VM

```sh
sudo install -d -m 0700 /etc/utm
sudo age-keygen -o /etc/utm/age.key
sudo chmod 600 /etc/utm/age.key
sudo chown root:root /etc/utm/age.key
```

Capture the public key:

```sh
sudo grep '^# public key:' /etc/utm/age.key
# example: # public key: age1xyz...
```

### 3. Update the repo's .sops.yaml

Edit `secrets/.sops.yaml` and replace the placeholder public key
with the one captured in the previous step. Commit and push.

### 4. Create the encrypted credentials file

On a workstation with the age private key (or directly on the VM):

```sh
cp secrets/credentials.sops.yaml.example secrets/credentials.sops.yaml
$EDITOR secrets/credentials.sops.yaml   # fill in real values

# Encrypt in place
sops -e -i secrets/credentials.sops.yaml

# Verify the password fields became ENC[...]
grep password secrets/credentials.sops.yaml
```

Commit `credentials.sops.yaml` to the repo. The cleartext form of
the file should never be committed.

### 5. Deploy on the VM

```sh
sudo install -d -m 0700 -o root -g root /etc/utm
sudo cp secrets/credentials.sops.yaml /etc/utm/credentials.sops.yaml
sudo cp bin/utm-decrypt-creds.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/utm-decrypt-creds.sh
sudo cp systemd/utm-creds.service /etc/systemd/system/
sudo cp systemd/utm.service.example /etc/systemd/system/utm.service
# Edit utm.service: change EnvironmentFile to /run/utm/creds.env
# Add After=utm-creds.service and Requires=utm-creds.service under [Unit]
sudo systemctl daemon-reload
sudo systemctl enable --now utm-creds.service utm.service
sudo systemctl status utm.service
```

### 6. Exclude age.key from backups

Coordinate with the infrastructure team to add `/etc/utm/age.key` to
the backup exclusion list of the agent that snapshots this VM. This
is the single most important step — without it, the encrypted YAML
is no more secure than a plaintext file.

## Routine operations

### Rotate a UCS password

```sh
sops /etc/utm/credentials.sops.yaml   # opens decrypted in $EDITOR
# Change the password, save, exit.
sudo systemctl restart utm-creds.service utm.service
```

### Add a new domain

```sh
sops /etc/utm/credentials.sops.yaml
# Add a new entry under "domains:"
sudo systemctl restart utm-creds.service utm.service
```

### Recover from a lost age key

If `/etc/utm/age.key` is destroyed and not backed up elsewhere
(intended), the only path forward is:

1. Generate a new age key on the VM.
2. Re-encrypt `credentials.sops.yaml` with the new public key on
   a workstation that still has access to the old key (e.g., via
   another team member's copy).
3. If no one has the old key: re-create `credentials.sops.yaml`
   from scratch with current credentials, encrypt with the new key,
   commit.

This is the trade-off for keeping the key out of backups.

## Verification

```sh
# Confirm /run/utm/creds.env exists and is mode 600 owned by telegraf
sudo stat /run/utm/creds.env

# Confirm the file is on tmpfs (not on disk)
mount | grep '/run '

# Confirm utm.service started after utm-creds.service
sudo systemctl list-dependencies utm.service
```
```

- [ ] **Step 2: Commit**

```fish
git add docs/SOPS_SETUP.md
git commit -m "Add docs/SOPS_SETUP.md operator guide

Covers bootstrap (age key, sops config, encryption), deployment on
the VM, routine ops (rotation, adding domains), recovery from a lost
age key, and verification. Emphasizes excluding /etc/utm/age.key
from backups as the single most critical hardening step.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 21: Final fork validation

- [ ] **Step 1: Re-run full test suite**

```fish
.venv/bin/pytest tests/ -v
```

Expected: 7 testes passam.

- [ ] **Step 2: Re-run lint**

```fish
.venv/bin/ruff check telegraf/credentials.py tests/ scripts/
.venv/bin/ruff format --check telegraf/credentials.py tests/ scripts/
```

Expected: zero issues.

- [ ] **Step 3: Verify shape of fork branch**

```fish
git log --oneline master..HEAD
```

Expected: ~20 commits cobrindo Phase 1-5.

- [ ] **Step 4: Final smoke test**

Crie um creds.env temporário mimicando o que o decrypt script geraria, e dispare o script principal em modo `--verify-only`:

```fish
mkdir -p /tmp/utm-smoke
cat > /tmp/utm-smoke/creds.env <<EOF
UTM_DOMAINS=smoke
UTM_smoke_HOST=192.0.2.1
UTM_smoke_USER=u
UTM_smoke_PASS=p
UTM_smoke_GROUP=test
EOF
chmod 600 /tmp/utm-smoke/creds.env

env $(cat /tmp/utm-smoke/creds.env | xargs) \
    .venv/bin/python telegraf/ucs_traffic_monitor.py influxdb-lp \
    --instance-name smoke -V 2>&1 | head -20
```

Expected: o script tenta conectar em 192.0.2.1 (TEST-NET-1, vai falhar por timeout, é esperado), mas o load das credenciais pelas env vars deve completar sem erro.

Cleanup:
```fish
rm -rf /tmp/utm-smoke
```

---

## Self-review notes

Spec coverage:
- ✅ `Domain` dataclass + `load_domains_from_env()` (Tasks 3-9)
- ✅ Refactor de `ucs_traffic_monitor.py` (Tasks 10-11)
- ✅ `systemd/utm.service.example` (Task 13)
- ✅ `scripts/migrate_credentials.py` (Task 12)
- ✅ `tests/test_credentials.py` cobrindo todos os 7 casos do spec (Tasks 2-9)
- ✅ `pyproject.toml` (Task 1)
- ✅ `.github/workflows/ci.yml` (Task 15)
- ✅ `README.md` reescrito (Task 14)
- ✅ `secrets/.sops.yaml` + example (Task 17)
- ✅ `bin/utm-decrypt-creds.sh` (Task 18)
- ✅ `systemd/utm-creds.service` (Task 19)
- ✅ `docs/SOPS_SETUP.md` (Task 20)

Tratamento de erros do spec coberto:
- ✅ UTM_DOMAINS unset/empty → SystemExit(2) (Tasks 4-5)
- ✅ Per-domain var faltante → SystemExit(2), lista vars sem valores (Tasks 6-7)
- ✅ Atomic write em decrypt script (Task 18, usa `mv` no fim)
- ✅ Erros não vazam segredos (Task 7)

Itens deliberadamente fora de escopo:
- Hot-reload, healthcheck, multi-backend abstraction (alinhado com Non-Goals do spec).
- Refactor do monolito (Non-Goals).

## Next step (after this plan)

Conforme o spec, o próximo item de roadmap é **consolidar `upgrade_utm.sh` + `backup_utm_bashboards.sh`** (item #3 do punch list de segurança) — fecha o capítulo de segurança crítica antes de tocar em modernização (Grafana 7→10).
