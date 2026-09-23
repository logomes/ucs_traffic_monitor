# RFC — Análise técnica e refatoração do UCS Traffic Monitor (UTM)

**Data:** 2026-09-20
**Status:** Proposta para revisão
**Autor:** lucgomes
**Alvo da análise:** `telegraf/ucs_traffic_monitor.py` v0.52 (2.960 linhas), stack de runtime e dashboards
**Relacionado:** `docs/superpowers/specs/2026-04-25-utm-credentials-design.md` (credenciais — aprovado, incorporado como Fase 1)

---

## 0. Metodologia

Toda afirmação deste documento é **verificada**, não inferida. Os achados da Parte I foram confirmados por um destes três meios, indicados em cada item:

- **[código]** — leitura direta com referência `arquivo:linha`
- **[PoC]** — reprodução executável do defeito, com o código real extraído do projeto
- **[medido]** — contagem/medição sobre o repositório

Achados não confirmados aparecem separados na seção 5 como **hipóteses a validar em campo** — não estão misturados aos fatos.

---

## 1. Sumário executivo

O UTM resolve um problema que nenhuma ferramenta de mercado resolve pronta: correlação end-to-end de vNIC/vHBA até a porta de uplink da FI. Esse valor está intacto e deve ser preservado integralmente.

O que a análise mostra, porém, é que o projeto tem **defeitos de correção de dado e de disponibilidade que não são visíveis em operação** — nenhum deles gera erro na tela, todos degradam silenciosamente. Não são consequência de código "antigo": são consequência estrutural de três escolhas (estado global mutável, serialização manual de Line Protocol por concatenação de strings, e ausência de isolamento de falha entre domínios).

Sete achados confirmados, três deles críticos:

| # | Achado | Sev. | Prova |
|---|---|---|---|
| F1 | O arquivo `.pickle` contém a senha do UCS **em texto claro** | Crítica | PoC |
| F2 | `pickle.load()` de arquivo gravável = execução de código arbitrário | Crítica | código |
| F3 | Injeção de Line Protocol via descrição de porta do UCSM | Crítica | PoC |
| F4 | Uma exceção em qualquer ponto do output descarta o ciclo inteiro, de **todos** os domínios | Alta | código |
| F5 | `UnboundLocalError` real em `print_output_in_influxdb_lp()` (variável de loop vazada) | Alta | código |
| F6 | Taxa de banda depende de 3 configurações não sincronizadas — erro silencioso de escala | Alta | código |
| F7 | `iom_slot_id` vaza entre iterações → contadores de PAUSE atribuídos ao IOM errado | Alta | código |

Mais quatro de severidade média (F8–F11, seção 4).

A proposta é reescrita incremental por *strangler pattern*, com **harness de paridade como critério de aceite bloqueante** em cada passo. Estimativa: ~14 semanas-pessoa em 6 fases entregáveis de forma independente. Há também 5 correções pontuais (seção 8) que valem mesmo que o RFC inteiro seja recusado.

---

# PARTE I — ANÁLISE

## 2. Perfil do código **[medido]**

```
2.960  linhas em um único arquivo
   26  declarações `global`
    0  type hints
    0  testes
    0  arquivos de CI
  141  chamadas `.format()`  vs  6 f-strings
  308  ramos `if`/`elif`
   15  blocos `except Exception` genéricos
```

Cinco funções concentram 1.170 linhas (40 % do arquivo):

| Função | Linhas | Responsabilidades acumuladas |
|---|---|---|
| `print_output_in_influxdb_lp()` | 332 | percorre 5 hierarquias, resolve peers, monta tags, serializa, imprime |
| `parse_fi_stats()` | 250 | 11 class IDs, FC + Ethernet + port-channels |
| `parse_backplane_port_stats()` | 225 | correlação IOM ↔ FI ↔ VIF |
| `parse_pfc_stats()` | 198 | parsing de saída NX-OS |
| `parse_raw_sdk_stats()` | 165 | dispatcher por `class_id` |

Os números por si só são só dívida técnica. O que importa é o que eles **causam** — a seção 3.

---

## 3. Achados críticos e altos

### F1 — O `.pickle` armazena a senha do UCS em texto claro **[PoC]**

`pickle_connections()` (`telegraf/ucs_traffic_monitor.py:631`) serializa `conn_dict`, que contém objetos `UcsHandle`. O `UcsSession.__init__` guarda a senha como atributo de instância:

```python
# ucsmsdk/ucssession.py
def __init__(self, ip, username, password, ...):
    self.__ip = ip
    self.__username = username
    self.__password = password        # ← vai junto no pickle
```

Reprodução executada com o `ucsmsdk` real:

```python
>>> h = UcsHandle('10.1.1.1', 'svc_utm_ro', 'SuperSecret123!')
>>> blob = pickle.dumps(h)
>>> b'SuperSecret123!' in blob
True
>>> [s for s in re.findall(rb'[ -~]{8,}', blob) if b'Secret' in s or b'svc_utm' in s]
[b'svc_utm_ro', b'SuperSecret123!']
```

**Impacto:** o `.pickle` fica no diretório de trabalho do Telegraf, entra em snapshot de VM e em backup para storage externo — exatamente o vetor que a spec de credenciais (`2026-04-25`) existe para fechar. **Migrar as credenciais para env vars sem remover o `pickle` não resolve o problema**: a senha continua sendo escrita em disco a cada 60 segundos.

Verificação na VM de produção:

```sh
sudo strings /usr/local/telegraf/ucs_traffic_monitor_*.pickle | grep -A2 -i 'passw'
```

**Correção:** eliminar o `pickle` (ADR-06). É pré-requisito da Fase 1, não item opcional.

---

### F2 — `pickle.load()` em arquivo gravável é execução de código arbitrário **[código]**

`unpickle_connections()` (`:288-340`) faz `pickle.load()` sobre um caminho derivado de `FILENAME_PREFIX + '_' + INPUT_FILE_PREFIX + '.pickle'`, relativo ao diretório de trabalho do processo Telegraf. `pickle` executa `__reduce__` durante a desserialização — por construção, quem escreve no arquivo executa código como o usuário do Telegraf.

Agravante: o tratamento de erro de `pickle.load()` só captura `EOFError` e `Exception`; um payload malicioso *bem-formado* não gera erro nenhum.

**Correção:** mesma de F1 — remover. Enquanto não for removido: `chmod 600` e dono restrito ao usuário do Telegraf.

---

### F3 — Injeção de Line Protocol via descrição de porta do UCSM **[PoC]**

Todo o Line Protocol é construído por concatenação de strings, **sem nenhum escape**. O caso mais grave está em `:2563`:

```python
fi_port_fields = fi_port_fields + \
    'admin_state="' + per_fi_port_dict['admin_state'] + '",' + \
    'description="' + per_fi_port_dict['name'] + '",' + \   # ← sem escape
    'oper_speed=' + (str)(per_fi_port_dict['oper_speed']) + ',' + \
    'oper_state="' + (str)(per_fi_port_dict['oper_state']) + '"'
```

`per_fi_port_dict['name']` vem de `fill_fi_port_common_items()` (`:721`), cujo próprio comentário diz: `# name carries description`. É o campo de **descrição da porta, editável por qualquer administrador do UCSM**, que aceita espaços, vírgulas, aspas e barras.

Reprodução com a construção de linha real do projeto:

```
=== 1. descrição normal ===
FIUplinkPortStats,domain=10.1.1.1,fi_id=A,...  description="Uplink para Nexus 93180 Po10",...

=== 2. descrição com aspas — linha malformada ===
... description="link "backup"",oper_speed=10,...

=== 3. injeção: descrição = 'x",fake=1\nFIUplinkPortStats,... bytes_rx_delta=999999999i\nz="'
FIUplinkPortStats,domain=10.1.1.1,... description="x",fake=1
FIUplinkPortStats,domain=10.1.1.1,fi_id=A,port=99/99 bytes_rx_delta=999999999i   ← linha forjada
z="",oper_speed=10,oper_state="up"
--- linhas geradas: 3 (esperado: 1)
```

**Impacto, em ordem de probabilidade:**

1. **Disponibilidade (provável hoje):** basta uma descrição de porta com aspas para produzir linha malformada. O Telegraf descarta a linha; dependendo do parser, a rejeição pode atingir o lote.
2. **Integridade:** um administrador do UCSM pode escrever métricas arbitrárias na TSDB — medições falsas, tags forjadas, valores inventados. O UTM vira canal de escrita não autenticado para a TSDB.
3. **Cardinalidade:** tags injetadas explodem o índice do InfluxDB.

O mesmo defeito, em menor grau, atinge `,location=` (`:2508`), alimentado pelo texto entre `[` `]` do arquivo de entrada. Um `[Sao Paulo DC1]` gera `location=Sao Paulo DC1` — o espaço **termina o conjunto de tags** no Line Protocol e quebra a linha. O `README` não documenta essa restrição.

**Correção:** serialização por biblioteca, nunca por concatenação (`influxdb-client` / `line-protocol`), ou função de escape única aplicada a todo valor de tag e field string. Na arquitetura-alvo isso vira responsabilidade exclusiva de `exporters/`.

---

### F4 — Nenhum isolamento de falha: uma exceção derruba o ciclo inteiro **[código]**

Duas decisões estruturais se combinam:

1. `print_output_in_influxdb_lp()` acumula **tudo** em `final_print_string` e executa **um único `print()`** na linha `:2810`, fora do loop de domínios que começa em `:2490`.
2. Em `main()` (`:2839`), `update_stats_dict()` é chamada **sem `try/except`** — diferente de `get_ucs_stats()` e `print_output()`, que têm.

Consequências:

- Qualquer exceção em qualquer ponto das 332 linhas do output → `print()` nunca executa → **Telegraf recebe stdout vazio → zero métricas para todos os domínios daquele grupo naquele ciclo**.
- Qualquer exceção no parsing → processo morre → além de perder o ciclo, **`pickle_connections()` e `cleanup_ucs_connections()` não rodam** → sessões SDK/SSH ficam órfãs no UCSM.

O UCSM limita sessões por usuário (padrão 32). O ciclo vicioso é: degradação → exceção → sessões órfãs → esgotamento do limite → login recusado → apagão total de monitoração. E como não existe nenhuma métrica sobre a saúde da coleta, **isso é indistinguível de "as portas estão sem tráfego"** no Grafana.

**Correção:** isolamento por domínio (um `TaskGroup` por domínio, falha contida), *streaming* incremental do output em vez de acumulação, e meta-métricas sempre emitidas — inclusive, principalmente, em falha.

---

### F5 — `UnboundLocalError` confirmado no caminho de FEX **[código]**

`print_output_in_influxdb_lp()`, linhas `:2791-2797`:

```python
ru_dict = d_dict['ru']
ru_server = per_bp_port_dict['peer']
if ru_server in per_ru_dict:          # ← BUG: deveria ser `in ru_dict`
    per_ru_dict = ru_dict[ru_server]
    bp_tags = bp_tags + ',peer_service_profile=' + per_ru_dict['service_profile']
```

`per_ru_dict` é vinculado **somente** pelo loop da linha `:2711` (`for ru_id, per_ru_dict in ru_dict.items()`). No ponto `:2793` ele é uma variável de loop vazada. Dois modos de falha:

- **Domínio sem rack servers** (`d_dict['ru']` vazio — caso comum em ambiente só de blades): o loop de `:2711` nunca executa, `per_ru_dict` **nunca é vinculado** → `UnboundLocalError` → por F4, **o ciclo inteiro é perdido, para todos os domínios do grupo**.
- **Domínio com rack servers:** `per_ru_dict` contém o dicionário do *último* rack unit iterado (chaves `service_profile`, `adaptors`, …), não o dicionário indexado por nome. O teste `ru_server in per_ru_dict` é quase sempre falso → a tag `peer_service_profile` **nunca é emitida** para portas de backplane de FEX. Silencioso. E a linha `:2794` ainda **rebind** `per_ru_dict`, corrompendo as iterações seguintes.

Gatilho: domínio com FEX cuja porta de backplane tem `peer_type` conhecido e diferente de `S-chassis`.

**Correção imediata:** trocar `per_ru_dict` por `ru_dict` na linha `:2793`. Uma palavra.

---

### F6 — A taxa de banda depende de três configurações não sincronizadas **[código]**

Este é o achado mais importante para a **confiabilidade do dado**, e o menos visível.

O UTM **não calcula taxa**. Ele lê o delta que o próprio UCSM já computou (`:1436`, `:1462`, `:1474`, `:1704`, `:1843`, `:1855`):

```python
port_dict['bytes_rx_delta'] = item.bytes_rx_delta      # delta calculado pelo UCSM
port_dict['bytes_rx_delta'] = item.total_bytes_delta
```

Esse delta é computado pelo UCSM sobre **o intervalo da stat collection policy dele** — adapter, chassis, host, port e server têm políticas independentes, tipicamente 1 ou 2 minutos.

A conversão para bits/s acontece só no Grafana, e divide por uma **constante de dashboard**:

```sql
SELECT max("bytes_rx_delta")/[[polling_interval]] AS "RX"
FROM "FIUplinkPortStats" WHERE ... GROUP BY time([[__interval_ms]]ms),fi_id,port
```

(41 queries em `domain_traffic.json` usam `bytes_rx_delta` dessa forma.)

Ou seja, **todo número de largura de banda do UTM só está correto se três valores configurados de forma independente coincidirem**:

```
 intervalo da stat collection policy no UCSM   (configurado no UCSM, por tipo de stat)
                  ==
 intervalo do inputs.exec do Telegraf          (configurado em telegraf.conf)
                  ==
 variável [[polling_interval]] do dashboard    (configurada no Grafana)
```

Ninguém valida essa igualdade. Se a policy de `port` estiver em 2 min e `polling_interval` = 60, **todo gráfico de banda de uplink mostra o dobro do valor real** — sem erro, sem aviso, sem sintoma. O inverso (policy mais rápida que o scrape) descarta amostras.

Agravante: o UCSM expõe `timeCollected` e `intervals` nos próprios MOs de estatística. **O script não lê nenhum dos dois** — a informação necessária para normalizar corretamente está disponível e é ignorada.

**Correção:** o coletor lê `timeCollected`/`intervals`, normaliza para taxa por segundo na origem, e exporta bits/s. O dashboard deixa de ter aritmética. Some a classe inteira de erro. Ver `transform/rates.py` na seção 6.4.

---

### F7 — `iom_slot_id` vaza entre linhas → PAUSE atribuído ao IOM errado **[código]**

Em `parse_pfc_stats()`, `iom_slot_id = 0` é inicializado uma vez por chamada (`:2162`) e o bloco que o resolve aparece duplicado (`:2211` e `:2281`):

```python
for iom_slot, port_dict in bp_port_dict.items():
    for iom_port, per_bp_port_dict in port_dict.items():
        if per_bp_port_dict['fi_id'] == fi_id:
            iom_slot_id = iom_slot        # só atribui quando casa
        else:
            pass
        break
...
iom_slot_dict = bp_port_dict[iom_slot_id]   # KeyError se nada casou
```

`iom_slot_id` tem escopo de função e **só é atualizado quando encontra correspondência**. Duas falhas:

- **Primeira linha sem correspondência:** `iom_slot_id` continua `0` → `bp_port_dict[0]` → `KeyError` → por F4, processo morto, ciclo perdido, sessões órfãs.
- **Linha subsequente sem correspondência (pior):** `iom_slot_id` retém o valor da **linha anterior** → os contadores `pause_rx`/`pause_tx` daquela porta são gravados no **IOM errado**. Sem erro, sem log. Corrupção silenciosa exatamente nas dashboards de congestionamento (`chassis_pause.json`, `ingress_congestion.json`) — que são o caso de uso onde o dado precisa ser confiável.

**Correção:** resolver o slot em função pura que retorna `str | None`, tratar `None` explicitamente, e eliminar a duplicação.

**Nota de correção à primeira versão desta análise:** eu havia classificado `parse_pfc_stats()` como parser posicional por coluna. Está errado — ele usa `lines.split()` com guarda `len(line) < 5` e índices `line[-2]`/`line[-1]`, o que é razoavelmente robusto a mudanças de largura de coluna. O defeito real é o vazamento de `iom_slot_id`, acima.

---

## 4. Achados de severidade média

### F8 — `get_fi_id_from_dn()` confunde fabric por substring **[PoC]**

```python
def get_fi_id_from_dn(dn):          # :681
    if 'A' in dn: return 'A'
    elif 'B' in dn: return 'B'
```

Busca de substring em todo o DN, com `A` tendo precedência incondicional sobre `B`:

```
sys/switch-B/slot-1/switch-ether/port-1   -> B   ✓
fabric/lan/B/net-VLAN_A                   -> A   ✗  (é fabric B)
```

Qualquer DN que carregue rótulo definido pelo usuário contendo `A` maiúsculo é atribuído ao fabric errado. **Correção:** extrair o token de fabric por posição no DN ou por regex ancorada (`switch-([AB])/`).

### F9 — `isFloat()` valida com `float()` mas converte com `int()` **[PoC]**

```python
def get_speed_num_from_string(speed, item):    # :696
    if isFloat(speed):
        return (int)(speed)                     # ValueError para '10.5', 'nan', 'inf'
    ...
    return (int)(((str)(speed)).rstrip('gbps'))
```

```
'10.5' -> CRASH ValueError: invalid literal for int() with base 10: '10.5'
'nan'  -> CRASH
'inf'  -> CRASH
```

Por F4, essa exceção mata o ciclo. Segundo defeito na mesma função: `rstrip('gbps')` remove **caracteres do conjunto** `{g,b,p,s}`, não o sufixo — funciona por acaso para os valores atuais (`'10gbps'→'10'`), mas `'sgbps'` vira `''`. O correto é `removesuffix('gbps')`.

### F10 — Filtro de estado por substring: `'associated' in 'unassociated'` **[PoC]**

Nove ocorrências do padrão. A mais relevante, em `:2645` e `:2733`:

```python
if 'ok' not in per_blade_dict['oper_state'] or \
   'associated' not in per_blade_dict['association']:
    continue
```

`'associated' in 'unassociated'` é `True` — um blade **não associado** passa no teste de associação. Hoje isso está **mascarado** pela condição combinada: um blade não associado costuma ter `oper_state='unassociated'`, que falha no teste `'ok' not in ...`. Mas a proteção é acidental, não projetada: um blade com `oper_state='ok'` e `association='unassociated'` (estado possível durante/após desassociação, com o blade energizado e descoberto) passa pelo filtro e é emitido com o service profile residual.

**Correção:** comparação por igualdade contra `StrEnum`, nunca por substring.

### F11 — `cleanup_ucs_connections()` quebra com `--no-ssh` **[código]**

```python
for domain_ip, handles in conn_dict.items():    # :607
    cli_handle = handles['cli']                  # KeyError
    sdk_handle = handles['sdk']
    cli_handle.disconnect()                      # AttributeError se None
    sdk_handle.logout()
```

Em `connect_and_pull_stats()` (`:474`), o ramo `cli` faz `return` por causa de `--no-ssh` **antes** de atribuir `conn_dict[domain_ip]['cli']`. Com `--no-ssh` + `-dss`, a chave nunca existe → `KeyError`. E sem `None`-check, uma falha de login vira `AttributeError` — exatamente no caminho de limpeza, isto é, na hora em que já há um problema.

### F12 — A flag `-ct` não controla o que promete **[código]**

`-ct/--connection-timeout` é documentada como *"Total timeout in seconds for login/auth and metrics pull (Default:45s)"*, mas:

- é passada **apenas** ao netmiko: `ConnectHandler(..., timeout=user_args.get('conn_timeout'))` (`:418`)
- o login do SDK usa a constante `CONNECTION_TIMEOUT = 10`, hardcoded (`:435`)
- **`query_classids()` não tem timeout nenhum** (`:548`)

O *stats pull* do SDK — a operação mais cara do ciclo — não tem limite de tempo. O único limite efetivo é o `SIGKILL` do Telegraf aos 50 s, que é justamente o caminho que deixa sessões órfãs (F4). `MASTER_TIMEOUT = 48` (`:27`) só é usado para **logar um aviso depois do fato**, nunca para interromper nada.

---

## 5. Hipóteses a validar em campo (não confirmadas)

Explicitamente separadas dos achados acima — **não tratar como fato**:

- **H1:** as stat collection policies reais dos domínios divergem do `polling_interval` dos dashboards (F6 seria não apenas possível, mas ativo). Validar: `show stats-collection-policy detail` em cada domínio, comparar com `telegraf.conf` e com a variável do Grafana.
- **H2:** existem sessões órfãs acumuladas no UCSM hoje. Validar: `show system-session` / `scope security; show user-sessions detail`.
- **H3:** os `.pickle` em produção contêm credenciais (F1 prova que é assim por construção; falta confirmar na VM). Validar com o `strings` da seção F1.
- **H4:** a cardinalidade de séries por vNIC é alta o bastante para pesar no dimensionamento da TSDB. Validar: `SHOW SERIES CARDINALITY` no InfluxDB.

---

## 6. Stack de infraestrutura **[código]**

De `ansible-install/utm.yml`:

| Componente | Estado | Consequência |
|---|---|---|
| CentOS 7 | EOL desde 2024-06-30 | sem patches de segurança |
| Python 3.6 (base do CentOS 7) | EOL desde 2021-12 | força `pip==21.3.1` e `netmiko==4.0.0` |
| InfluxDB 1.x | linha em manutenção mínima | InfluxQL; upgrade não trivial |
| Grafana `10.1.10-1` | **fixado** | ver abaixo |

O pin do Grafana é o sintoma mais eloquente. O próprio playbook documenta o motivo:

```yaml
# 10.1.10-1 : OK
# 10.2.0-1  : Service Profile "None"
# 10.2.8-1  : UCS Traffic Monitoring - error parsing query: found [, expected identifier...
```

A causa raiz não é o Grafana: são **2,9 MB de JSON de dashboard editados pela UI** (o maior, `service_profile.json`, tem 842 KB), que não são revisáveis nem diffáveis. Sem dashboards como código, todo upgrade de Grafana vira teste de regressão manual de 9 dashboards — então ninguém atualiza.

Volume de log: `LOGFILE_SIZE = 20 MB × LOGFILE_NUMBER = 10`, por arquivo de entrada. Com os dois grupos do exemplo e o `-vv` (INFO) que o README recomenda, são até **400 MB de log rotativo** gerados a cada 60 s de operação.

---

# PARTE II — ARQUITETURA-ALVO

## 7. Princípio estrutural

Os sete achados críticos/altos têm três causas raiz, e cada uma tem uma fronteira arquitetural correspondente:

| Causa raiz | Achados | Fronteira que a elimina |
|---|---|---|
| Processo efêmero obriga persistir sessão em disco | F1, F2 | serviço long-running: sessão vive em memória |
| Serialização manual por concatenação de string | F3, F6 | `exporters/` é a **única** camada que conhece formato de saída |
| Estado global mutável sem isolamento de falha | F4, F5, F7 | `transform/` são funções puras sobre modelos imutáveis |

A regra é uma só: **`collectors/` faz I/O e nada mais; `transform/` não faz I/O e nada mais; `exporters/` serializa e nada mais.** Todo o valor intelectual do projeto — o stitching — passa a ser função pura sobre estruturas tipadas, testável com fixtures gravadas, sem UCSM.

```
┌──────────────────────────────────────────────────────────────────┐
│  utm-collector  (serviço asyncio long-running)                   │
│                                                                  │
│  runtime/scheduler.py   1 TaskGroup por domínio — falha contida  │
│  runtime/session.py     pool em memória, refresh, circuit breaker│
│                              ▼                                   │
│  collectors/            I/O puro → RawSnapshot (imutável)        │
│    ├─ ucsm_sdk.py       query_classids em executor dedicado      │
│    ├─ ucsm_cli.py       scrapli + asyncssh                       │
│    └─ intersight.py     [Fase 6, condicionado a validação]       │
│                              ▼                                   │
│  transform/             FUNÇÕES PURAS — 100 % testáveis          │
│    ├─ normalize.py      RawSnapshot → DomainSnapshot tipado      │
│    ├─ topology.py       stitching vNIC → VIF → backplane→uplink  │
│    └─ rates.py          delta UCSM + timeCollected → bits/s  (F6)│
│                              ▼                                   │
│  exporters/             ÚNICO lugar que serializa           (F3) │
│    ├─ prometheus.py     /metrics                                 │
│    ├─ influx_lp.py      Line Protocol com escape correto         │
│    └─ otlp.py                                                    │
│                                                                  │
│  observability/selfmetrics.py   saúde da coleta             (F4) │
└──────────────────────────────────────────────────────────────────┘
```

### 7.1 Modelo de domínio

```python
# src/utm/domain/models.py
from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from ipaddress import IPv4Address
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FabricId(StrEnum):
    A = "A"
    B = "B"


class Association(StrEnum):
    """Comparação por igualdade — nunca por substring (F10)."""

    ASSOCIATED = "associated"
    UNASSOCIATED = "unassociated"
    ASSOCIATING = "associating"
    REMOVING = "removing"
    FAILED = "failed"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DeltaSample(Frozen):
    """Delta calculado PELO UCSM, com o intervalo sobre o qual ele vale.

    `interval` é o que resolve F6: sem ele não há como converter o delta
    em taxa sem assumir que a stat collection policy do UCSM coincide com
    o intervalo de scrape — que é exatamente a suposição não validada de hoje.
    """

    delta: Annotated[int, Field(ge=0)]
    interval: timedelta          # de `intervals` / `timeCollected` do MO
    collected_at: datetime

    @property
    def per_second(self) -> float:
        seconds = self.interval.total_seconds()
        return self.delta / seconds if seconds > 0 else 0.0


class FiPort(Frozen):
    dn: str
    fabric: FabricId             # extraído por regex ancorada, não substring (F8)
    slot: int
    port: int
    aggr_port: int | None = None
    description: str = ""        # texto livre do UCSM — escape é do exporter (F3)
    admin_up: bool
    oper_up: bool
    speed_mbps: int | None = None
    peer_dn: str | None = None

    rx: DeltaSample | None = None
    tx: DeltaSample | None = None
    rx_pause: DeltaSample | None = None
    tx_pause: DeltaSample | None = None


class DomainSnapshot(Frozen):
    """Estado de um domínio em um instante. Unidade de troca entre camadas."""

    domain_ip: IPv4Address
    location: str
    ucsm_version: str
    collected_at: datetime
    collection_duration: timedelta

    ports: tuple[FiPort, ...] = ()
    blades: tuple[Blade, ...] = ()

    partial: bool = False
    errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _partial_requires_reason(self) -> Self:
        if self.partial and not self.errors:
            raise ValueError("snapshot parcial exige ao menos um erro registrado")
        return self
```

`partial` + `errors` é a resposta direta a F4: um snapshot degradado é **explicitamente** degradado. O exporter emite `utm_collection_partial{domain=...} 1` em vez de simplesmente omitir séries — e "coleta falhou" deixa de ser indistinguível de "sem tráfego".

### 7.2 Serialização — a correção de F3

Nenhum `+` monta Line Protocol. Um único ponto escapa, e é coberto por teste de propriedade:

```python
# src/utm/exporters/influx_lp.py
_TAG_ESCAPES = str.maketrans({",": r"\,", "=": r"\=", " ": r"\ "})
_STR_FIELD_ESCAPES = str.maketrans({'"': r"\"", "\\": r"\\"})


def escape_tag(value: str) -> str:
    """Tag key, tag value e measurement: escapar vírgula, igual e espaço."""
    return value.translate(_TAG_ESCAPES)


def escape_string_field(value: str) -> str:
    """Field string: escapar aspas e barra. Newline vira espaço — nunca
    pode chegar ao stream, que é delimitado por newline (F3)."""
    return value.replace("\n", " ").replace("\r", " ").translate(_STR_FIELD_ESCAPES)
```

```python
# tests/exporters/test_influx_lp.py
from hypothesis import given, strategies as st

@given(descr=st.text(min_size=0, max_size=200))
def test_arbitrary_port_description_never_breaks_the_line(descr: str) -> None:
    """F3: nenhuma descrição de porta pode gerar mais de uma linha."""
    port = make_port(description=descr)
    rendered = influx_lp.render_fi_port(port, domain="10.1.1.1", location="DC 1")
    assert rendered.count("\n") == 1, f"injeção de linha com descr={descr!r}"
```

### 7.3 Taxas normalizadas — a correção de F6

```python
# src/utm/transform/rates.py
from dataclasses import dataclass

from utm.domain.models import DeltaSample


@dataclass(frozen=True, slots=True)
class Rate:
    bits_per_second: float
    interval_s: float
    stale: bool


def to_rate(sample: DeltaSample | None, scrape_interval_s: float) -> Rate | None:
    """Converte o delta do UCSM em taxa usando o intervalo REAL do UCSM.

    Elimina a dependência entre stat collection policy, intervalo do Telegraf
    e a variável [[polling_interval]] do dashboard (F6).
    """
    if sample is None:
        return None

    interval_s = sample.interval.total_seconds()
    if interval_s <= 0:
        return None

    # A policy do UCSM é mais lenta que o scrape: o mesmo delta será relido.
    # Marcar como stale em vez de contar duas vezes.
    stale = interval_s > scrape_interval_s * 1.5

    return Rate(
        bits_per_second=(sample.delta * 8) / interval_s,
        interval_s=interval_s,
        stale=stale,
    )
```

Com isso o dashboard deixa de fazer aritmética: consome `bits_per_second` direto. E `utm_stat_policy_interval_seconds{domain,stat_type}` vira métrica exportada — a divergência de H1 passa a ser **observável e alertável** em vez de silenciosa.

### 7.4 Meta-métricas — a correção de F4

Sempre emitidas, principalmente quando a coleta falha:

```
utm_collection_success{domain,collector}           0|1
utm_collection_duration_seconds{domain,collector}  histogram
utm_collection_partial{domain}                     0|1
utm_collection_last_success_timestamp{domain}      gauge (unix)
utm_ucsm_sessions_open{domain}                     gauge   ← detecta F4/H2
utm_session_reconnects_total{domain,kind}          counter
utm_circuit_breaker_state{domain}                  0=closed 1=half 2=open
utm_stat_policy_interval_seconds{domain,stat_type} gauge   ← detecta F6/H1
utm_export_lines_rejected_total{exporter,reason}   counter ← detecta F3
```

```promql
# Domínio sem coleta bem-sucedida há mais de 5 minutos
time() - utm_collection_last_success_timestamp > 300

# Sessões UCSM acumulando (limite padrão: 32 por usuário)
utm_ucsm_sessions_open > 20

# Policy do UCSM divergindo do intervalo de scrape
utm_stat_policy_interval_seconds != on(domain) group_left utm_scrape_interval_seconds
```

---

## 8. Decisões técnicas

### ADR-01 — Serviço long-running em vez de `inputs.exec`

| Opção | Prós | Contras |
|---|---|---|
| Manter `exec` | zero mudança operacional | obriga o `pickle` (F1/F2), sem estado, timeout rígido, sem isolamento (F4) |
| **Serviço + `/metrics`** | sessão em memória, isolamento por domínio, meta-métricas | nova unit/container para operar |
| Telegraf `execd` | mantém Telegraf no caminho | processo persistente sem ganho arquitetural sobre a opção 2 |

**Decisão: serviço long-running.** Fecha F1, F2 e F4 de uma vez — sem processo efêmero, não existe motivo para serializar sessão em disco. O Telegraf continua disponível como scraper Prometheus (`inputs.prometheus` → `outputs.influxdb`) durante a migração, o que torna o corte reversível.

### ADR-02 — TSDB

| Opção | Ingest | Query | Esforço em dashboards |
|---|---|---|---|
| InfluxDB 1.8 (hoje) | LP | InfluxQL | zero |
| InfluxDB 3 | LP + SQL | SQL/InfluxQL | alto |
| Prometheus | scrape/remote-write | PromQL | alto; sem histórico migrado |
| **VictoriaMetrics** | **LP + Prometheus + OTLP** | MetricsQL | alto, mas faseável |

**Decisão: VictoriaMetrics** — o ponto decisivo é aceitar **Line Protocol** no endpoint `/write`: dá para apontar o Telegraf atual para ele e rodar os dois bancos em paralelo, sem tocar no coletor, validando dado contra dado antes de qualquer corte.

**Contrapeso honesto:** as 9 dashboards estão em InfluxQL; a reescrita para MetricsQL é a parte cara desta decisão e só compensa junto com o ADR-07. **Se a equipe não topar isso agora, a alternativa defensável é permanecer em InfluxDB 1.8 e trocar só o coletor** — os ADRs 01, 03, 04, 05, 06 e 08 continuam valendo isoladamente, e F1–F7 são todos fechados sem trocar de TSDB. A troca de banco é a única decisão deste RFC que pode ser adiada sem custo de correção.

### ADR-03 — `asyncio` com isolamento por domínio

O padrão atual (`ThreadPoolExecutor(max_workers=len(executor_list))`, `:586`) escala threads linearmente com domínios × tipos de conexão e não isola falhas.

**Decisão: `asyncio`**, um `TaskGroup` por domínio, `asyncio.timeout()` por operação. Substitui o `MASTER_TIMEOUT` global (que só loga depois do fato — F12) por timeout real e **por domínio**: um domínio lento deixa de atrasar os demais, e uma exceção deixa de derrubar o ciclo inteiro (F4). O `ucsmsdk`, que é síncrono, roda em executor dedicado.

### ADR-04 — Manter `ucsmsdk`, atrás de um Protocol

**Decisão: manter no curto prazo, abstraído atrás do `Collector` Protocol.** Com o contrato isolado, trocar por `httpx` + XML API direta depois é troca de um arquivo, não reescrita. Medir primeiro (`utm_collection_duration_seconds` por collector), decidir depois.

**Intersight:** domínios em *Intersight Managed Mode* (6400/6500) não falam a XML API do UCSM. A arquitetura reserva `collectors/intersight.py`. **Não comprometer roadmap antes de validar** granularidade de telemetria, limites de rate e se existe equivalente ao `DcxVc` para o stitching de VIF.

### ADR-05 — scrapli/asyncssh no lugar do netmiko

netmiko é síncrono e está pinado em `4.0.0` por causa do Python 3.6. scrapli + `asyncssh` é nativamente assíncrono, tem driver `cisco_nxos` e oferece `textfsm_parse_output()` — que substitui o parsing manual de `parse_pfc_stats()` e elimina a classe de erro de F7. Pré-requisito: Python ≥ 3.10 (ADR-06).

### ADR-06 — Runtime e empacotamento

**Decisão:** Python 3.12, `uv` para resolução/lock, container OCI como artefato primário, unit systemd com `EnvironmentFile` como alternativa. O container resolve a causa real por trás do CentOS 7: o SO da VM deixa de ditar a versão de Python.

### ADR-07 — Dashboards como código

2,9 MB de JSON editados na UI são a causa do pin do Grafana.

**Decisão: Grafana Foundation SDK (Python)**, gerando JSON em build, provisionado por arquivo. Permite fatorar os painéis repetidos em funções parametrizadas — o mesmo painel de utilização aparece dezenas de vezes com variações de tag. Grafonnet é a alternativa madura, mas acrescenta Jsonnet como segunda linguagem.

### ADR-08 — Testes com fixtures gravadas

**Decisão:** comando `utm record --domain <ip> --output tests/fixtures/` captura a resposta real do UCSM, anonimiza (IP, serial, WWPN, service profile, descrição) e grava. A partir daí todo `transform/` e `exporters/` é testado offline:

```python
# tests/transform/test_topology.py
@pytest.mark.parametrize("fixture", ["ucsm_4.2_8chassis", "ucsm_4.3_mixed_rack", "ucsm_4.3_fex_only"])
def test_every_active_vif_resolves_to_an_uplink(fixture, load_fixture):
    snapshot = normalize.from_raw(load_fixture(fixture))
    stitched = topology.stitch(snapshot)
    unresolved = [v for b in stitched.blades for v in b.vifs if v.uplink_port_dn is None]
    assert not unresolved, f"VIFs sem uplink: {[v.dn for v in unresolved]}"


def test_fex_peer_without_rack_units_does_not_raise(load_fixture):
    """Regressão de F5: domínio só com blades + FEX com peer rack."""
    snapshot = normalize.from_raw(load_fixture("ucsm_4.3_fex_only"))
    lines = influx_lp.render(topology.stitch(snapshot))
    assert lines  # antes: UnboundLocalError → ciclo inteiro perdido
```

Alvo: **≥ 80 % em `transform/` e `exporters/`**. Smoke test em `collectors/` com servidor fake. Nenhuma meta de cobertura para `runtime/`.

### ADR-09 — Credenciais

**Decisão: adotar `docs/superpowers/specs/2026-04-25-utm-credentials-design.md` como está**, com **um adendo obrigatório**: a remoção do `pickle` é pré-requisito, não item opcional. F1 prova que sem ela a senha continua sendo escrita em disco a cada ciclo e o ganho da migração para env vars é parcial.

---

# PARTE III — EXECUÇÃO

## 9. Correções pontuais — antes de qualquer refatoração

> **Status: aplicadas.** Ver [`QUICK_FIXES.md`](QUICK_FIXES.md) para o
> detalhe de cada uma, o que foi medido e os passos que ainda dependem
> de ação na VM (apagar os `.pickle` antigos e rodar a auditoria de
> intervalos). Regressão em `tests/test_quick_fixes.py`.

Cinco itens de baixo risco, alto retorno, independentes do RFC:

1. **F5 — uma palavra.** `:2793`: trocar `per_ru_dict` por `ru_dict`. Elimina a perda total de ciclo em domínios só com blades + FEX.
2. **F1/F2 — contenção imediata.** `chmod 600` nos `.pickle`, dono restrito ao usuário do Telegraf, e `shred` nos existentes. Confirmar H3 antes com o `strings` da seção F1.
3. **F11 — `None`-check e `.get()`** em `cleanup_ucs_connections()` (`:607-614`). Quatro linhas.
4. **F6/H1 — auditoria.** `show stats-collection-policy detail` em todos os domínios; comparar com o `interval` do Telegraf e com `[[polling_interval]]`. Se divergirem, **os números de banda dos dashboards estão errados hoje** — alinhar imediatamente.
5. **F4 — uma métrica de saúde.** Emitir `UTMCollectorHealth,domain=<ip> success=0|1` ao final de cada ciclo, inclusive em falha. ~10 linhas, e transforma o Grafana de "acho que está coletando" em "sei que está".

## 10. Plano de migração — *strangler pattern*

O coletor atual permanece em produção até a paridade estar provada.

### Fase 0 — Rede de segurança (1 semana)
- [ ] `pyproject.toml`, `ruff`, `mypy`, `pytest`, GitHub Actions
- [ ] `utm record` — captura e anonimização de fixtures reais
- [ ] **Harness de paridade:** roda o script antigo e o novo sobre a mesma fixture e faz diff do Line Protocol normalizado. **Critério de aceite bloqueante de todas as fases seguintes.**
- [ ] Aplicar as 5 correções pontuais da seção 9, cada uma com teste de regressão

**Saída:** F5, F11 fechados; F1/F2 contidos; F6 diagnosticado. Nenhuma mudança arquitetural.

### Fase 1 — Credenciais + remoção do `pickle` (2 semanas)
- [ ] `credentials.py` conforme a spec aprovada
- [ ] Remover `pickle` — aceitar o custo de login por ciclo **temporariamente** (ainda sob `exec`)
- [ ] `shred` nos `.pickle` existentes; `utm migrate-credentials` converte os `.txt`

**Saída:** F1, F2 fechados. Ciclo fica mais lento até a Fase 3 — monitorar com a métrica do item 5 da seção 9.

### Fase 2 — Núcleo tipado (4 semanas)
- [ ] `domain/models.py`, `transform/{normalize,topology,rates}.py`
- [ ] `exporters/influx_lp.py` **com escape correto** + teste de propriedade (F3)
- [ ] Portar o stitching das 5 funções gigantes, **função por função, com o harness verde a cada passo**
- [ ] Cobertura ≥ 80 % em `transform/`

**Saída:** F3, F6, F7, F8, F9, F10 fechados. Maior risco e maior retorno da migração.

### Fase 3 — Runtime como serviço (3 semanas)
- [ ] `runtime/{scheduler,session,health}.py`, `collectors/` com scrapli
- [ ] `exporters/prometheus.py` + meta-métricas
- [ ] Container + unit systemd
- [ ] Rodar em paralelo ao coletor antigo, no mesmo InfluxDB, com prefixo de medição distinto

**Saída:** F4, F12 fechados. Validar paridade em produção por 2 semanas antes de seguir.

### Fase 4 — Armazenamento (2 semanas) — *opcional, ver ADR-02*
- [ ] VictoriaMetrics recebendo LP em paralelo; comparar séries por 1 semana
- [ ] Retenção e downsampling; corte e desligamento do coletor antigo

### Fase 5 — Dashboards como código (2 semanas)
- [ ] Extrair os 9 JSONs para Foundation SDK, fatorar painéis repetidos
- [ ] Remover a aritmética de taxa das queries (já resolvida em `rates.py`)
- [ ] Provisionamento em arquivo; **destravar o pin do Grafana**

### Fase 6 — Intersight — *bloqueada*
- [ ] Validar viabilidade de telemetria na API (pré-requisito absoluto)
- [ ] `collectors/intersight.py`; modelo unificado UCSM + IMM

## 11. Esforço e riscos

| Fase | Esforço | Risco | Mitigação |
|---|---|---|---|
| 0 — Rede de segurança | 1 sem | Baixo | sem mudança arquitetural |
| 1 — Credenciais | 2 sem | Médio | rollback documentado; ciclo temporariamente mais lento |
| 2 — Núcleo tipado | 4 sem | **Alto** | harness de paridade bloqueante a cada passo |
| 3 — Runtime | 3 sem | Médio | operação em paralelo ao antigo |
| 4 — TSDB | 2 sem | Médio | dual-write + 1 semana de comparação; **adiável** |
| 5 — Dashboards | 2 sem | Médio | dashboards antigos preservados até validação |
| 6 — Intersight | ? | Alto | bloqueada até validação da API |
| **Total (0–5)** | **~14 sem** | | |

**Riscos principais:**

- **Regressão silenciosa no stitching (Fase 2).** É a lógica mais complexa e menos documentada do projeto. Mitigação: harness de paridade com fixtures de múltiplas versões de UCSM e topologias distintas (blade, rack, FEX, misto, UCS Mini).
- **Correção de F6 muda os números dos dashboards.** Se H1 se confirmar, os valores de banda **vão mudar** após a correção — e estarão certos pela primeira vez. Comunicar antes, não depois; guardar a série antiga para comparação.
- **Reescrita das dashboards (Fase 5).** Maior bloco de trabalho manual. Mitigação: fatorar antes de portar.

## 12. O que explicitamente NÃO muda

- O stitching end-to-end vNIC → uplink é preservado integralmente. A refatoração o torna testável, não diferente.
- Nomes de measurement, tags e unidades — exceto onde F6 exige (taxa passa de delta bruto para bits/s, mudança anunciada e versionada). Caso contrário o histórico do InfluxDB fica órfão.
- Compatibilidade com UCSM clássico. Intersight é adição, nunca substituição.

## 13. Decisões pendentes

1. **Trocar de TSDB agora ou depois?** ADR-02 deixa claro que é a única decisão adiável sem custo de correção. Recomendação: Fases 0–3 primeiro, decidir com dados de cardinalidade reais (H4) em mãos.
2. **Container ou systemd puro?** Depende da política da VM de produção.
3. **Upstream ou fork?** Fases 0–2 são candidatas naturais a PR upstream — F1, F3, F5, F6 e F7 afetam **todos** os usuários do projeto. Fases 3–5 mudam o modelo de deploy e provavelmente vivem só no fork.
4. **Divulgação dos achados de segurança.** F1, F2 e F3 afetam qualquer instalação do UTM. Decidir se a comunicação ao mantenedor é privada primeiro.
