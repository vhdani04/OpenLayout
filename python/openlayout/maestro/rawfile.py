"""SPICE raw files (ngspice `-r`, binary or ASCII): one file holds a plot per analysis.

    plots = read("tb.raw")           # [Plot]
    p = plots[0]; p.name ("Transient Analysis"), p.kind ("tran"), p.scale ("time"), p["v(out)"]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

KINDS = {"transient": "tran", "dc transfer": "dc", "ac analysis": "ac", "operating point": "op",
         "noise": "noise", "transfer function": "tf", "sensitivity": "sens", "pole-zero": "pz"}


@dataclass
class Plot:
    name: str                       # "Transient Analysis"
    names: list                     # variable names, the scale first
    units: list                     # "time", "voltage", "current", ...
    data: np.ndarray                # (n_vars, n_points), float64 or complex128
    title: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def kind(self) -> str:
        n = self.name.lower()
        for k, v in KINDS.items():
            if n.startswith(k):
                return v
        return n.split()[0] if n else "plot"

    @property
    def scale(self) -> str:
        return self.names[0]

    @property
    def x(self) -> np.ndarray:
        x = self.data[0]
        return x.real if np.iscomplexobj(x) else x

    @property
    def complex(self) -> bool:
        return np.iscomplexobj(self.data)

    def __contains__(self, name) -> bool:
        return self.index(name) is not None

    def index(self, name):
        key = name.lower()
        for i, n in enumerate(self.names):
            if n.lower() == key:
                return i
        if not key.startswith(("v(", "i(")):               # a bare node name: v(node)
            return self.index(f"v({key})")
        if key.startswith("i(") and not key.endswith("#branch)"):
            for i, n in enumerate(self.names):            # i(vdd) is written "vdd#branch" by some versions
                if n.lower() == key[2:-1] + "#branch":
                    return i
        return None

    def __getitem__(self, name) -> np.ndarray:
        i = self.index(name)
        if i is None:
            raise KeyError(name)
        return self.data[i]

    def signals(self, internal=False):
        """The vectors other than the scale; internal device nodes (n1#di ...) only on request."""
        return [n for n in self.names[1:] if internal or "#" not in n or n.endswith("#branch")]


def read(path) -> list[Plot]:
    raw = Path(path).read_bytes()
    plots, pos = [], 0
    while pos < len(raw):
        header, pos, binary = _header(raw, pos)
        if header is None:
            break
        nvars, npts = int(header["no. variables"]), int(header["no. points"])
        cplx = "complex" in header.get("flags", "").lower()
        names, units = [], []
        for line in header["_vars"]:
            t = line.split()
            names.append(t[1])
            units.append(t[2] if len(t) > 2 else "")
        dtype = np.complex128 if cplx else np.float64
        if binary:
            count = nvars * npts
            arr = np.frombuffer(raw, dtype=np.dtype(dtype).newbyteorder("<"), count=count, offset=pos)
            pos += arr.nbytes
            data = arr.reshape(npts, nvars).T.copy()
        else:
            data, pos = _ascii_values(raw, pos, nvars, npts, cplx)
        plots.append(Plot(header.get("plotname", ""), names, units, data, header.get("title", ""), header))
    return plots


def _header(raw: bytes, pos: int):
    h, vars_ = {}, []
    in_vars = False
    while pos < len(raw):
        end = raw.find(b"\n", pos)
        if end < 0:
            return None, len(raw), False
        line = raw[pos:end].decode("latin-1").rstrip("\r")
        pos = end + 1
        low = line.strip().lower()
        if low in ("binary:", "values:"):
            h["_vars"] = vars_
            return h, pos, low == "binary:"
        if in_vars and line[:1] in (" ", "\t") and line.strip():
            vars_.append(line.strip())
            continue
        in_vars = False
        if ":" in line:
            k, v = line.split(":", 1)
            h[k.strip().lower()] = v.strip()
            if k.strip().lower() == "variables":
                in_vars = True
    return None, pos, False


def _ascii_values(raw: bytes, pos: int, nvars: int, npts: int, cplx: bool):
    text = raw[pos:].decode("latin-1")
    tokens = re.split(r"\s+", text.strip())
    data = np.zeros((nvars, npts), dtype=np.complex128 if cplx else np.float64)
    k = 0
    consumed = 0
    for p in range(npts):
        k += 1                                   # the point index
        for v in range(nvars):
            tok = tokens[k]
            k += 1
            if cplx:
                re_, im = tok.split(",")
                data[v, p] = complex(float(re_), float(im))
            else:
                data[v, p] = float(tok)
    # find where the next plot starts (a "Title:" line), if any
    nxt = text.find("Title:")
    consumed = len(raw) - pos if nxt < 0 else len(text[:nxt].encode("latin-1"))
    return data, pos + consumed
