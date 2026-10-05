"""The waveform calculator: OLSim output expressions and the viewer's calculator.

Expressions are Python syntax over waveforms and numbers, with SPICE suffixes allowed on numbers
(10p, 1.5meg, 3G) and Cadence-calculator style functions:

    v("out")  i("vdd")             a waveform of the current analysis (also VT / VS / VF / IT ...
                                   for transient / dc / ac, and "/out" with Cadence's leading slash)
    value(w, x)  cross(w, level, n=1, edge="either")  delay(w1, w2, th1, th2, edge1, edge2, n1, n2)
    riseTime(w, lo=10, hi=90)  fallTime(...)  slewRate(...)  frequency(w)  period(w)  dutyCycle(w)
    ymax ymin xmax xmin ptp average rms integ deriv clip(w, x0, x1)  overshoot(w)  settlingTime(w, tol=2)
    db20 db10 mag phase real imag  bandwidth(w, db=3)  ugf(w)  phaseMargin(w)  gainMargin(w)
    sqrt log10 exp abs min max ... and design variables by name (vdd/2)

    evaluate(expr, Context(plots, variables, analysis="tran")) -> float | Waveform
    check_spec(value, "< 10p") -> True / False / None
"""
from __future__ import annotations

import math
import re

import numpy as np

SI = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "meg": 1e6, "M": 1e6,
      "G": 1e9, "T": 1e12, "a": 1e-18}
NUM_RE = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(meg|MEG|Meg|[afpnumkKMGT])?[A-Za-z]*\s*$")
EXPR_NUM_RE = re.compile(r"(?<![\w.\"'])((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(meg|[afpnumkKMGT])(?![\w(])")


class CalcError(Exception):
    pass


def si(text) -> float:
    """'10p' -> 1e-11, '1.5meg' -> 1.5e6, 3 -> 3.0"""
    if isinstance(text, (int, float)):
        return float(text)
    m = NUM_RE.match(str(text))
    if not m:
        raise ValueError(f"not a number: {text!r}")
    v = float(m.group(1))
    suf = m.group(2)
    if suf:
        v *= SI["meg"] if suf.lower() == "meg" else SI[suf]
    return v


def fmt(v, digits=4) -> str:
    """Engineering notation with SPICE suffixes: 1.234e-11 -> '12.34p'."""
    if v is None:
        return ""
    if isinstance(v, Waveform):
        return "wave"
    if isinstance(v, complex):
        return f"{fmt(v.real, digits)}{'+' if v.imag >= 0 else '-'}j{fmt(abs(v.imag), digits)}"
    if isinstance(v, str):
        return v
    if v != v:
        return "nan"
    if v == 0 or not math.isfinite(v):
        return f"{v:g}"
    exp = int(math.floor(math.log10(abs(v)) / 3) * 3)
    exp = max(-18, min(12, exp))
    suffix = {-18: "a", -15: "f", -12: "p", -9: "n", -6: "u", -3: "m", 0: "", 3: "k", 6: "M", 9: "G", 12: "T"}[exp]
    return f"{v / 10 ** exp:.{digits}g}{suffix}"


# ---- waveforms --------------------------------------------------------------------------------------
class Waveform:
    def __init__(self, x, y, name="", xname="x"):
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y)
        self.name, self.xname = name, xname

    def __repr__(self):
        return f"<Waveform {self.name} {len(self.x)} points>"

    def __len__(self):
        return len(self.x)

    def _other(self, o):
        if isinstance(o, Waveform):
            if len(o.x) == len(self.x) and np.array_equal(o.x, self.x):
                return o.y
            if np.iscomplexobj(o.y):
                return np.interp(self.x, o.x, o.y.real) + 1j * np.interp(self.x, o.x, o.y.imag)
            return np.interp(self.x, o.x, o.y)
        return o

    def _op(self, o, f, name):
        return Waveform(self.x, f(self.y, self._other(o)), name, self.xname)

    def __add__(self, o): return self._op(o, np.add, f"({self.name}+..)")
    def __radd__(self, o): return self.__add__(o)
    def __sub__(self, o): return self._op(o, np.subtract, f"({self.name}-..)")
    def __rsub__(self, o): return Waveform(self.x, o - self.y, f"(..-{self.name})", self.xname)
    def __mul__(self, o): return self._op(o, np.multiply, f"({self.name}*..)")
    def __rmul__(self, o): return self.__mul__(o)
    def __truediv__(self, o): return self._op(o, np.divide, f"({self.name}/..)")
    def __rtruediv__(self, o): return Waveform(self.x, o / self.y, f"(../{self.name})", self.xname)
    def __pow__(self, o): return self._op(o, np.power, f"({self.name}**..)")
    def __neg__(self): return Waveform(self.x, -self.y, f"-{self.name}", self.xname)
    def __abs__(self): return Waveform(self.x, np.abs(self.y), f"abs({self.name})", self.xname)

    @property
    def real_y(self):
        return self.y.real if np.iscomplexobj(self.y) else self.y


def _w(w, fn):
    if not isinstance(w, Waveform):
        raise CalcError(f"{fn}: expects a waveform")
    return w


def _crossings(w, level, edge="either"):
    """x of every crossing of `level` (linear interpolation), filtered by edge."""
    x, y = w.x, w.real_y - level
    s = np.signbit(y)
    idx = np.nonzero(s[:-1] != s[1:])[0]
    out = []
    for i in idx:
        rising = y[i] < y[i + 1]
        if edge in ("rise", "rising") and not rising or edge in ("fall", "falling") and rising:
            continue
        dy = y[i + 1] - y[i]
        out.append(x[i] if dy == 0 else x[i] - y[i] * (x[i + 1] - x[i]) / dy)
    return out


def value(w, at):
    w = _w(w, "value")
    if np.iscomplexobj(w.y):
        return complex(np.interp(at, w.x, w.y.real), np.interp(at, w.x, w.y.imag))
    return float(np.interp(at, w.x, w.y))


def cross(w, level, n=1, edge="either"):
    c = _crossings(_w(w, "cross"), level, edge)
    if len(c) < n:
        raise CalcError(f"cross: {w.name} crosses {fmt(level)} only {len(c)} time(s) ({edge})")
    return float(c[n - 1] if n > 0 else c[n])


def delay(w1, w2, th1=None, th2=None, edge1="either", edge2="either", n1=1, n2=1):
    """Time from the n1-th crossing of th1 by w1 to the n2-th crossing of th2 by w2 after it
    (thresholds default to the middle of each waveform's range)."""
    th1 = (ymax(w1) + ymin(w1)) / 2 if th1 is None else th1
    th2 = (ymax(w2) + ymin(w2)) / 2 if th2 is None else th2
    t1 = cross(w1, th1, n1, edge1)
    after = [t for t in _crossings(w2, th2, edge2) if t >= t1]
    if len(after) < n2:
        raise CalcError(f"delay: {w2.name} does not cross {fmt(th2)} ({edge2}) after {fmt(t1)}s")
    return float(after[n2 - 1] - t1)


def _levels(w, initial, final):
    lo = ymin(w) if initial is None else initial
    hi = ymax(w) if final is None else final
    return lo, hi


def riseTime(w, lo=10, hi=90, initial=None, final=None, n=1):
    a, b = _levels(w, initial, final)
    t_lo = cross(w, a + (b - a) * lo / 100, n, "rise")
    t_hi = [t for t in _crossings(w, a + (b - a) * hi / 100, "rise") if t >= t_lo]
    if not t_hi:
        raise CalcError("riseTime: no rising edge reaching the upper level")
    return float(t_hi[0] - t_lo)


def fallTime(w, hi=90, lo=10, initial=None, final=None, n=1):
    a, b = _levels(w, final, initial)          # falls from the max (initial) to the min (final)
    t_hi = cross(w, a + (b - a) * hi / 100, n, "fall")
    t_lo = [t for t in _crossings(w, a + (b - a) * lo / 100, "fall") if t >= t_hi]
    if not t_lo:
        raise CalcError("fallTime: no falling edge reaching the lower level")
    return float(t_lo[0] - t_hi)


def slewRate(w, lo=10, hi=90, edge="rise"):
    a, b = ymin(w), ymax(w)
    dt = riseTime(w, lo, hi) if edge == "rise" else fallTime(w, hi, lo)
    return (b - a) * (hi - lo) / 100 / dt


def ymax(w): return float(np.max(_w(w, "ymax").real_y))
def ymin(w): return float(np.min(_w(w, "ymin").real_y))
def xmax(w): return float(w.x[int(np.argmax(_w(w, "xmax").real_y))])
def xmin(w): return float(w.x[int(np.argmin(_w(w, "xmin").real_y))])
def ptp(w): return ymax(w) - ymin(w)


def integ(w, x0=None, x1=None):
    w = clip(w, x0, x1) if x0 is not None or x1 is not None else _w(w, "integ")
    return float(np.trapezoid(w.real_y, w.x))


def average(w, x0=None, x1=None):
    w = clip(w, x0, x1) if x0 is not None or x1 is not None else _w(w, "average")
    span = w.x[-1] - w.x[0]
    return integ(w) / span if span else float(np.mean(w.real_y))


def rms(w, x0=None, x1=None):
    w = clip(w, x0, x1) if x0 is not None or x1 is not None else _w(w, "rms")
    span = w.x[-1] - w.x[0]
    return math.sqrt(float(np.trapezoid(w.real_y ** 2, w.x)) / span) if span else float(np.sqrt(np.mean(w.real_y ** 2)))


def deriv(w):
    w = _w(w, "deriv")
    return Waveform(w.x, np.gradient(w.real_y, w.x), f"deriv({w.name})", w.xname)


def clip(w, x0=None, x1=None):
    w = _w(w, "clip")
    x0 = w.x[0] if x0 is None else x0
    x1 = w.x[-1] if x1 is None else x1
    inside = (w.x > x0) & (w.x < x1)
    xs = np.concatenate([[x0], w.x[inside], [x1]])
    if np.iscomplexobj(w.y):
        ys = np.interp(xs, w.x, w.y.real) + 1j * np.interp(xs, w.x, w.y.imag)
    else:
        ys = np.interp(xs, w.x, w.y)
    return Waveform(xs, ys, f"clip({w.name})", w.xname)


def _rising(w, level):
    level = (ymax(w) + ymin(w)) / 2 if level is None else level
    return _crossings(w, level, "rise"), level


def period(w, level=None):
    c, _ = _rising(_w(w, "period"), level)
    if len(c) < 2:
        raise CalcError("period: fewer than two rising crossings")
    return float((c[-1] - c[0]) / (len(c) - 1))


def frequency(w, level=None):
    return 1.0 / period(w, level)


def dutyCycle(w, level=None):
    w = _w(w, "dutyCycle")
    level = (ymax(w) + ymin(w)) / 2 if level is None else level
    r, f = _crossings(w, level, "rise"), _crossings(w, level, "fall")
    if len(r) < 2:
        raise CalcError("dutyCycle: fewer than two rising crossings")
    highs = []
    for a, b in zip(r, r[1:]):                 # each full period: rising edge to the fall inside it
        fall = next((t for t in f if a < t < b), None)
        if fall is not None:
            highs.append((fall - a) / (b - a))
    if not highs:
        raise CalcError("dutyCycle: no complete period")
    return 100.0 * float(np.mean(highs))


def overshoot(w, initial=None, final=None):
    """Percent past the final value, relative to the step (final defaults to the last value)."""
    w = _w(w, "overshoot")
    a = float(w.real_y[0]) if initial is None else initial
    b = float(w.real_y[-1]) if final is None else final
    peak = ymax(w) if b >= a else ymin(w)
    return 100.0 * (peak - b) / (b - a) if b != a else 0.0


def settlingTime(w, tol=2, final=None, start=None):
    """Time (from `start`, default the first x) after which w stays within tol % of its final
    value (of the step from the first value)."""
    w = _w(w, "settlingTime")
    y = w.real_y
    b = float(y[-1]) if final is None else final
    band = abs(b - float(y[0])) * tol / 100 or abs(b) * tol / 100
    outside = np.nonzero(np.abs(y - b) > band)[0]
    t0 = w.x[0] if start is None else start
    if len(outside) == 0:
        return 0.0
    i = outside[-1]
    return float((w.x[min(i + 1, len(w.x) - 1)]) - t0)


# ---- AC -----------------------------------------------------------------------------------------
def mag(w): return Waveform(w.x, np.abs(w.y), f"mag({w.name})", w.xname) if isinstance(w, Waveform) else abs(w)
def db20(w): return Waveform(w.x, 20 * np.log10(np.abs(w.y)), f"dB20({w.name})", w.xname) if isinstance(w, Waveform) else 20 * math.log10(abs(w))
def db10(w): return Waveform(w.x, 10 * np.log10(np.abs(w.y)), f"dB10({w.name})", w.xname) if isinstance(w, Waveform) else 10 * math.log10(abs(w))
def real(w): return Waveform(w.x, np.real(w.y), f"real({w.name})", w.xname) if isinstance(w, Waveform) else complex(w).real
def imag(w): return Waveform(w.x, np.imag(w.y), f"imag({w.name})", w.xname) if isinstance(w, Waveform) else complex(w).imag


def phase(w):
    if isinstance(w, Waveform):
        return Waveform(w.x, np.degrees(np.unwrap(np.angle(w.y))), f"phase({w.name})", w.xname)
    return math.degrees(np.angle(w))


def bandwidth(w, db=3, kind="low"):
    """The -db point relative to the response at the lowest frequency (kind "low") or its peak."""
    g = db20(_w(w, "bandwidth"))
    ref = g.y[0] if kind == "low" else float(np.max(g.y))
    c = _crossings(Waveform(np.log10(g.x), g.y), ref - db, "fall")
    if not c:
        raise CalcError(f"bandwidth: never falls {db} dB")
    return float(10 ** c[0])


def ugf(w):
    """Unity-gain frequency (0 dB crossing, falling)."""
    g = db20(_w(w, "ugf"))
    c = _crossings(Waveform(np.log10(g.x), g.y), 0.0, "fall")
    if not c:
        raise CalcError("ugf: the gain never falls through 0 dB")
    return float(10 ** c[0])


def phaseMargin(w):
    f = ugf(w)
    return 180.0 + value(phase(w), f)


def gainMargin(w):
    p = phase(_w(w, "gainMargin"))
    c = _crossings(Waveform(np.log10(p.x), p.y), -180.0, "fall")
    if not c:
        raise CalcError("gainMargin: the phase never reaches -180")
    return -value(db20(w), 10 ** c[0])


# ---- evaluation ---------------------------------------------------------------------------------
FUNCS = {f.__name__: f for f in (value, cross, delay, riseTime, fallTime, slewRate, ymax, ymin, xmax, xmin, ptp,
                                 integ, average, rms, deriv, clip, period, frequency, dutyCycle, overshoot,
                                 settlingTime, mag, db20, db10, real, imag, phase, bandwidth, ugf, phaseMargin,
                                 gainMargin)}
FUNCS.update({"dB20": db20, "dB10": db10, "freq": frequency, "average": average, "avg": average,
              "integral": integ, "peakToPeak": ptp, "unityGainFreq": ugf})
MATH = {n: getattr(math, n) for n in ("sqrt", "log", "log10", "exp", "sin", "cos", "tan", "atan", "pi", "e",
                                      "floor", "ceil")}
MATH.update({"abs": abs, "min": min, "max": max, "round": round, "float": float, "int": int, "len": len})

ANALYSIS_ALIASES = {"VT": ("v", "tran"), "IT": ("i", "tran"), "VS": ("v", "dc"), "IS": ("i", "dc"),
                    "VF": ("v", "ac"), "IF": ("i", "ac"), "VN": ("v", "noise")}


class Context:
    """What an expression sees: the plots of one simulation point (or a function giving them),
    the design variables, and the default analysis for v() / i()."""

    def __init__(self, plots, variables=None, analysis=None):
        self.plots = plots
        self.variables = variables or {}
        self.analysis = analysis

    def plot(self, kind=None):
        kind = kind or self.analysis
        if kind:
            for p in self.plots:
                if p.kind == kind:
                    return p
            raise CalcError(f"no {kind} results")
        for p in self.plots:
            if p.kind != "op":
                return p
        if self.plots:
            return self.plots[0]
        raise CalcError("no results")

    def signal(self, prefix, name, kind=None):
        p = self.plot(kind)
        name = name.lstrip("/").replace("/", ".")
        key = name if name.lower().startswith(("v(", "i(")) or prefix is None else f"{prefix}({name})"
        if key not in p:
            if prefix == "i" and f"i({name})" not in p and f"{name}#branch" in p:
                key = f"{name}#branch"
            else:
                raise CalcError(f"{key} not in the {p.kind} results")
        if p.kind == "op":
            return complex(p[key][0]) if p.complex else float(p[key][0])
        return Waveform(p.x, p[key], key, p.scale)

    def namespace(self):
        ns = dict(FUNCS)
        ns.update(MATH)
        for k, v in self.variables.items():
            try:
                ns[k] = si(v)
            except (ValueError, TypeError):
                pass
        ns["v"] = lambda n, analysis=None: self.signal("v", n, analysis)
        ns["i"] = lambda n, analysis=None: self.signal("i", n, analysis)
        for alias, (pre, kind) in ANALYSIS_ALIASES.items():
            ns[alias] = (lambda pre, kind: lambda n: self.signal(pre, n, kind))(pre, kind)
        ns["op"] = lambda n: self.signal(None if n.lower().startswith(("v(", "i(")) else "v", n, "op")
        return ns


def prepare(expr: str) -> str:
    """SPICE-suffixed numbers to Python (10p -> 10e-12), outside string literals."""
    parts = re.split(r"(\"[^\"]*\"|'[^']*')", expr)
    for i in range(0, len(parts), 2):
        parts[i] = EXPR_NUM_RE.sub(lambda m: f"({m.group(1)}*{SI['meg'] if m.group(2) == 'meg' else SI[m.group(2)]!r})",
                                   parts[i])
    return "".join(parts)


def evaluate(expr: str, ctx: Context):
    """float, complex or Waveform; raises CalcError with a readable message."""
    try:
        code = compile(prepare(expr), "<expression>", "eval")
    except SyntaxError as e:
        raise CalcError(f"syntax error: {e.msg}") from None
    try:
        return eval(code, {"__builtins__": {}}, ctx.namespace())
    except CalcError:
        raise
    except Exception as e:
        raise CalcError(f"{type(e).__name__}: {e}") from None


def guess_unit(expr: str) -> str:
    """The unit an output expression most likely has (for axis labels)."""
    e = expr.replace(" ", "").lower()
    if any(f in e for f in ("delay(", "risetime(", "falltime(", "period(", "cross(", "settlingtime(", "xmax(",
                            "xmin(")):
        return "s"
    if any(f in e for f in ("frequency(", "freq(", "bandwidth(", "ugf(", "unitygainfreq(")):
        return "Hz"
    if any(f in e for f in ("db20(", "db10(", "gainmargin(")):
        return "dB"
    if "phase" in e:
        return "°"
    if "slewrate(" in e:
        return "V/s"
    if "i(" in e and "v(" not in e:
        return "A"
    if "v(" in e or "vt(" in e:
        return "V"
    return ""


def variable_unit(name: str) -> str:
    """A design variable's likely unit, by the usual naming (cload -> F, rload -> Ohm, vdd -> V)."""
    n = name.lower()
    if n.startswith("temp"):
        return "°C"
    return {"c": "F", "r": "Ω", "v": "V", "i": "A", "l": "m", "w": "m", "t": "s", "f": "Hz"}.get(n[:1], "")


SPEC_RE = re.compile(r"^\s*(<=|>=|==|<|>|range)\s*(.*)$")


def check_spec(val, spec: str):
    """True / False against a spec ("< 10p", ">= 1G", "range 0.3 0.4", "== 0"); None if there is
    no spec or no number."""
    if not spec or not spec.strip() or not isinstance(val, (int, float)) or val != val:
        return None
    m = SPEC_RE.match(spec)
    if not m:
        raise CalcError(f"bad spec {spec!r}")
    op, rest = m.group(1), m.group(2).split()
    if op == "range":
        lo, hi = si(rest[0]), si(rest[1])
        return lo <= val <= hi
    ref = si(rest[0])
    return {"<": val < ref, "<=": val <= ref, ">": val > ref, ">=": val >= ref,
            "==": abs(val - ref) <= 1e-12 * max(1.0, abs(ref))}[op]
