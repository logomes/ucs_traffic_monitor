# Correções pontuais — RFC seção 9

Status das cinco correções propostas para aplicação imediata, antes de
qualquer refatoração estrutural. Todas são de baixo risco e independentes
entre si.

| # | Correção | Onde | Status |
|---|---|---|---|
| 1 | F5 — variável de loop vazada | `telegraf/ucs_traffic_monitor.py` | ✅ aplicada |
| 2 | F1/F2 — contenção do `.pickle` | `telegraf/ucs_traffic_monitor.py` | ✅ código / ⚠️ ação na VM |
| 3 | F11 — cleanup com `--no-ssh` | `telegraf/ucs_traffic_monitor.py` | ✅ aplicada |
| 4 | F6/H1 — auditoria de intervalos | `tools/audit_stats_interval.py` | ✅ ferramenta / ⚠️ rodar na VM |
| 5 | F4 — métrica de saúde | `telegraf/ucs_traffic_monitor.py` | ✅ aplicada |

Nenhuma altera o formato das séries existentes. O único dado novo é a
medição `UTMCollectorHealth`.

---

## 1. F5 — lookup no dicionário errado

`print_output_in_influxdb_lp()` consultava `per_ru_dict` (variável de loop
vazada) em vez de `ru_dict`. Corrigido, e o peer passou a usar um nome
próprio (`peer_ru_dict`) para não sobrescrever a variável do loop externo.

**Impacto medido.** Numa topologia com blades, chassi e um FEX cuja porta de
backplane tem peer rack-unit, com `ru` vazio:

```
original:  0 linhas   (UnboundLocalError — ciclo inteiro perdido)
corrigido: 7 linhas
```

Em domínios sem esse gatilho o output é byte a byte idêntico ao anterior
(verificado com 6 linhas em fixture com chassi, blade, portas e uplink).

## 2. F1/F2 — contenção do `.pickle`

O `.pickle` carrega usuário e senha do UCS em texto claro, porque o
`UcsHandle` guarda ambos como atributos de instância. E `pickle.load()`
executa código vindo do arquivo que lê.

**No código:**

- `open_pickle_file_for_write()` cria o arquivo com `0600` via `os.open` e
  aplica `os.fchmod` para apertar um arquivo pré-existente com modo frouxo.
- `pickle_file_is_safe_to_load()` recusa carregar um arquivo que não seja do
  usuário atual (ou root) ou que seja gravável por grupo/outros. Nesse caso
  o coletor começa sem sessões salvas em vez de carregar algo não confiável.

Antes: o arquivo nascia `0644` — legível por qualquer conta da VM, com a
senha dentro. Confirmado em execução ponta a ponta.

**⚠️ Ação pendente na VM** — o código protege arquivos novos, mas não apaga
os antigos:

```sh
# 1. Confirmar o problema (H3)
sudo strings /usr/local/telegraf/ucs_traffic_monitor_*.pickle | grep -i -A2 passw

# 2. Parar o telegraf antes de mexer
sudo systemctl stop telegraf

# 3. Apagar de forma irrecuperável
sudo shred -u /usr/local/telegraf/ucs_traffic_monitor_*.pickle

# 4. Subir de novo — o coletor recria com 0600
sudo systemctl start telegraf
sudo stat -c '%a %U:%G %n' /usr/local/telegraf/ucs_traffic_monitor_*.pickle
```

Se o passo 1 mostrar a senha, **trate-a como comprometida**: ela esteve
legível em todo snapshot e backup da VM. Rode a troca no UCSM.

A remoção definitiva do `pickle` é a Fase 1 do RFC.

## 3. F11 — cleanup que quebrava justo no caminho de erro

`cleanup_ucs_connections()` fazia `handles['cli']` e chamava `.disconnect()`
sem checagem. Com `--no-ssh` a chave `cli` nunca é criada (`KeyError`), e com
login falho o handle é `None` (`AttributeError`). Corrigido com `.get()`,
checagem de `None` e `try/except` por handle — uma sessão que falha ao
fechar não impede as dos outros domínios de fecharem.

## 4. F6/H1 — auditoria dos três intervalos

`tools/audit_stats_interval.py` compara lado a lado:

```
 intervalo da stats collection policy do UCSM   (por tipo de stat)
     ==  intervalo do inputs.exec do Telegraf
     ==  variável [[polling_interval]] do dashboard
```

Se divergirem, todo painel de banda está fora de escala pelo fator mostrado.

**⚠️ Rodar na VM:**

```sh
python3 tools/audit_stats_interval.py \
    -i /usr/local/telegraf/ucs_domains_group_1.txt \
    -t /etc/telegraf/telegraf.conf \
    -d grafana/dashboards/domain_traffic.json
```

Sai 0 se tudo bate, 1 se diverge. Com `--no-ucs` roda offline e reporta só
o lado local.

Já verificado neste repositório: **os dashboards assumem 60 s**
(`[[polling_interval]]` = 60 em 7 dos 9; `local_sys` e `welcome` não usam).
Falta confirmar a policy do UCSM — é o lado que ninguém checou.

A correção durável é F6 na Fase 2: ler `timeCollected`/`intervals` dos MOs
e exportar taxa real, tirando a aritmética do dashboard.

## 5. F4 — métrica de saúde da coleta

`print_collector_health()` emite uma linha por domínio ao final de **todo**
ciclo, inclusive quando ele falha:

```
UTMCollectorHealth,domain=10.0.0.1 success=1i,sdk_ok=1i,cli_ok=1i,cli_skipped=0i,output_ok=1i,run_duration=12.5,collector_ver="0.52"
```

`success=0` distingue "coleta falhou" de "porta sem tráfego" — hoje ambos
aparecem no Grafana simplesmente como série ausente.

Junto, `update_stats_dict()` passou a ser chamada dentro de `try/except`,
como `get_ucs_stats()` e `print_output()` já eram. Antes, uma exceção de
parsing matava o processo, o que perdia o ciclo de todos os domínios **e**
pulava `pickle_connections()`, deixando as sessões UCS abertas até expirarem.

A linha só carrega a tag `domain` (um IP), que não precisa de escape de Line
Protocol — deliberadamente não inclui `location`, que é texto livre e cairia
no F3, ainda não corrigido.

**Alertas que isso habilita:**

```sql
-- Domínio sem coleta bem-sucedida
SELECT last("success") FROM "UTMCollectorHealth" GROUP BY domain
```

---

## Pré-requisito: a máquina consegue rodar o coletor?

```sh
python3 tools/preflight.py
```

Checa versão de Python, `ucsmsdk`, `netmiko` e a sintaxe do coletor. Não altera
nada. Sai 0 se o host está apto.

**Por que importa:** netmiko abaixo de 4.4.0 importa o `telnetlib` da stdlib,
que o **Python 3.13 removeu**. O playbook deste repositório fixava
`netmiko==4.0.0`, então um host em Python 3.13+ que seguiu o playbook **não
consegue nem importar o coletor** — morre no startup com `ModuleNotFoundError`
e não produz métrica nenhuma. Corrige com:

```sh
python3 -m pip install -U 'netmiko>=4.4.0'
```

Verificado: netmiko 4.2.0 e 4.3.0 falham no 3.13; 4.4.0 e 4.8.0 passam.
`ucsmsdk` 0.9.27 importa sem problema.

## Verificação

```sh
python3 tests/test_quick_fixes.py      # 16/16
```

Validado em Python 3.11 e 3.13. O coletor e as ferramentas não usam sintaxe
posterior ao 3.6, então rodam em toda a faixa 3.6 → 3.13+.

Os testes importam o coletor real com `ucsmsdk`/`netmiko` stubados, então não
precisam de UCS nem de dependências externas. Para provar que pegam os bugs,
rode-os contra o código anterior:

```sh
git show <commit-anterior>:telegraf/ucs_traffic_monitor.py > /tmp/old.py
UTM_COLLECTOR=/tmp/old.py python3 tests/test_quick_fixes.py   # 0/16
```
