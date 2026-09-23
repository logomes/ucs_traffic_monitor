# Port para `feat/prod-rollout-grafana-12`

O coletor da `master` e o da `feat/prod-rollout-grafana-12` divergem: a
segunda lê credenciais de `/etc/utm/creds.env` e é invocada com
`influxdb-lp --instance-name utm`. As correções deste PR foram feitas sobre a
`master`; `prod-rollout-grafana-12.mbox` é a mesma série portada para a outra
branch, porque promover o coletor da `master` numa produção em modo env quebra
a coleta (o argparse exige o arquivo de domínios).

Contra o coletor original da `prod-rollout`, `test_quick_fixes.py` dá 0/16:
F1, F2, F4, F5 e F11 estão todos lá.

## Aplicar

```sh
git checkout -b quick-fixes origin/feat/prod-rollout-grafana-12
git am docs/refactor/patches/prod-rollout-grafana-12.mbox   # a partir de um checkout desta branch
```

São 12 commits. Os 4 primeiros e os 6 últimos são os mesmos deste PR, com um
conflito trivial resolvido (`.gitignore`) e o merge de 3 vias do coletor
limpo. Dois são próprios do port:

- **Disable setuptools package discovery** — bug pré-existente: o
  `pip install -e .[dev]` do CI aborta na branch original com
  "Multiple top-level packages discovered in a flat-layout". O CI só dispara
  em push para main/master e em PR, o que explica ninguém ter visto.
- **Require netmiko 4.4+** — o `pyproject.toml` da branch declara
  `netmiko>=4.0`, que não importa em Python 3.13+ (o CI testa só até 3.12).
  Inclui `ruff --fix` + `ruff format` no arquivo de teste, para as regras da
  branch.

## Verificado

CI completo da branch no resultado: install, `ruff check`, `ruff format
--check`, pytest (23 passed em 3.10, 3.12 e 3.13), shellcheck e bats (13/13).
`git am` numa cópia limpa da branch reproduz o port byte a byte.
