"""Running a OLSim setup: netlist each test's testbench, build one ngspice deck per point
(corner x swept variables), run them in parallel, evaluate the outputs and the vector checks,
and keep everything in a history:

    <results>/<history>/setup.json            the setup as run
                        netlist/<test>.spice  the testbench netlist (cleaned, the config's views bound)
                        points/<n>/deck.sp, ngspice.log, sim.raw, results.json
                        history.json          points, output values, pass / fail

    run = Run(setup, results_dir, workarea=None); run.start(progress=callback); run.wait()
    History.load(dir).value(point, output)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal as _signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import rawfile, vectors
from .calc import CalcError, Context, Waveform, check_spec, evaluate, fmt
from .config import Config, ConfigError, bind, counts, find_pex
from .setup import Point, Setup

ANALYSIS_RE = re.compile(r"^\s*\.(tran|dc|ac|op|noise|tf|sens|pz|disto|four|meas|measure)\b", re.I)
DROP_RE = re.compile(r"^\s*\.(end|temp)\b|^\s*\.lib\s+\S*asap7\.lib\b", re.I)
PARAM_RE = re.compile(r"^\s*\.param\s+(.*)$", re.I)
BRACE_RE = re.compile(r"\{([^{}]*)\}")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NOT_VARS = {"temper", "hertz", "time", "pi", "e", "abs", "sqrt", "exp", "log", "ln", "log10", "sin", "cos",
            "tan", "atan", "sinh", "cosh", "tanh", "min", "max", "pow", "pwr", "int", "floor", "ceil", "sgn",
            "nint", "u", "uramp", "agauss", "gauss", "unif", "aunif", "limit", "ternary_fcn", "if", "defined"}


class OLSimError(Exception):
    pass


# ---- netlists -----------------------------------------------------------------------------------
def netlist_schematic(sch: Path, out_dir: Path, workarea_root: Path | None) -> str:
    """xschem: the testbench as a top-level netlist."""
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = ["xschem", "-x", "-q", "-r", "-n", "-s", "-o", str(out_dir), str(sch)]
    res = subprocess.run(argv, cwd=workarea_root or sch.parent, capture_output=True, text=True, timeout=300)
    net = out_dir / f"{sch.stem}.spice"
    if not net.is_file():
        raise OLSimError(f"xschem could not netlist {sch}:\n{(res.stdout + res.stderr)[-600:]}")
    return net.read_text()


def clean_netlist(text: str):
    """The testbench netlist without what OLSim controls: .control blocks, analyses and
    measurements, the model corner (.lib asap7.lib), .temp, .end. Returns (body, removed)."""
    out, removed = [], []
    skipping = in_control = False
    for line in text.splitlines():
        low = line.strip().lower()
        if in_control:
            removed.append(line)
            if low.startswith(".endc"):
                in_control = False
            continue
        if low.startswith(".control"):
            in_control = True
            removed.append(line)
            continue
        if line.startswith("+") and skipping:
            removed.append(line)
            continue
        skipping = False
        if ANALYSIS_RE.match(line) or DROP_RE.match(line):
            removed.append(line)
            skipping = True
            continue
        out.append(line)
    return "\n".join(out) + "\n", [r for r in removed if r.strip() and r.strip().lower() != ".end"]


def design_variables(body: str) -> list[str]:
    """The names used in {expressions} that the netlist does not define - "copy from cellview"."""
    defined = set()
    for line in body.splitlines():
        m = PARAM_RE.match(line)
        if m:
            defined |= {a.split("=")[0].strip().lower() for a in re.split(r"\s+(?=[A-Za-z_]\w*\s*=)", m.group(1))}
    used = []
    for expr in BRACE_RE.findall(body):
        for name in IDENT_RE.findall(re.sub(r"\d+\.?\d*(e[+-]?\d+)?", " ", expr, flags=re.I)):
            low = name.lower()
            if low not in defined and low not in NOT_VARS and name not in used and not low.startswith("v("):
                used.append(name)
    return used


def spiceinit(threads: int | None) -> str:
    """The user's ~/.spiceinit (BSIM-CMG OSDI, model path), with ngspice's OpenMP threads set:
    several ngspice processes with 8 spinning threads each on 8 cores slow down a thousandfold."""
    home = Path.home() / ".spiceinit"
    text = home.read_text() if home.is_file() else ""
    if not text.strip():
        osdi, models = os.environ.get("BSIMCMG_OSDI", ""), os.environ.get("ASAP7_SPICE_DIR", "")
        text = (f"osdi {osdi}\n" if osdi else "") + (f"set sourcepath = ( . {models} )\n" if models else "")
    if threads:
        text = re.sub(r"(?m)^\s*set\s+num_threads\s*=.*$", "", text) + f"set num_threads = {threads}\n"
    return text


def deck(setup: Setup, point: Point, body: str, vecs: list) -> str:
    test = setup.test(point.test)
    lines = [f"* OpenLayout OLSim: test {test.name}, point {point.index} ({point.label})",
             f".lib asap7.lib {point.section}", f".temp {point.temp}"]
    params = [f"{k}={v}" for k, v in point.variables.items() if v != ""]
    if params:
        lines.append(".param " + " ".join(params))
    if test.options.strip():
        lines.append(test.options.strip())
    lines.append("* ---- testbench ----")
    lines.append(body.rstrip())
    for vf in vecs:
        lines += vf.sources(point.variables)
    if test.saves.strip() and test.saves.strip().lower() != "all":
        lines.append(".save " + test.saves.strip())
    for a in test.analyses:
        if a.enabled:
            lines.append(a.spice())
    lines.append(".end")
    return "\n".join(lines) + "\n"


# ---- results ------------------------------------------------------------------------------------
def output_value(setup: Setup, out, plots, variables):
    """(value, error): float / complex / Waveform, or the message why not."""
    test = setup.test(out.test)
    analysis = out.analysis or next((a.type for a in test.analyses if a.enabled), None)
    try:
        return evaluate(out.expr, Context(plots, variables, analysis)), None
    except CalcError as e:
        return None, str(e)


def _jsonable(v):
    if isinstance(v, Waveform):
        return {"wave": v.name}
    if isinstance(v, complex):
        return {"re": v.real, "im": v.imag}
    return v


class History:
    """A finished (or running) run: its points, output values and files."""

    def __init__(self, path: Path, data: dict):
        self.path = Path(path)
        self.data = data
        self._plots = {}

    @staticmethod
    def load(path) -> "History":
        path = Path(path)
        return History(path, json.loads((path / "history.json").read_text()))

    @property
    def name(self):
        return self.path.name

    @property
    def points(self):
        return self.data["points"]

    @property
    def outputs(self):
        return self.data["outputs"]

    def setup(self) -> Setup:
        s = Setup.load(self.path / "setup.json")
        s.path = json.loads((self.path / "setup.json").read_text()).get("source") or s.path
        return s

    def raw(self, index) -> Path:
        return self.path / "points" / str(index) / "sim.raw"

    def plots(self, index):
        if index not in self._plots:
            f = self.raw(index)
            self._plots[index] = rawfile.read(f) if f.is_file() else []
        return self._plots[index]

    def result(self, index) -> dict:
        return self.data["results"].get(str(index), {})

    def wave(self, index, output_name):
        """The waveform of an output at a point (re-evaluated from the raw file)."""
        setup = self.setup()
        out = next(o for o in setup.outputs if o.name == output_name)
        p = self.points[index]
        val, err = output_value(setup, out, self.plots(index), p["variables"])
        if err:
            raise CalcError(err)
        return val


class Run:
    """Runs a setup in the background; progress(done, total, message) is called from worker
    threads."""

    def __init__(self, setup: Setup, results_dir, workarea_root=None, name=None):
        self.setup = setup
        self.results_dir = Path(results_dir)
        self.workarea_root = Path(workarea_root) if workarea_root else None
        self.name = name or self._next_name()
        self.path = self.results_dir / self.name
        self._procs = set()
        self._lock = threading.Lock()
        self._cancel = False
        self._thread = None
        self.error = None
        self.history: History | None = None

    def _next_name(self):
        n = 0
        if self.results_dir.is_dir():
            for d in self.results_dir.iterdir():
                m = re.match(r"Interactive\.(\d+)$", d.name)
                if m:
                    n = max(n, int(m.group(1)))
        return f"Interactive.{n + 1}"

    # ---- control --------------------------------------------------------------------------------
    def start(self, progress=None):
        self._thread = threading.Thread(target=self._safe_run, args=(progress,), daemon=True)
        self._thread.start()
        return self

    def wait(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)
        if self.error:
            raise OLSimError(self.error)
        return self.history

    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def cancel(self):
        self._cancel = True
        with self._lock:
            for p in list(self._procs):
                try:
                    os.killpg(p.pid, _signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass

    def run(self, progress=None):
        self._safe_run(progress)
        if self.error:
            raise OLSimError(self.error)
        return self.history

    def _safe_run(self, progress):
        try:
            self._run(progress or (lambda *a: None))
        except Exception as e:                          # reported to the caller, not lost in a thread
            self.error = f"{type(e).__name__}: {e}"

    # ---- the run --------------------------------------------------------------------------------
    def _resolve(self, rel):
        p = Path(os.path.expandvars(os.path.expanduser(rel)))
        return p if p.is_absolute() else self.setup.directory / p

    def _workarea(self):
        from ..workarea import Workarea
        return Workarea(self.workarea_root) if self.workarea_root else Workarea.find(self.setup.directory)

    def config(self, test) -> Config | None:
        """The config view a test's design names ({"lib", "cell", "view": "config"}), else None."""
        d = test.design
        if d.get("view") != "config" or "lib" not in d:
            return None
        wa = self._workarea()
        lib = wa.library(d["lib"]) if wa else None
        cell = lib.cell(d["cell"]) if lib else None
        view = cell.view("config") if cell else None
        if view is None:
            raise OLSimError(f"test {test.name}: {d['lib']}/{d['cell']} has no config view")
        cfg = Config.load(view.path)
        cfg.top = cfg.top or {"lib": d["lib"], "cell": d["cell"]}
        return cfg

    def _netlist(self, test):
        """(netlist, removed lines, notes) of a test's design: the testbench netlisted by xschem,
        cleaned, with the views of its config (and its Post-layout cells) bound."""
        d = test.design
        out = self.path / "netlist"
        cfg = self.config(test)
        if "netlist" in d:
            text = self._resolve(d["netlist"]).read_text()
        else:
            if "lib" in d:
                wa = self._workarea()
                if wa is None:
                    raise OLSimError(f"test {test.name}: {d['lib']}/{d['cell']} needs a workarea")
                top = cfg.top if cfg else d
                lib = wa.library(top.get("lib", ""))
                cell = lib.cell(top.get("cell", "")) if lib else None
                view = cell.view("schematic") if cell else None
                if view is None:
                    raise OLSimError(f"test {test.name}: no schematic {top.get('lib')}/{top.get('cell')}")
                sch, root = view.path, wa.root
            else:
                sch, root = self._resolve(d["schematic"]), self.workarea_root
            text = netlist_schematic(sch, out / test.name, root)
        body, removed = clean_netlist(text)
        body, notes = self.bind(test, body, cfg)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{test.name}.spice").write_text(body)
        return body, removed, notes

    def bind(self, test, body, cfg=None):
        """(netlist, notes): the config's views - and the test's Post-layout cells, extracted on
        top of it - bound into a netlist."""
        cfg = Config(**{**cfg.__dict__, "cells": dict(cfg.cells)}) if cfg else Config()
        files = {}
        for entry in test.extracted:
            if entry.endswith((".spice", ".sp")):
                name = Path(entry).name.split(".")[0]
                files[name.lower()] = entry
                cfg.cells[name] = "extracted"
            else:
                cfg.cells[entry] = "extracted"
        if not (cfg.path or cfg.cells or cfg.instances or cfg.default != "schematic"):
            return body, []

        def pex_for(cell):
            key = files.get(cell.lower()) or cfg.cell_binding(cell)[0] or cell
            p, _, note = self._pex_netlist(key if "/" in key or key.endswith((".spice", ".sp")) else cell)
            return p, note

        try:
            body, bnotes, resolved = bind(body, cfg, pex_for)
        except ConfigError as e:
            raise OLSimError(f"test {test.name}: {e}") from None
        head = [f"* OpenLayout hierarchy" + (f" - config {test.design_label()}" if cfg.path else "")
                + f": {counts(resolved)}"]
        head += [f"*   {p} ({c}): {v}" for p, (c, v, _) in list(resolved.items())[:200] if v]
        notes = [f"{test.name}: " + (f"config {test.design_label()}: " if cfg.path else "") + counts(resolved)]
        return "\n".join(head) + "\n" + body, notes + [f"{test.name}: {n}" for n in bnotes]

    def _pex_netlist(self, entry):
        """(netlist, cell name, warning) of a cell's latest PEX run, or of a .spice file given."""
        if entry.endswith((".spice", ".sp")):
            p = self._resolve(entry)
            if not p.is_file():
                raise OLSimError(f"no PEX netlist {p}")
            return p, p.name.split(".")[0], ""
        wa = self._workarea()
        if wa is None:
            raise OLSimError(f"extracted {entry}: needs a workarea (or give the .pex.spice file)")
        try:
            p, note = find_pex(wa, entry)
        except ConfigError as e:
            raise OLSimError(str(e)) from None
        return p, entry.split("/")[-1], note

    def _run(self, progress):
        setup = self.setup
        self.path.mkdir(parents=True, exist_ok=True)
        snapshot = setup.to_dict()
        snapshot["source"] = setup.path           # relative files (netlists, vectors) are relative to it
        (self.path / "setup.json").write_text(json.dumps(snapshot, indent=1) + "\n")
        points = setup.points()
        if not points:
            raise OLSimError("nothing to run: no enabled test")
        bodies, vecs, notes = {}, {}, []
        for test in {p.test for p in points}:
            t = setup.test(test)
            bodies[test], removed, pex_notes = self._netlist(t)
            if removed:
                notes.append(f"{test}: ignored {len(removed)} line(s) of the testbench (OLSim sets analyses, "
                             f"corner and temperature): {removed[0].strip()[:60]}")
            notes += pex_notes
            vecs[test] = [vectors.parse(self._resolve(v)) for v in t.vectors]
        data = {"name": self.name, "started": time.time(), "points": [p.as_dict() for p in points],
                "outputs": [{"test": o.test, "name": o.name, "expr": o.expr, "spec": o.spec, "plot": o.plot}
                            for o in setup.outputs],
                "results": {}, "notes": notes, "status": "running"}
        self._write(data)
        total, done = len(points), 0
        progress(0, total, f"{self.name}: {total} point(s)")
        for n in notes:
            progress(0, total, n)

        def one(p):
            if self._cancel:
                return p, {"_status": "cancelled"}
            return p, self._point(p, bodies[p.test], vecs[p.test])

        with ThreadPoolExecutor(max_workers=max(1, setup.jobs)) as pool:
            for fut in as_completed([pool.submit(one, p) for p in points]):
                p, res = fut.result()
                done += 1
                data["results"][str(p.index)] = res
                status = res.get("_status", "")
                progress(done, total, f"point {p.index} {p.test} {p.label}: {status}")
                self._write(data)
        data["status"] = "cancelled" if self._cancel else "done"
        data["finished"] = time.time()
        self._write(data)
        self.history = History(self.path, data)

    def _write(self, data):
        tmp = self.path / "history.json.tmp"
        tmp.write_text(json.dumps(data, indent=1, default=str))
        tmp.replace(self.path / "history.json")

    def _point(self, p: Point, body: str, vecs: list) -> dict:
        d = self.path / "points" / str(p.index)
        d.mkdir(parents=True, exist_ok=True)
        try:
            text = deck(self.setup, p, body, vecs)
        except vectors.VectorError as e:
            return {"_status": f"error: {e}"}
        (d / "deck.sp").write_text(text)
        (d / ".spiceinit").write_text(spiceinit(1 if self.setup.jobs > 1 else None))
        t0 = time.time()
        with open(d / "ngspice.log", "w") as log:
            proc = subprocess.Popen(["ngspice", "-b", "-r", "sim.raw", "deck.sp"], cwd=d, stdout=log,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
            with self._lock:
                self._procs.add(proc)
            try:
                rc = proc.wait(timeout=24 * 3600)
            finally:
                with self._lock:
                    self._procs.discard(proc)
        res = {"_seconds": round(time.time() - t0, 2)}
        if self._cancel:
            res["_status"] = "cancelled"
            return res
        log_text = (d / "ngspice.log").read_text(errors="replace")
        if rc != 0 or not (d / "sim.raw").is_file():
            err = next((l for l in log_text.splitlines() if "error" in l.lower()), f"ngspice exit {rc}")
            res["_status"] = f"sim error: {err.strip()[:200]}"
            return res
        try:
            plots = rawfile.read(d / "sim.raw")
        except Exception as e:
            res["_status"] = f"raw file: {e}"
            return res
        res["_status"] = "done"
        for out in (o for o in self.setup.outputs if o.test == p.test):
            val, err = output_value(self.setup, out, plots, p.variables)
            entry = {"value": _jsonable(val), "error": err}
            if not err and not isinstance(val, Waveform):
                try:
                    entry["pass"] = check_spec(val, out.spec)
                except CalcError as e:
                    entry["error"] = str(e)
            res[out.name] = entry
        if vecs:
            tran = next((pl for pl in plots if pl.kind == "tran"), None)
            if tran is None:
                res["vector errors"] = {"value": None, "error": "vector check needs a tran analysis"}
            else:
                ctx = Context(plots, p.variables, "tran")
                errors = []
                for vf in vecs:
                    errors += vf.check(lambda n: ctx.signal("v", n, "tran"), p.variables, float(tran.x[-1]))
                (d / "vector_errors.json").write_text(json.dumps(errors, indent=1))
                res["vector errors"] = {"value": len(errors), "error": None, "pass": not errors,
                                        "first": [f"{fmt(e['time'])}s {e['signal']}: expected {e['expected']} "
                                                  f"got {e['got']}" for e in errors[:5]]}
        (d / "results.json").write_text(json.dumps(res, indent=1, default=str))
        return res


def histories(results_dir) -> list[Path]:
    d = Path(results_dir)
    if not d.is_dir():
        return []
    hs = [h for h in d.iterdir() if (h / "history.json").is_file()]
    return sorted(hs, key=lambda h: h.stat().st_mtime)


def delete_history(path) -> None:
    shutil.rmtree(path, ignore_errors=True)
