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
    for domain_id, (host, user, password, group) in zip(ids, domains, strict=True):
        lines.append(f"UTM_{domain_id}_HOST={shell_quote(host)}")
        lines.append(f"UTM_{domain_id}_USER={shell_quote(user)}")
        lines.append(f"UTM_{domain_id}_PASS={shell_quote(password)}")
        lines.append(f"UTM_{domain_id}_GROUP={shell_quote(group)}")
        lines.append("")

    out_path.write_text("\n".join(lines))
    out_path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, type=Path, help="Path to legacy ucs_domains_group_*.txt"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Path to write the new creds.env"
    )
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
