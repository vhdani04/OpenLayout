"""Bus names, as xschem writes them: WL[1:0] is the bits WL[1], WL[0] (MSB first, as written).

    expand("WL[1:0]")   -> ["WL[1]", "WL[0]"]
    expand("D[0:4:2]")  -> ["D[0]", "D[2]", "D[4]"]      (start:stop:step)
    expand("A,B[1:0]")  -> ["A", "B[1]", "B[0]"]          (comma lists)
    expand("CLK")       -> ["CLK"]
Cadence-style WL<1:0> is read the same way.
"""
from __future__ import annotations

import re

RANGE_RE = re.compile(r"^(?P<base>[^\[\]]+)\[(?P<a>\d+)(?::(?P<b>\d+)(?::(?P<s>\d+))?)?\]$")


def _split(text: str) -> list[str]:
    """Comma-separated parts, commas inside brackets kept."""
    parts, cur, depth = [], "", 0
    for ch in text:
        depth += (ch == "[") - (ch == "]")
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return [p for p in parts + [cur] if p]


def expand(name: str) -> list[str]:
    name = re.sub(r"<([^<>]*)>", r"[\1]", name.strip())
    out = []
    for part in _split(name):
        m = RANGE_RE.match(part)
        if not m:
            out.append(part)
            continue
        a = int(m["a"])
        b = int(m["b"]) if m["b"] is not None else a
        s = int(m["s"]) if m["s"] is not None else 1
        step = s if b >= a else -s
        out += [f"{m['base']}[{i}]" for i in range(a, b + step // abs(step), step)]
    return out


def is_bus(name: str) -> bool:
    return len(expand(name)) > 1 or "[" in name
