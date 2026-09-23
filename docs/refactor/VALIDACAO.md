# Validação das correções na VM de produção

Roteiro para validar as cinco correções pontuais (RFC seção 9) no host real e
trazer os resultados para análise. **Nada aqui altera a produção**: não escreve
em `/usr/local/telegraf`, não mexe no `telegraf.conf` e não reinicia serviço.

## Os dois modos de credencial

O pacote traz o coletor corrigido nas duas variantes que existem no fork, e o
script detecta sozinho qual a produção usa:

| Modo | Origem | Credenciais | Invocação no Telegraf |
|---|---|---|---|
| `file` | `master` / upstream | `ucs_domains_group_*.txt` | `ucs_traffic_monitor.py <arquivo> influxdb-lp` |
| `env` | `feat/credentials-env-vars` → `feat/prod-rollout-grafana-12` | `/etc/utm/creds.env` | `ucs_traffic_monitor.py influxdb-lp --instance-name utm` |

Promover a variante errada quebra a coleta: o argparse de cada uma rejeita a
invocação da outra.

## Passo 0 — o host consegue rodar o coletor?

```sh
cd ~ && tar xzf utm-validacao.tar.gz && cd utm-validacao    # fora de /tmp: /tmp/utm-validacao é a saída
python3 tools/preflight.py
```

Use **o mesmo Python que o Telegraf usa** — o primeiro termo do `commands` no
bloco `inputs.exec`. Se for um venv, rode com ele (`/opt/utm-venv/bin/python
tools/preflight.py`).

O ponto que costuma falhar em Python 3.13+ é o `netmiko`: abaixo de 4.4.0 ele
importa o `telnetlib`, removido no 3.13, e o coletor morre no startup sem
produzir métrica. Conserto:

```sh
python3 -m pip install -U 'netmiko>=4.4.0'
```

No SUSE, se o pip recusar com `externally-managed-environment`, use venv:

```sh
sudo python3 -m venv /opt/utm-venv
sudo /opt/utm-venv/bin/pip install -U ucsmsdk 'netmiko>=4.4.0'
```

e troque `python3` por `/opt/utm-venv/bin/python` no `telegraf.conf` quando
for promover.

## Passo 1 — coleta automática

```sh
sudo ./tools/collect_validation.sh
less /tmp/utm-validacao/relatorio.txt
```

O script descobre sozinho, a partir do `telegraf.conf`: o Python, o usuário do
Telegraf, o modo de credencial, o arquivo de domínios ou o `creds.env`, e o
dashboard. Qualquer um pode ser forçado por variável — ver o cabeçalho do
script.

O relatório tem, nesta ordem:

| Seção | O que prova | Esperado |
|---|---|---|
| 0 | contexto: SO, Python, Telegraf, modo | — |
| 1 | preflight com o Python e o usuário do Telegraf | OK |
| 2 | integridade do pacote (`MANIFEST.sha256`) | confere |
| 3 | testes contra o coletor **de produção** | **0/16** — os bugs estão ativos |
| 4 | testes contra o coletor **novo** | **16/16** |
| 5 | F1: senha em texto claro no `.pickle` | sem senha, idealmente |
| 6 | F6: intervalo do Telegraf e do dashboard | 60 s e 60 s |
| 7 | F6: stats collection policy do UCSM | igual ao 6 |
| 8 | saída real antes × depois, em cópias isoladas | só `UTMCollectorHealth` a mais |
| 9 | resumo | — |

A seção 8 roda **cópias** dos dois coletores como o usuário do Telegraf, com
instância própria (`validacao_antes`, `validacao_depois`), então não encosta no
pickle nem no log de produção. Ela abre uma sessão por domínio no UCSM e faz
logout no fim (`-dss`). Os logs que cria são listados no relatório e podem ser
apagados.

A seção 8 também passa as duas saídas pelo `tools/lp_lint.py`, que aponta
linhas de Line Protocol que o Telegraf rejeitaria (achado F3) — por exemplo uma
`location`/`GROUP` com espaço, como `DC São Paulo`.

## Antes de enviar o relatório

- IPs saem mascarados (`IP-1`, `IP-2`…) de forma consistente. `MASCARAR=0`
  desliga.
- **Nenhuma senha vai para o relatório**: a verificação do pickle compara bytes
  e imprime só sim/não, e a leitura do `creds.env` nunca passa por linha de
  comando.
- Nomes de service profile e descrições de porta podem aparecer na seção 8
  (séries antes/depois). Mascare o que não quiser expor — não atrapalha.

## Se a seção 5 disser SIM

A senha esteve legível em todo snapshot e backup da VM. Trate como
comprometida:

1. troque a senha do usuário de monitoração no UCSM;
2. atualize `creds.env` (ou o `.txt`);
3. `sudo systemctl stop telegraf && sudo shred -u /usr/local/telegraf/*.pickle && sudo systemctl start telegraf`.

## Só depois do relatório analisado: promover

Não promova antes. Quando for, o coletor certo é
`coletor/modo-<file|env>/ucs_traffic_monitor.py` (o relatório diz qual), com
backup do atual e o `patches/` como referência do que mudou.
