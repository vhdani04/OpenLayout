"""The config view (<cell>.config): which view each cell and each instance of a design is
simulated with - a hierarchy editor. An OLSim test whose design is a config simulates
the netlist it describes.

    {"top": {"lib": "demo", "cell": "tb_inv"},           # the design: this cell's schematic
     "default": "schematic",                              # or "extracted": wherever a PEX netlist exists
     "cells": {"demo/inv": "extracted"},                  # every instance of a cell ...
     "instances": {"X2": "schematic", "X4/x1": "extracted"}}   # ... unless its instance path says otherwise

Views:
- schematic: the cell's schematic subcircuit; its own instances are bound in turn.
- extracted: the cell's latest PEX netlist, a leaf. Its pins are matched to the schematic's by
  name; layout pins that are global nets of the design (VDD, VSS) connect to those nets.

    bind(netlist, config, pex_for) -> (netlist, notes, resolved)
"""
from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

VIEWS = ("schematic", "extracted")
SUBCKT_RE = re.compile(r"^\s*\.subckt\s+(\S+)(.*)$", re.I)
ENDS_RE = re.compile(r"^\s*\.ends\b", re.I)
GLOBAL_RE = re.compile(r"^\s*\.global\s+(.*)$", re.I)


class ConfigError(Exception):
    pass


@dataclass
class Config:
    top: dict = field(default_factory=dict)          # {"lib", "cell"}: the design (its schematic)
    default: str = "schematic"
    cells: dict = field(default_factory=dict)        # "lib/cell" (or "cell") -> view
    instances: dict = field(default_factory=dict)    # instance path "X1/x2" -> view
    path: str = ""

    @staticmethod
    def load(path) -> "Config":
        d = json.loads(Path(path).read_text())
        return Config(dict(d.get("top", {})), d.get("default", "schematic"), dict(d.get("cells", {})),
                      dict(d.get("instances", {})), str(path))

    def to_dict(self) -> dict:
        return {"top": self.top, "default": self.default, "cells": self.cells, "instances": self.instances}

    def save(self, path=None) -> None:
        path = Path(path or self.path)
        self.path = str(path)
        path.write_text(json.dumps(self.to_dict(), indent=1) + "\n", newline="\n")

    @property
    def top_label(self) -> str:
        return f"{self.top.get('lib', '?')}/{self.top.get('cell', '?')}"

    def cell_binding(self, cell: str):
        """(key, view) of a cell's binding, or (None, None)."""
        for k, v in self.cells.items():
            if k.split("/")[-1].lower() == cell.lower():
                return k, v
        return None, None

    def instance_binding(self, path: str):
        return next((v for k, v in self.instances.items() if k.lower() == path.lower()), None)

    def bound(self, path: str, cell: str):
        """(view, how) of an instance: its own binding, else its cell's, else the default."""
        v = self.instance_binding(path)
        if v in VIEWS:
            return v, "instance"
        v = self.cell_binding(cell)[1]
        if v in VIEWS:
            return v, "cell"
        return (self.default if self.default in VIEWS else "schematic"), "default"

    def summary(self) -> str:
        """The bindings in a few words."""
        parts = [f"{k.split('/')[-1]} {v}" for k, v in self.cells.items()]
        parts += [f"{k} {v}" for k, v in self.instances.items()]
        lead = "extracted where available" if self.default == "extracted" else "schematic"
        return lead + (f"; {', '.join(parts)}" if parts else "")


# ---- netlists -----------------------------------------------------------------------------------
def _ports(rest: str):
    """('A Z VSS', 'params: w=1') -> (['A', 'Z', 'VSS'], ' params: w=1')"""
    toks = rest.split()
    for i, t in enumerate(toks):
        if "=" in t or t.lower() == "params:":
            return toks[:i], " " + " ".join(toks[i:])
    return toks, ""


@dataclass
class Stmt:
    """A netlist statement: its line and "+" continuations. X instances know their instance name
    and the subcircuit they instantiate."""
    lines: list
    inst: str = ""
    cell: str = ""

    def __post_init__(self):
        toks = self.joined.split()
        if len(toks) >= 2 and toks[0][:1] in "xX":
            names = []
            for t in toks[1:]:
                if "=" in t or t.lower() == "params:":
                    break
                names.append(t)
            if names:
                self.inst, self.cell = toks[0], names[-1]
                self._at = len(names)

    @property
    def joined(self) -> str:
        return " ".join([self.lines[0]] + [ln.lstrip()[1:] for ln in self.lines[1:]])

    def render(self, cell: str | None = None) -> str:
        if not self.cell or cell is None or cell == self.cell:
            return "\n".join(self.lines)
        toks = self.joined.split()
        toks[self._at] = cell
        return " ".join(toks)


@dataclass
class Subckt:
    name: str
    ports: list
    params: str
    body: list                                       # [Stmt]

    @property
    def instances(self):
        return [s for s in self.body if s.cell]

    def render(self, name: str | None = None, cells: list | None = None, ports: list | None = None) -> str:
        """The subcircuit, renamed, its instances bound to `cells` (in order), its pins `ports`."""
        it = iter(cells or [])
        lines = [f".subckt {name or self.name} {' '.join(self.ports if ports is None else ports)}{self.params}"]
        lines += [s.render(next(it) if (cells is not None and s.cell) else None) for s in self.body]
        return "\n".join(lines + [".ends"])


@dataclass
class Node:
    path: str
    inst: str
    cell: str
    depth: int
    defined: bool                                    # the netlist has the cell's subcircuit
    children: list


class Netlist:
    """A flat-text SPICE netlist as top-level statements and subcircuits, in order."""

    def __init__(self, text: str):
        stmts = []
        for line in text.splitlines():
            if line.lstrip().startswith("+") and stmts:
                stmts[-1].lines.append(line)
            else:
                stmts.append([line])
        self.items, self.subckts, self.globals = [], {}, {"0"}
        cur = None
        for st in (Stmt(s) for s in stmts):
            j = st.joined
            m = SUBCKT_RE.match(j)
            if cur is None and m:
                ports, params = _ports(m.group(2))
                cur = Subckt(m.group(1), ports, params, [])
            elif cur is not None and ENDS_RE.match(j):
                self.items.append(cur)
                self.subckts[cur.name.lower()] = cur
                cur = None
            elif cur is not None:
                cur.body.append(st)
            else:
                g = GLOBAL_RE.match(j)
                if g:
                    self.globals |= {x.lower() for x in g.group(1).split()}
                self.items.append(st)

    @property
    def top(self):
        return [i for i in self.items if isinstance(i, Stmt)]

    def tree(self, stmts=None, prefix="", depth=0, stack=()) -> list[Node]:
        """The instance hierarchy."""
        nodes = []
        for st in (self.top if stmts is None else stmts):
            if not st.cell:
                continue
            sub = self.subckts.get(st.cell.lower())
            n = Node(prefix + st.inst, st.inst, st.cell, depth, sub is not None, [])
            if sub is not None and st.cell.lower() not in stack:
                n.children = self.tree(sub.body, n.path + "/", depth + 1, stack + (st.cell.lower(),))
            nodes.append(n)
        return nodes


def extracted_block(pex_text: str, cell: str, name: str, ports, globals_, source: str):
    """(text, notes): the cell's PEX subcircuit as `name`, its pins in the order `ports` (the
    schematic's; None keeps the PEX's own). Layout pins that the schematic lacks must be global
    nets: inside the subcircuit they then connect to those."""
    pex = Netlist(pex_text)
    sub = pex.subckts.get(cell.lower())
    if sub is None:
        raise ConfigError(f"{source} has no subcircuit {cell}")
    notes = []
    header = sub.ports
    if ports is not None:
        have = {p.lower(): p for p in sub.ports}
        wanted = {p.lower() for p in ports}
        extra = [p for p in sub.ports if p.lower() not in wanted]
        bad = [p for p in extra if p.lower() not in globals_]
        if bad:
            raise ConfigError(f"{cell}: the layout has pin(s) {' '.join(bad)} that its schematic does not "
                              f"(schematic pins: {' '.join(ports)}) - fix the pin labels, or make those nets global")
        missing = [p for p in ports if p.lower() not in have]
        if extra:
            notes.append(f"layout pin(s) {' '.join(extra)} connect to the global net(s)")
        if missing:
            notes.append(f"pin(s) {' '.join(missing)} are not in the layout (left open)")
        header = [have.get(p.lower(), p) for p in ports]
    return sub.render(name, ports=header), notes


def resolve(net: Netlist, cfg: Config, pex, strict: bool = True) -> dict:
    """{instance path: (cell, view, how)} - view None inside an extracted instance, "error" (strict
    False) where a binding asks for a PEX netlist that does not exist. pex(cell) -> (path, note) or
    an exception."""
    resolved = {}

    def walk(nodes, inside=None):
        for n in nodes:
            if inside:
                resolved[n.path] = (n.cell, None, f"inside {inside}")
                walk(n.children, inside)
                continue
            view, how = cfg.bound(n.path, n.cell)
            if view == "extracted":
                got = pex(n.cell)
                if isinstance(got, Exception):
                    if how == "default":
                        view, how = "schematic", "default (no PEX netlist)"
                    elif strict:
                        raise ConfigError(f"{n.path} ({n.cell}): {got}")
                    else:
                        view, how = "error", str(got)
            resolved[n.path] = (n.cell, view, how)
            walk(n.children, n.path if view == "extracted" else None)

    walk(net.tree())
    return resolved


def counts(resolved: dict) -> str:
    ext = [p for p, (_, v, _) in resolved.items() if v == "extracted"]
    sch = [p for p, (_, v, _) in resolved.items() if v == "schematic"]
    listed = ", ".join(ext[:6]) + (" ..." if len(ext) > 6 else "")
    return f"{len(ext)} instance(s) extracted{f' ({listed})' if ext else ''}, {len(sch)} schematic"


def bind(body: str, cfg: Config, pex_for):
    """(netlist, notes, resolved): the design netlist with the config's bindings applied. A cell
    extracted everywhere has its subcircuit replaced; one extracted only at some instances gets a
    <cell>_pex subcircuit, and the cells above those instances get bound copies (<cell>_cfgN).
    pex_for(cell) -> (path, note) of the cell's PEX netlist, raising when there is none."""
    net = Netlist(body)
    avail = {}

    def pex(cell):
        k = cell.lower()
        if k not in avail:
            try:
                avail[k] = pex_for(cell)
            except Exception as e:                   # no netlist: an error only where it is asked for
                avail[k] = e
        return avail[k]

    resolved = resolve(net, cfg, pex)
    uses = {}
    for cell, view, _ in resolved.values():
        if view:
            uses.setdefault(cell.lower(), set()).add(view)
    blocks, replaced, extra_defs, variants, notes = {}, {}, [], {}, []

    def name_for(st, path, stack):
        cell, view, _ = resolved[path]
        k = cell.lower()
        if view == "extracted":
            if k not in blocks:
                sub = net.subckts.get(k)
                in_place = sub is not None and uses[k] == {"extracted"}
                name = sub.name if in_place else f"{cell}_pex"
                p, note = avail[k]
                text, pin_notes = extracted_block(Path(p).read_text(), cell, name, sub.ports if sub else None,
                                                  net.globals, Path(p).name)
                text = f"* {cell}: extracted (PEX {Path(p).name})\n" + text
                (replaced.__setitem__(k, text) if in_place else extra_defs.append(text))
                blocks[k] = name
                at = [q for q, (c, v, _) in resolved.items() if c.lower() == k and v == "extracted"]
                notes.append(f"{cell} extracted ({Path(p).name}): {', '.join(at[:8])}{' ...' if len(at) > 8 else ''}"
                             + "".join(f" - {n}" for n in [note, *pin_notes] if n))
            return blocks[k]
        sub = net.subckts.get(k)
        if sub is None or k in stack:
            return st.cell
        names = [name_for(c, f"{path}/{c.inst}", stack | {k}) for c in sub.instances]
        if all(a == c.cell for a, c in zip(names, sub.instances)):
            return st.cell
        sig = (k, tuple(names))
        if sig not in variants:
            variants[sig] = f"{sub.name}_cfg{sum(1 for s in variants if s[0] == k) + 1}"
            extra_defs.append(f"* {sub.name} as bound at {path}\n" + sub.render(variants[sig], names))
        return variants[sig]

    top_names = {id(st): name_for(st, st.inst, frozenset()) for st in net.top if st.cell}
    out = []
    for item in net.items:
        if isinstance(item, Subckt):
            out.append(replaced.get(item.name.lower()) or item.render())
        else:
            out.append(item.render(top_names.get(id(item))))
    return "\n".join(out + extra_defs) + "\n", notes, resolved


# ---- PEX netlists of workarea cells -------------------------------------------------------------
def find_pex(workarea, entry: str):
    """(path, note) of a cell's latest PEX netlist ("lib/cell" or "cell"): the hub writes it to
    verify/<lib>/<cell>/, KLayout's Run PEX next to the layout."""
    lib_name, _, cell_name = entry.rpartition("/")
    libs = [workarea.library(lib_name)] if lib_name else workarea.libraries()
    cell = next((lb.cell(cell_name) for lb in libs if lb and lb.cell(cell_name)), None)
    if cell is None:
        raise ConfigError(f"{entry}: no such cell")
    layout = cell.view("layout")
    cands = [workarea.verify_dir(cell) / f"{cell_name}.pex.spice"]
    if layout and not layout.gds_cell:
        cands.append(layout.path.parent / f"{cell_name}.pex.spice")
    found = [c for c in cands if c.is_file()]
    if not found:
        raise ConfigError(f"{cell.key} has no PEX netlist yet - run PEX on its layout first")
    pex = max(found, key=lambda c: c.stat().st_mtime)
    stale = layout is not None and layout.path.is_file() and layout.path.stat().st_mtime > pex.stat().st_mtime
    return pex, "the layout changed since this extraction" if stale else ""


def describe_pex(path) -> str:
    when = datetime.datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%b %d %H:%M")
    return f"{path}  ({when})"
