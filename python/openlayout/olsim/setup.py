"""The OLSim setup: tests, design variables, corners and outputs - one JSON file, the cell's
`olsim` view (<cell>.olsim).

    {"tests": [{"name": "tran", "design": {"lib": "mychip", "cell": "tb_inv", "view": "config"},   # its config view
                "analyses": [{"type": "tran", "stop": "200p", "step": "0.5p"}],
                "vectors": ["stim.vec"], "section": "tt", "temp": "27",
                "extracted": ["mychip/inv"]}],          # post-layout: inv's PEX netlist instead of its schematic
     "variables": {"vdd": "0.7", "cload": "1f 2f 4f"},
     "corners": [{"name": "ss_hot", "section": "ss", "temp": "125", "variables": {"vdd": "0.63"}}],
     "outputs": [{"test": "tran", "name": "tpd", "expr": "delay(v('in'), v('out'), vdd/2, vdd/2)",
                  "spec": "< 10p"},
                 {"test": "tran", "name": "out", "expr": "v('out')", "plot": true}],
     "jobs": 4}

Variable values may sweep: "1f 2f 4f", "0.6:0.05:0.8" (start:step:stop) or "1f,2f,4f".
"""
from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .calc import fmt, si

ANALYSIS_TYPES = ("tran", "dc", "ac", "op", "noise")
ANALYSIS_DEFAULTS = {
    "tran": {"step": "1p", "stop": "1n", "start": "0"},
    "dc": {"source": "VIN", "start": "0", "stop": "0.7", "step": "1m"},
    "ac": {"variation": "dec", "points": "20", "start": "1k", "stop": "100G"},
    "op": {},
    "noise": {"output": "v(out)", "source": "VIN", "variation": "dec", "points": "10", "start": "1k", "stop": "100G"},
}
SECTIONS = ("tt", "ff", "ss", "fs", "sf")


@dataclass
class Analysis:
    type: str
    enabled: bool = True
    params: dict = field(default_factory=dict)

    def spice(self) -> str:
        p = {**ANALYSIS_DEFAULTS[self.type], **self.params}
        if self.type == "tran":
            return f".tran {p['step']} {p['stop']} {p['start']}"
        if self.type == "dc":
            return f".dc {p['source']} {p['start']} {p['stop']} {p['step']}"
        if self.type == "ac":
            return f".ac {p['variation']} {p['points']} {p['start']} {p['stop']}"
        if self.type == "op":
            return ".op"
        if self.type == "noise":
            return f".noise {p['output']} {p['source']} {p['variation']} {p['points']} {p['start']} {p['stop']}"
        raise ValueError(self.type)

    def summary(self) -> str:
        return self.spice()[1:]


@dataclass
class Test:
    name: str
    design: dict = field(default_factory=dict)      # {"lib", "cell"[, "view": "config"]} | {"schematic": path} | {"netlist": path}
    analyses: list = field(default_factory=list)
    vectors: list = field(default_factory=list)     # .vec files (relative to the setup file)
    enabled: bool = True
    section: str = "tt"
    temp: str = "27"
    options: str = ""                               # extra SPICE lines (.options ...)
    saves: str = "all"                              # "all" or "v(out) i(vdd) ..."
    variables: dict = field(default_factory=dict)   # overrides of the global ones
    extracted: list = field(default_factory=list)   # cells simulated with their PEX netlist ("lib/cell" or "cell")

    def design_label(self) -> str:
        d = self.design
        if "lib" in d:
            return f"{d['lib']}/{d['cell']}" + (" config" if d.get("view") == "config" else "")
        return Path(d.get("schematic") or d.get("netlist") or "?").name


@dataclass
class Corner:
    name: str
    enabled: bool = True
    section: str = ""                               # "" = the test's
    temp: str = ""
    variables: dict = field(default_factory=dict)


@dataclass
class Output:
    test: str
    name: str
    expr: str
    spec: str = ""
    plot: bool = False
    analysis: str = ""                              # "" = the test's first analysis

    @property
    def is_signal(self) -> bool:
        e = self.expr.replace(" ", "")
        return e.startswith(("v(", "i(", "VT(", "VS(", "VF(", "IT(", "IS(", "IF(")) and e.count("(") == 1


@dataclass
class Point:
    """One simulation: a test at one corner and one combination of swept variables."""
    index: int
    test: str
    corner: str
    section: str
    temp: str
    variables: dict

    @property
    def label(self) -> str:
        swept = ", ".join(f"{k}={v}" for k, v in self.variables.items() if k in self._swept)
        return self.corner + (f" {swept}" if swept else "")

    _swept: tuple = ()

    def as_dict(self):
        return {"index": self.index, "test": self.test, "corner": self.corner, "section": self.section,
                "temp": self.temp, "variables": self.variables, "swept": list(self._swept), "label": self.label}


def sweep_values(spec) -> list[str]:
    """'0.6:0.05:0.8' -> ['0.6', '0.65', ...]; '1f 2f' / '1f,2f' -> ['1f', '2f']; '0.7' -> ['0.7']"""
    s = str(spec).strip()
    if ":" in s and len(s.split(":")) == 3 and " " not in s:
        a, step, b = (si(x) for x in s.split(":"))
        if step == 0 or (b - a) / step < 0:
            raise ValueError(f"bad sweep {spec!r}")
        n = int(round((b - a) / step))
        return [fmt(a + i * step, 6) for i in range(n + 1)]
    parts = [p for p in s.replace(",", " ").split() if p]
    return parts or [""]


@dataclass
class Setup:
    tests: list = field(default_factory=list)
    variables: dict = field(default_factory=dict)
    corners: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    nominal: bool = True
    jobs: int = 4
    path: str = ""

    # ---- file ----------------------------------------------------------------------------------
    @staticmethod
    def load(path) -> "Setup":
        d = json.loads(Path(path).read_text())
        s = Setup(path=str(path))
        for t in d.get("tests", []):
            t = dict(t)
            t["analyses"] = [Analysis(a["type"], a.get("enabled", True),
                                      {k: str(v) for k, v in a.items() if k not in ("type", "enabled")})
                             for a in t.get("analyses", [])]
            s.tests.append(Test(**t))
        s.variables = {k: str(v) for k, v in d.get("variables", {}).items()}
        s.corners = [Corner(**c) for c in d.get("corners", [])]
        s.outputs = [Output(**o) for o in d.get("outputs", [])]
        s.nominal = d.get("nominal", True)
        s.jobs = int(d.get("jobs", 4))
        return s

    def to_dict(self) -> dict:
        tests = []
        for t in self.tests:
            td = asdict(t)
            td["analyses"] = [{"type": a.type, **({} if a.enabled else {"enabled": False}), **a.params}
                              for a in t.analyses]
            tests.append(td)
        return {"tests": tests, "variables": self.variables, "corners": [asdict(c) for c in self.corners],
                "outputs": [asdict(o) for o in self.outputs], "nominal": self.nominal, "jobs": self.jobs}

    def save(self, path=None) -> None:
        path = Path(path or self.path)
        self.path = str(path)
        path.write_text(json.dumps(self.to_dict(), indent=1) + "\n", newline="\n")

    @property
    def directory(self) -> Path:
        return Path(self.path).parent if self.path else Path.cwd()

    def test(self, name) -> Test | None:
        return next((t for t in self.tests if t.name == name), None)

    # ---- the run plan --------------------------------------------------------------------------
    def corners_to_run(self) -> list[Corner]:
        out = [Corner("Nominal")] if self.nominal else []
        return out + [c for c in self.corners if c.enabled]

    def points(self) -> list[Point]:
        pts = []
        for test in (t for t in self.tests if t.enabled):
            for corner in self.corners_to_run():
                values = {**self.variables, **test.variables, **corner.variables}
                names = list(values)
                lists = [sweep_values(values[n]) for n in names]
                swept = tuple(n for n, l in zip(names, lists) if len(l) > 1)
                for combo in itertools.product(*lists):
                    p = Point(len(pts), test.name, corner.name, corner.section or test.section,
                              corner.temp or test.temp, dict(zip(names, combo)))
                    p._swept = swept
                    pts.append(p)
        return pts


def default_setup(lib=None, cell=None, schematic=None, netlist=None) -> Setup:
    design = {"lib": lib, "cell": cell} if lib else {"schematic": str(schematic)} if schematic else \
        {"netlist": str(netlist)}
    return Setup(tests=[Test("tran", design, [Analysis("tran", True, {"step": "1p", "stop": "1n", "start": "0"})])])
