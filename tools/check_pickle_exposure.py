#!/usr/bin/python3
"""Report whether UTM session pickles carry UCS passwords, without printing them.

The collector pickles UcsHandle objects between runs, and UcsSession keeps the
password as an instance attribute, so the pickle can hold it in the clear
(finding F1). A `strings | grep passw` check proves nothing: the attribute
NAME `_UcsSession__password` is always there once a handle is pickled, and the
grep puts the secret on the terminal. This tool instead looks for each
configured password as raw bytes and prints only yes/no per domain.

It never unpickles anything: pickle.load() would run code from the file
(finding F2). It only reads bytes and stat().

    tools/check_pickle_exposure.py --env-file /etc/utm/creds.env /usr/local/telegraf/*.pickle
    tools/check_pickle_exposure.py -i ucs_domains_group_1.txt   /usr/local/telegraf/*.pickle

Exits 0 when no password is found in any pickle, 1 when at least one is,
2 on error.
"""

# Kept compatible with Python 3.6 so it runs on any host being diagnosed.
from __future__ import print_function

import argparse
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import credsource  # noqa: E402

# Present in the pickle whenever a UcsHandle (hence a UcsSession) was saved
SESSION_MARKER = b"_UcsSession__password"


def owner_name(uid):
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError):
        return str(uid)


def describe_mode(mode):
    perms = stat.S_IMODE(mode)
    notes = []
    if perms & 0o044:
        notes.append("readable by group/others")
    if perms & 0o022:
        notes.append("WRITABLE by group/others (pickle.load RCE risk)")
    return "{:o}".format(perms), notes


def check_file(path, domains):
    """Return (exposed_count, lines) for one pickle file."""
    lines = []
    try:
        st = os.stat(path)
        with open(path, "rb") as handle:
            blob = handle.read()
    except (IOError, OSError) as exc:
        return 0, ["  cannot read: {}".format(exc)]

    mode, notes = describe_mode(st.st_mode)
    lines.append("  mode {}  owner {}  size {} bytes".format(
        mode, owner_name(st.st_uid), len(blob)))
    for note in notes:
        lines.append("  ! {}".format(note))

    if SESSION_MARKER not in blob:
        lines.append("  no UCS session stored (empty or cleared pickle)")
        return 0, lines

    exposed = 0
    for domain in domains:
        found = bool(domain.password) and \
            domain.password.encode("utf-8") in blob
        exposed += int(found)
        lines.append("  {:<18} password in clear: {}".format(
            domain.host, "YES" if found else "no"))
    return exposed, lines


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    credsource.add_arguments(parser)
    parser.add_argument("pickles", nargs="+", help="pickle files to inspect")
    args = parser.parse_args()

    try:
        domains = credsource.load(args)
    except (credsource.CredentialError, IOError, OSError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2

    total_exposed = 0
    for path in args.pickles:
        print(path)
        exposed, lines = check_file(path, domains)
        total_exposed += exposed
        for line in lines:
            print(line)

    print("")
    if total_exposed:
        print("{} password(s) stored in clear. Treat them as compromised: "
              "they were in every VM snapshot and backup. Rotate them on "
              "UCSM, then shred the pickle files.".format(total_exposed))
        return 1
    print("No configured password found in the pickle files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
