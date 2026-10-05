"""Digital vector files (the HSPICE / Spectre .vec format): input patterns become PWL voltage
sources on the nodes they name, expected outputs are checked against the simulated waveforms.

    ; a 2-bit counter's stimulus and expected output
    radix  1 1 4          ; bits per column (1 = binary digit, 4 = hex digit)
    io     i i o          ; i input, o output (checked), b bidirectional (driven like an input)
    vname  clk rst q[3:0] ; node names; a bus names the bits of a multi-bit column, MSB first
    tunit  ps             ; fs ps ns us ms (default ns)
    period 100            ; one vector per period (otherwise the first column of a data line is its time)
    trise 10 ; tfall 10   ; transition times (also: slope)
    vih vdd ; vil 0       ; input levels - a number, a design variable or an expression (0.9*vdd)
    voh 0.5 ; vol 0.2     ; output thresholds (default 80 % / 20 % of vih)
    idelay 0 ; odelay 90  ; input delay, output check time after each vector (default: just before the next)
    0 1 0
    1 1 0
    0 0 0
    1 0 1

Values: 0 1 (bits) or 0-F (hex columns); X don't care (outputs) / hold (inputs); Z hold.
A statement may end with a mask - one digit per column, non-zero where it applies:
    vih 0.9 1 1 0     (only the first two columns)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .calc import CalcError, Context, Waveform, evaluate, si

TUNITS = {"fs": 1e-15, "ps": 1e-12, "ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}
SETTINGS = ("vih", "vil", "voh", "vol", "trise", "tfall", "slope", "idelay", "odelay", "tdelay")


class VectorError(Exception):
    pass


@dataclass
class Bit:
    name: str
    io: str
    column: int
    settings: dict = field(default_factory=dict)     # per-bit overrides from masked statements
    values: list = field(default_factory=list)       # one per vector: "0" "1" "X" "Z"


@dataclass
class VectorFile:
    path: str
    bits: list
    times: list                     # seconds, one per vector
    period: float | None
    settings: dict                  # global settings (raw strings / numbers, times already in seconds)

    def inputs(self):
        return [b for b in self.bits if b.io in ("i", "b")]

    def outputs(self):
        return [b for b in self.bits if b.io == "o"]

    def setting(self, bit, key, variables, default=None):
        raw = bit.settings.get(key, self.settings.get(key))
        if raw is None:
            return default
        if isinstance(raw, (int, float)):
            return float(raw)
        if raw in variables:
            return si(variables[raw])
        try:
            return si(raw)
        except ValueError:
            pass
        try:                                         # an expression of design variables: 0.8*vdd
            v = evaluate(raw, Context([], variables))
        except CalcError as e:
            raise VectorError(f"{self.path}: {key} {raw!r} is not a number, a design variable or an "
                              f"expression of them ({e})") from None
        if not isinstance(v, (int, float)):
            raise VectorError(f"{self.path}: {key} {raw!r} is not a number")
        return float(v)

    def levels(self, bit, variables):
        vih = self.setting(bit, "vih", variables, si(variables.get("vdd", 0.7)))
        vil = self.setting(bit, "vil", variables, 0.0)
        voh = self.setting(bit, "voh", variables, vil + 0.8 * (vih - vil))
        vol = self.setting(bit, "vol", variables, vil + 0.2 * (vih - vil))
        return vih, vil, voh, vol

    # ---- stimulus -------------------------------------------------------------------------------
    def sources(self, variables) -> list[str]:
        """SPICE PWL sources for the inputs."""
        lines = [f"* vector file {self.path}"]
        for b in self.inputs():
            vih, vil, _, _ = self.levels(b, variables)
            slope = self.setting(b, "slope", variables, None)
            tr = self.setting(b, "trise", variables, slope if slope is not None else 10e-12)
            tf = self.setting(b, "tfall", variables, slope if slope is not None else 10e-12)
            delay = self.setting(b, "idelay", variables, 0.0) + self.setting(b, "tdelay", variables, 0.0)
            pts = []
            level = None
            for t, v in zip(self.times, b.values):
                if v in ("X", "Z"):                        # don't care / tri-state: hold the level
                    continue
                target = vih if v == "1" else vil
                t += delay
                if level is None:                          # the first defined value, from t = 0
                    pts.append((0.0, target))
                elif target != level:
                    edge = tr if target > level else tf
                    t0 = max(t, pts[-1][0])
                    pts.append((t0, level))
                    pts.append((t0 + edge, target))
                level = target
            if not pts:
                continue
            body = " ".join(f"{t:.6g} {v:.6g}" for t, v in _dedup(pts))
            lines.append(f"Vvec_{_safe(b.name)} {b.name} 0 PWL({body})")
        return lines

    # ---- checking -------------------------------------------------------------------------------
    def check_times(self, variables):
        """When each vector's outputs are checked: after odelay if given, else just before the
        next vector (the last one: one period, or the average spacing, after it)."""
        out = []
        n = len(self.times)
        spacing = self.period or ((self.times[-1] - self.times[0]) / (n - 1) if n > 1 else 1e-9)
        for k, t in enumerate(self.times):
            nxt = self.times[k + 1] if k + 1 < n else t + spacing
            out.append((t, nxt))
        return out

    def check(self, signal, variables, t_stop=None):
        """Compare the outputs: `signal(name)` gives a Waveform. Returns [mismatch dicts]."""
        errors = []
        windows = self.check_times(variables)
        for b in self.outputs():
            _, _, voh, vol = self.levels(b, variables)
            try:
                w = signal(b.name)
            except Exception as e:
                errors.append({"time": 0.0, "signal": b.name, "expected": "-", "got": f"no waveform ({e})"})
                continue
            od = b.settings.get("odelay", self.settings.get("odelay"))
            for (t, nxt), exp in zip(windows, b.values):
                if exp in ("X", "Z"):
                    continue
                if od is not None:
                    at = t + self.setting(b, "odelay", variables, 0.0) + self.setting(b, "tdelay", variables, 0.0)
                else:
                    at = t + 0.99 * (nxt - t)
                if t_stop is not None and at > t_stop:
                    continue
                v = float(_interp(w, at))
                ok = v > voh if exp == "1" else v < vol
                if not ok:
                    got = "1" if v > voh else "0" if v < vol else "between"
                    errors.append({"time": at, "signal": b.name, "expected": exp, "got": got, "value": v})
        return sorted(errors, key=lambda e: e["time"])


def _interp(w: Waveform, at):
    import numpy as np
    return np.interp(at, w.x, w.real_y)


def _dedup(pts):
    out = []
    for t, v in pts:
        if out and abs(out[-1][0] - t) < 1e-18:
            if out[-1][1] == v:
                continue
            t = out[-1][0] + 1e-15                       # PWL times must increase
        out.append((t, v))
    return out


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def _bus(name):
    m = re.match(r"^(.+?)\[(\d+):(\d+)\]$", name)
    if not m:
        return None
    base, a, b = m.group(1), int(m.group(2)), int(m.group(3))
    step = -1 if a > b else 1
    return [f"{base}[{i}]" for i in range(a, b + step, step)]


def parse(path) -> VectorFile:
    text = Path(path).read_text()
    radix, io, names = None, None, None
    tunit, period = 1e-9, None
    settings, masked = {}, []
    data = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        # comments: a line starting with * or ;, and anything after a ; (a * inside a line is
        # multiplication: voh 0.8*vdd)
        line = raw.split(";", 1)[0].strip() if not raw.lstrip().startswith(("*", ";")) else ""
        if not line:
            continue
        t = line.split()
        kw = t[0].lower()
        if kw == "radix":
            radix = [int(x) for x in t[1:]]
        elif kw == "io":
            io = [x.lower() for x in t[1:]]
        elif kw == "vname":
            names = t[1:]
        elif kw == "tunit":
            if t[1].lower() not in TUNITS:
                raise VectorError(f"{path}:{lineno}: unknown tunit {t[1]}")
            tunit = TUNITS[t[1].lower()]
        elif kw == "period":
            period = float(t[1])
        elif kw in SETTINGS:
            if len(t) > 2:
                masked.append((kw, t[1], t[2:], lineno))
            else:
                settings[kw] = t[1]
        elif kw in ("out", "outz", "triz", "enable", "vref", "vth"):
            continue                                       # drivers / tri-state: not modelled
        elif re.match(r"^[0-9a-fA-FxXzZ.+-]", kw):
            data.append((lineno, t))
        else:
            raise VectorError(f"{path}:{lineno}: unknown statement {t[0]}")
    if radix is None:
        raise VectorError(f"{path}: no radix statement")
    ncol = len(radix)
    io = io or ["i"] * ncol
    if len(io) != ncol:
        raise VectorError(f"{path}: io has {len(io)} entries for {ncol} columns")
    if names is None:
        raise VectorError(f"{path}: no vname statement")
    # names per column: a bus for multi-bit columns, or one name per bit
    bits, k = [], 0
    for col, nb in enumerate(radix):
        if nb < 1 or nb > 4:
            raise VectorError(f"{path}: radix {nb} (1-4 bits per column)")
        if k >= len(names):
            raise VectorError(f"{path}: vname is missing names for column {col + 1}")
        bus = _bus(names[k])
        if bus and len(bus) == nb:
            col_names = bus
            k += 1
        elif nb == 1:
            col_names = [names[k]]
            k += 1
        else:
            col_names = names[k:k + nb]
            k += nb
            if len(col_names) != nb:
                raise VectorError(f"{path}: column {col + 1} needs {nb} names")
        for n in col_names:
            bits.append(Bit(n.lower(), io[col], col))
    # time settings to seconds
    for key in ("trise", "tfall", "slope", "idelay", "odelay", "tdelay"):
        if key in settings:
            settings[key] = float(settings[key]) * tunit
    for kw, val, mask, lineno in masked:
        if len(mask) != ncol:
            raise VectorError(f"{path}:{lineno}: the mask of {kw} needs {ncol} digits")
        v = float(val) * tunit if kw in ("trise", "tfall", "slope", "idelay", "odelay", "tdelay") else val
        for b in bits:
            if mask[b.column] not in ("0",):
                b.settings[kw] = v
    # vectors
    times = []
    for n, (lineno, t) in enumerate(data):
        if period is None:
            if len(t) < 2:
                raise VectorError(f"{path}:{lineno}: a time and the column values expected (no period)")
            times.append(float(t[0]) * tunit)
            vals = t[1:]
        else:
            times.append(n * period * tunit)
            vals = t
        if len(vals) == 1 and len(vals[0]) == ncol and ncol > 1:   # compact "0110"
            vals = list(vals[0])
        if len(vals) != ncol:
            raise VectorError(f"{path}:{lineno}: {len(vals)} values for {ncol} columns")
        for col, (tok, nb) in enumerate(zip(vals, radix)):
            col_bits = [b for b in bits if b.column == col]
            tok = tok.upper()
            if tok in ("X", "Z"):
                for b in col_bits:
                    b.values.append(tok)
                continue
            try:
                num = int(tok, 16)
            except ValueError:
                raise VectorError(f"{path}:{lineno}: bad value {tok!r}") from None
            if num >= 2 ** nb:
                raise VectorError(f"{path}:{lineno}: {tok} does not fit {nb} bit(s)")
            for i, b in enumerate(col_bits):                 # MSB first
                b.values.append(str((num >> (nb - 1 - i)) & 1))
    if any(b <= a for a, b in zip(times, times[1:])):
        raise VectorError(f"{path}: vector times must increase")
    return VectorFile(str(path), bits, times, period * tunit if period else None, settings)
