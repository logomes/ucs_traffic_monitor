#!/usr/bin/python3
"""Load UCS domain credentials from either configuration mode UTM supports.

UTM has two credential modes in the wild:

  file mode  upstream / master: a text file with `IP,user,password` lines and
             `[Location]` headers, passed as the first positional argument.
  env mode   feat/credentials-env-vars and later: UTM_DOMAINS=dom1,dom2 plus
             UTM_<id>_HOST / _USER / _PASS / _GROUP, delivered by systemd from
             an EnvironmentFile such as /etc/utm/creds.env.

The validation tools accept either source through the same three options
(`-i FILE`, `--env-file FILE`, `--from-env`), so they run unchanged against
whichever collector is in production.

Run as a command, this module also launches a program with an env file loaded
the way the collector would see it under systemd, without the secrets ever
appearing on a command line:

    python3 credsource.py exec /etc/utm/creds.env -- python3 collector.py ...
"""

# Kept compatible with Python 3.6 so it runs on any host being diagnosed.
from __future__ import print_function

import os
import shlex
import sys
from collections import namedtuple

Domain = namedtuple("Domain", "id host user password group")


class CredentialError(Exception):
    """Raised when no usable credential source was found."""


def parse_env_file(path):
    """Parse a systemd EnvironmentFile / dotenv-style file into a dict.

    Handles blank lines, `#` comments, an optional `export ` prefix, and POSIX
    shell quoting, including the `'\\''` escape that migrate_credentials.py
    writes for passwords containing single quotes.
    """
    env = {}
    with open(path) as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" not in line:
                raise CredentialError(
                    "{}:{}: not a KEY=VALUE line".format(path, lineno))
            key, _, value = line.partition("=")
            key = key.strip()
            try:
                parts = shlex.split(value, posix=True)
            except ValueError as exc:
                raise CredentialError(
                    "{}:{}: cannot parse value for {}: {}".format(
                        path, lineno, key, exc))
            env[key] = " ".join(parts) if parts else ""
    return env


def domains_from_env(env):
    """Env mode: UTM_DOMAINS plus UTM_<id>_HOST/USER/PASS/GROUP."""
    ids = [item.strip() for item in env.get("UTM_DOMAINS", "").split(",")
           if item.strip()]
    if not ids:
        raise CredentialError("UTM_DOMAINS is empty or unset")

    domains = []
    for domain_id in ids:
        values = {}
        for field in ("HOST", "USER", "PASS"):
            key = "UTM_{}_{}".format(domain_id, field)
            if not env.get(key):
                raise CredentialError("missing {}".format(key))
            values[field] = env[key]
        domains.append(Domain(domain_id, values["HOST"], values["USER"],
                              values["PASS"],
                              env.get("UTM_{}_GROUP".format(domain_id),
                                      "default")))
    return domains


def domains_from_file(path):
    """File mode: mirrors get_ucs_domains() in the upstream collector,
    including taking the third comma-separated field as the password."""
    domains = []
    location = ""
    with open(path) as handle:
        for raw in handle:
            if raw.startswith("#"):
                continue
            line = raw.strip()
            if not line:
                continue
            if line.startswith("["):
                location = line.strip("[]").strip()
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            domains.append(Domain(parts[0], parts[0], parts[1], parts[2],
                                  location))
    if not domains:
        raise CredentialError("no domains in {}".format(path))
    return domains


def add_arguments(parser):
    """Register the three credential-source options on an argparse parser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-i", "--input-file",
                       help="file mode: ucs_domains_group_*.txt")
    group.add_argument("--env-file",
                       help="env mode: EnvironmentFile, e.g. /etc/utm/creds.env")
    group.add_argument("--from-env", action="store_true",
                       help="env mode: read UTM_* from this process environment")


def load(args):
    """Return the domains from whichever source the parsed args selected."""
    if getattr(args, "input_file", None):
        return domains_from_file(args.input_file)
    if getattr(args, "env_file", None):
        return domains_from_env(parse_env_file(args.env_file))
    if getattr(args, "from_env", False):
        return domains_from_env(os.environ)
    raise CredentialError(
        "no credential source: pass -i FILE, --env-file FILE or --from-env")


def _exec_with_env_file(argv):
    """`exec ENVFILE -- cmd args...`: replace this process with cmd, run with
    ENVFILE merged into the environment."""
    if len(argv) < 3 or argv[1] != "--":
        print("usage: credsource.py exec ENVFILE -- command [args...]",
              file=sys.stderr)
        return 2
    env = dict(os.environ)
    env.update(parse_env_file(argv[0]))
    command = argv[2:]
    os.execvpe(command[0], command, env)
    return 0  # not reached


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "exec":
        try:
            sys.exit(_exec_with_env_file(sys.argv[2:]))
        except CredentialError as exc:
            print("credsource: {}".format(exc), file=sys.stderr)
            sys.exit(2)
    print(__doc__)
    sys.exit(0)
