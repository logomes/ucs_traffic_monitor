#!/usr/bin/env python3
"""Reprodução executável dos achados do RFC 2026-09-20.

Cada verificação extrai o código real de `telegraf/ucs_traffic_monitor.py`
(referência de linha no docstring) e demonstra o defeito. Nenhum acesso a
UCS é necessário — os achados são determinísticos.

Uso:
    python3 docs/refactor/poc/verify_findings.py
    python3 docs/refactor/poc/verify_findings.py --finding F3

F1 exige o ucsmsdk instalado; é pulado automaticamente se ausente.
Saída: 0 se todos os defeitos foram reproduzidos, 1 caso contrário.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Result:
    finding: str
    title: str
    reproduced: bool
    notes: list[str] = field(default_factory=list)
    skipped: bool = False


# --------------------------------------------------------------------------
# F1 — o pickle do UcsHandle carrega a senha em texto claro  (:631)
# --------------------------------------------------------------------------
def check_f1() -> Result:
    r = Result("F1", "Senha do UCS em texto claro no arquivo .pickle", False)
    try:
        import pickle

        from ucsmsdk.ucshandle import UcsHandle
    except ImportError:
        r.skipped = True
        r.notes.append("ucsmsdk não instalado — pulado (pip install ucsmsdk)")
        return r

    secret = "SuperSecret123!"  # noqa: S105 - valor sintético de teste
    blob = pickle.dumps(UcsHandle("10.1.1.1", "svc_utm_ro", secret))

    r.reproduced = secret.encode() in blob
    printable = [s for s in re.findall(rb"[ -~]{8,}", blob) if b"svc_utm" in s or b"Secret" in s]
    r.notes.append(f"tamanho do pickle: {len(blob)} bytes")
    r.notes.append(f"strings recuperáveis: {printable}")
    return r


# --------------------------------------------------------------------------
# F3 — injeção de Line Protocol pela descrição da porta  (:2563)
# --------------------------------------------------------------------------
def _build_fi_port_line(description: str) -> str:
    """Cópia literal da construção de linha de print_output_in_influxdb_lp()."""
    prefix = "FIUplinkPortStats,domain=" + "10.1.1.1"
    tags = "," + "fi_id=A,location=DC1,port=1/17,transport=ether"
    fields = (
        " "
        + 'admin_state="' + "enabled" + '",'
        + 'description="' + description + '",'      # <- sem escape
        + "oper_speed=" + str(10) + ","
        + 'oper_state="' + "up" + '"'
    )
    return prefix + tags + fields + "\n"


def check_f3() -> Result:
    r = Result("F3", "Injeção de Line Protocol via descrição de porta do UCSM", False)

    ok = _build_fi_port_line("Uplink para Nexus 93180 Po10")
    r.notes.append(f"descrição normal  -> {ok.count(chr(10))} linha(s) (esperado 1)")

    quoted = _build_fi_port_line('link "backup"')
    broken = quoted.count('"') % 2 != 0 or 'description="link "backup""' in quoted
    r.notes.append(f"descrição com aspas -> linha malformada: {broken}")

    payload = 'x",fake=1\nFIUplinkPortStats,domain=10.1.1.1,port=99/99 bytes_rx_delta=999999999i\nz="'
    injected = _build_fi_port_line(payload)
    n_lines = len(injected.strip().splitlines())
    r.notes.append(f"payload de injeção -> {n_lines} linhas geradas (esperado 1)")
    if n_lines > 1:
        r.notes.append(f"  linha forjada: {injected.strip().splitlines()[1]}")

    r.reproduced = broken and n_lines > 1
    return r


# --------------------------------------------------------------------------
# F5 — variável de loop vazada em print_output_in_influxdb_lp()  (:2793)
# --------------------------------------------------------------------------
def check_f5() -> Result:
    r = Result("F5", "UnboundLocalError no caminho de FEX com peer rack-unit", False)

    def render(d_dict: dict, bp_peer: str) -> str:
        """Estrutura de controle idêntica a :2711 e :2791-2797."""
        out = ""
        ru_dict = d_dict["ru"]
        for ru_id, per_ru_dict in ru_dict.items():           # :2711 — único bind
            out += ru_id + per_ru_dict["service_profile"]

        # :2791-2797 — trecho do loop de FEX
        ru_dict = d_dict["ru"]
        ru_server = bp_peer
        if ru_server in per_ru_dict:                          # BUG: deveria ser ru_dict
            per_ru_dict = ru_dict[ru_server]
            out += ",peer_service_profile=" + per_ru_dict["service_profile"]
        return out

    # Caso 1: domínio só com blades (ru vazio) -> per_ru_dict nunca vinculado
    try:
        render({"ru": {}}, bp_peer="rack-unit-5")
        r.notes.append("domínio sem rack units -> NÃO levantou exceção (inesperado)")
    except (UnboundLocalError, NameError) as exc:
        r.reproduced = True
        r.notes.append(f"domínio sem rack units -> {type(exc).__name__}: {exc}")
        r.notes.append("  por F4, isso descarta o ciclo inteiro de TODOS os domínios")

    # Caso 2: com rack units -> tag silenciosamente omitida
    d = {"ru": {"rack-unit-5": {"service_profile": "SP-ESX-05"}}}
    rendered = render(d, bp_peer="rack-unit-5")
    omitted = "peer_service_profile" not in rendered
    r.notes.append(f"com rack units -> tag peer_service_profile omitida: {omitted}")
    return r


# --------------------------------------------------------------------------
# F7 — iom_slot_id vaza entre linhas do parser de PFC  (:2162, :2211, :2281)
# --------------------------------------------------------------------------
def check_f7() -> Result:
    r = Result("F7", "iom_slot_id vaza entre iterações -> PAUSE no IOM errado", False)

    def resolve(bp_port_dict: dict, fi_id: str, iom_slot_id):
        """Bloco de :2211 / :2281 — só atribui quando há correspondência."""
        for iom_slot, port_dict in bp_port_dict.items():
            for _iom_port, per_bp in port_dict.items():
                if per_bp["fi_id"] == fi_id:
                    iom_slot_id = iom_slot
                break
        return iom_slot_id

    # Linha 1: casa com fabric A -> slot "1"
    bp_a = {"1": {"09": {"fi_id": "A"}}}
    slot = resolve(bp_a, "A", 0)
    r.notes.append(f"linha 1 (casa fabric A) -> iom_slot_id={slot!r}")

    # Linha 2: chassi só com IOM do fabric B, coletando fabric A -> não casa
    bp_b = {"2": {"09": {"fi_id": "B"}}}
    leaked = resolve(bp_b, "A", slot)   # iom_slot_id carrega o valor da linha 1
    r.notes.append(f"linha 2 (não casa)     -> iom_slot_id={leaked!r} (vazou da linha 1)")

    contaminated = leaked == slot and leaked not in bp_b
    if contaminated:
        r.notes.append("  -> pause_rx/tx gravado em slot inexistente no chassi atual")

    # Primeira linha sem correspondência -> permanece 0 -> KeyError
    virgin = resolve(bp_b, "A", 0)
    try:
        _ = bp_b[virgin]
        r.notes.append("primeira linha sem match -> sem KeyError (inesperado)")
        crashed = False
    except KeyError as exc:
        crashed = True
        r.notes.append(f"primeira linha sem match -> KeyError: {exc} (mata o processo)")

    r.reproduced = contaminated and crashed
    return r


# --------------------------------------------------------------------------
# F8 — get_fi_id_from_dn() confunde fabric por substring  (:681)
# --------------------------------------------------------------------------
def check_f8() -> Result:
    r = Result("F8", "get_fi_id_from_dn() atribui fabric errado por substring", False)

    def get_fi_id_from_dn(dn: str):
        if "A" in dn:
            return "A"
        elif "B" in dn:
            return "B"
        return None

    cases = [
        ("sys/switch-A/slot-1/switch-ether/port-1", "A"),
        ("sys/switch-B/slot-1/switch-ether/port-1", "B"),
        ("fabric/lan/B/net-VLAN_A", "B"),  # rótulo do usuário com 'A'
    ]
    for dn, expected in cases:
        got = get_fi_id_from_dn(dn)
        mark = "OK " if got == expected else "ERRO"
        r.notes.append(f"{mark} {dn} -> {got} (esperado {expected})")
        if got != expected:
            r.reproduced = True
    return r


# --------------------------------------------------------------------------
# F9 — isFloat() valida com float() mas converte com int()  (:696)
# --------------------------------------------------------------------------
def check_f9() -> Result:
    r = Result("F9", "get_speed_num_from_string() levanta ValueError não tratado", False)

    def is_float(val) -> bool:
        try:
            float(val)
            return True
        except ValueError:
            return False

    def get_speed_num_from_string(speed):
        if is_float(speed):
            return int(speed)
        if "gbps" in str(speed):
            return int(str(speed).rstrip("gbps"))
        return 0

    for v in ("10", "10gbps", "100gbps"):
        r.notes.append(f"OK   {v!r} -> {get_speed_num_from_string(v)}")

    for v in ("10.5", "nan", "inf"):
        try:
            get_speed_num_from_string(v)
            r.notes.append(f"     {v!r} -> sem exceção (inesperado)")
        except ValueError as exc:
            r.reproduced = True
            r.notes.append(f"ERRO {v!r} -> ValueError: {exc}")

    r.notes.append(f"rstrip vs removesuffix: {'sgbps'.rstrip('gbps')!r} (esperado 's')")
    return r


# --------------------------------------------------------------------------
# F10 — 'associated' é substring de 'unassociated'  (:2645, :2733)
# --------------------------------------------------------------------------
def check_f10() -> Result:
    r = Result("F10", "Filtro de estado por substring aceita blade não associado", False)

    for assoc in ("associated", "unassociated", "associating", "removing"):
        emitted = not ("associated" not in assoc)
        mark = "ERRO" if assoc == "unassociated" and emitted else "OK  "
        r.notes.append(f"{mark} association={assoc!r:16} -> passa no filtro: {emitted}")
        if assoc == "unassociated" and emitted:
            r.reproduced = True

    r.notes.append("  mascarado hoje pela condição combinada com oper_state;")
    r.notes.append("  exposto quando oper_state='ok' e association='unassociated'")
    return r


# --------------------------------------------------------------------------
# F11 — cleanup_ucs_connections() com --no-ssh  (:607-614, :474)
# --------------------------------------------------------------------------
def check_f11() -> Result:
    r = Result("F11", "cleanup_ucs_connections() quebra com --no-ssh / login falho", False)

    def cleanup(conn_dict: dict) -> None:
        for _domain_ip, handles in conn_dict.items():
            cli_handle = handles["cli"]      # :608
            sdk_handle = handles["sdk"]
            cli_handle.disconnect()          # :613
            sdk_handle.logout()

    # --no-ssh: connect_and_pull_stats() retorna em :474 antes de setar 'cli'
    try:
        cleanup({"10.1.1.1": {"sdk": object()}})
        r.notes.append("--no-ssh -> sem exceção (inesperado)")
    except KeyError as exc:
        r.reproduced = True
        r.notes.append(f"--no-ssh -> KeyError: {exc}")

    # login falhou: handle é None, sem None-check
    try:
        cleanup({"10.1.1.1": {"cli": None, "sdk": None}})
        r.notes.append("login falho -> sem exceção (inesperado)")
    except AttributeError as exc:
        r.notes.append(f"login falho -> AttributeError: {exc}")
    return r


CHECKS: dict[str, Callable[[], Result]] = {
    "F1": check_f1,
    "F3": check_f3,
    "F5": check_f5,
    "F7": check_f7,
    "F8": check_f8,
    "F9": check_f9,
    "F10": check_f10,
    "F11": check_f11,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--finding", choices=sorted(CHECKS), help="roda apenas um achado")
    args = parser.parse_args()

    selected = [args.finding] if args.finding else list(CHECKS)
    results = [CHECKS[name]() for name in selected]

    for res in results:
        if res.skipped:
            status = "PULADO"
        elif res.reproduced:
            status = "REPRODUZIDO"
        else:
            status = "NÃO REPRODUZIDO"
        print(f"\n{'=' * 78}\n{res.finding} — {res.title}\n  status: {status}")
        for note in res.notes:
            print(f"    {note}")

    graded = [r for r in results if not r.skipped]
    failed = [r for r in graded if not r.reproduced]
    print(f"\n{'=' * 78}")
    print(f"reproduzidos: {len(graded) - len(failed)}/{len(graded)}"
          f"   pulados: {len(results) - len(graded)}")
    if failed:
        print("não reproduzidos: " + ", ".join(r.finding for r in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
