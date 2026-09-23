#!/usr/bin/python3
"""Check InfluxDB Line Protocol output for malformed lines.

The collector builds Line Protocol by string concatenation with no escaping
(finding F3). A location or GROUP with a space ("DC Sao Paulo"), or a port
description with a double quote, produces a line that Telegraf rejects: the
series silently disappears from the dashboards. This tool parses each line
the way the InfluxDB parser does and reports which ones would be rejected.

It prints the measurement name, line number and the reason, never the tag or
field values, so the report is safe to share.

    python3 ucs_traffic_monitor.py ... influxdb-lp | tools/lp_lint.py
    tools/lp_lint.py saida.lp

Exits 0 when every line parses, 1 when at least one is malformed.
"""

# Kept compatible with Python 3.6 so it runs on any host being diagnosed.
from __future__ import print_function

import re
import sys
from collections import Counter

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_INTEGER = re.compile(r"^[+-]?\d+[iu]$")
_BOOLEAN = {"t", "T", "true", "True", "TRUE", "f", "F", "false", "False", "FALSE"}


def split_unescaped(text, separator, honor_quotes):
    """Split on `separator` outside backslash escapes (and quotes, if asked).

    Returns (parts, error) where error is set for an unterminated quote.
    """
    parts, current = [], []
    in_quotes = escaped = False
    for ch in text:
        if escaped:
            current.append(ch)
            escaped = False
            continue
        if ch == "\\":
            current.append(ch)
            escaped = True
            continue
        if honor_quotes and ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
            continue
        if ch == separator and not in_quotes:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return parts, ("unterminated string value" if in_quotes else None)


def check_field_value(value):
    if value.startswith('"'):
        if len(value) < 2 or not value.endswith('"'):
            return "string field not properly quoted"
        escaped = False
        for ch in value[1:-1]:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                # e.g. a port description containing a double quote
                return "unescaped double quote inside string field"
        return None
    if _NUMBER.match(value) or _INTEGER.match(value) or value in _BOOLEAN:
        return None
    return "field value is not a number, bool or quoted string"


def check_line(line):
    """Return (measurement, reason) for a malformed line, or None when valid."""
    sections, err = split_unescaped(line, " ", honor_quotes=True)
    measurement = (split_unescaped(sections[0], ",", False)[0][0] or "?")[:30]
    if err:
        return measurement, err
    sections = [s for s in sections if s != ""]
    if len(sections) < 2:
        return measurement, "no field set"
    if len(sections) > 3:
        return measurement, "unescaped space in a tag or field key"

    series, fields = sections[0], sections[1]
    tags = split_unescaped(series, ",", honor_quotes=False)[0][1:]
    for tag in tags:
        pair = split_unescaped(tag, "=", honor_quotes=False)[0]
        if len(pair) != 2 or not pair[0] or not pair[1]:
            return measurement, "malformed or empty tag"

    field_items, err = split_unescaped(fields, ",", honor_quotes=True)
    if err:
        return measurement, err
    for item in field_items:
        key, sep, value = item.partition("=")
        if not sep or not key or not value:
            return measurement, "malformed field (missing key or value)"
        problem = check_field_value(value)
        if problem:
            return measurement, problem

    if len(sections) == 3 and not sections[2].lstrip("-").isdigit():
        return measurement, "timestamp is not an integer"
    return None


def main(argv):
    stream = open(argv[1]) if len(argv) > 1 else sys.stdin
    total = 0
    bad = []
    per_measurement = Counter()
    for lineno, raw in enumerate(stream, 1):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        total += 1
        problem = check_line(line)
        if problem:
            bad.append((lineno,) + problem)
            per_measurement[problem[0]] += 1

    print("lines checked: {}   malformed: {}".format(total, len(bad)))
    for measurement, count in per_measurement.most_common():
        print("  {:<24} {} malformed".format(measurement, count))
    for lineno, measurement, reason in bad[:15]:
        print("  line {:>5}  {:<24} {}".format(lineno, measurement, reason))
    if len(bad) > 15:
        print("  ... {} more".format(len(bad) - 15))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
