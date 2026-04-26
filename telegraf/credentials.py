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
