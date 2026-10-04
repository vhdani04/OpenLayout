"""Schematic-driven layout (Layout XL style "Generate All From Source" / "Update Components and Nets").

generate(schematic) netlists the xschem schematic, then creates or updates <cell>.gds:
  - FinFETs become OpenLayout_ASAP7 nmos/pmos PCells (vt, nfin, nf from the schematic; m copies),
  - standard cells become instances of the ASAP7 std-cell libraries,
  - other subcircuits become copies of their own layout view (if they have one),
  - schematic ports become M1 pins: a pin-purpose square of the layer's minimum width with the
    label, no drawing shape under it (draw the wire the pin sits on),
and writes the schematic link <cell>.ol.json used by the connectivity check. Existing instances are
matched by name (GDS property), so placement and routing survive updates; parts removed from the
schematic are reported, never deleted.

The cell's boundary has its lower left corner at (0, 0): a transistor-level cell gets the
standard-cell frame (stdcell.draw_frame, sized for its transistors chained per row) unless it has
one, and its transistors come in standard-cell row mode; a cell of only sub-cells gets a plain
boundary. New parts are parked below the cell (y < 0) in rows - pMOS, nMOS, then other cells - left
to right, so they never overlap the cell or each other; dragged into the frame, a row transistor
snaps onto the row (see chain.update).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pya

from .asap7 import DBU, LAYERS, METALS, MIN_WIDTH, PIN
from .connectivity import PREFIX, PROP, conn_file, instance_name
from .pcells import LIBRARY, ROW_MAX_FINS, register_library
from .stdcell import draw_frame, has_frame

STDCELL_RE = re.compile(r"_ASAP7_75t_(R|L|SL|SRAM)$")
GATE_PITCH, ROW_GAP = 0.054, 0.108


def _workarea():
    flow_python = Path(os.environ.get("OPENLAYOUT_HOME", Path.home() / "openlayout/flow")) / "python"
    if str(flow_python) not in sys.path:
        sys.path.insert(0, str(flow_python))
    from openlayout.workarea import Workarea
    return Workarea


# ---- netlist ---------------------------------------------------------------------------------

def netlist_schematic(sch: Path, wa_root: Path) -> str:
    out = Path(tempfile.mkdtemp(prefix="ol_gen_"))
    cmd = ["xschem", "-x", "-q", "-r", "-n", "-s", "--tcl", "set top_is_subckt 1", "-o", str(out), str(sch)]
    res = subprocess.run(cmd, cwd=wa_root, capture_output=True, text=True, timeout=120)
    net = out / f"{sch.stem}.spice"
    if not net.is_file():
        raise RuntimeError(f"xschem could not netlist {sch.name}: {(res.stdout + res.stderr)[-400:]}")
    return net.read_text()


GROUND_NAMES = {"0", "gnd", "gnd!", "vss!"}   # SPICE / analogLib ground -> the ASAP7 ground net
SUPPLIES = ("VDD", "VSS")


def ground_to_vss(net: str) -> str:
    """The ground net is VSS (ASAP7 convention); xschem's stock ground (0) and GND map to it."""
    return "VSS" if net.lower() in GROUND_NAMES else net


def parse_netlist(text: str, top: str) -> dict:
    lines = []
    for raw in text.splitlines():
        if raw.startswith("+") and lines:
            lines[-1] += " " + raw[1:]
        else:
            lines.append(raw)
    result = {"ports": [], "dirs": {}, "devices": [], "cells": [], "subckts": {}}
    current = None
    for line in lines:
        tok = line.split()
        if not tok:
            continue
        head = tok[0].lower()
        if head == ".subckt":
            current = tok[1]
            result["subckts"][current] = tok[2:]
            if current == top:
                result["ports"] = tok[2:]
            continue
        if head == ".ends":
            current = None
            continue
        if current != top:
            continue
        if head == "*.pininfo":
            for item in tok[1:]:
                name, _, d = item.rpartition(":")
                result["dirs"][name] = d
        elif head.startswith("n") and len(tok) >= 6:
            params = dict(t.split("=", 1) for t in tok[6:] if "=" in t)
            result["devices"].append({"name": tok[0][1:], "nets": [ground_to_vss(n) for n in tok[1:5]],
                                      "model": tok[5], "params": params})
        elif head.startswith("x"):
            plain = [i for i, t in enumerate(tok) if "=" not in t]
            cell_i = plain[-1]
            result["cells"].append({"name": tok[0][1:], "nets": [ground_to_vss(n) for n in tok[1:cell_i]],
                                    "cell": tok[cell_i]})
    # the supplies used inside the cell (global labels, like the ASAP7 cells' VDD / VSS) are pins of
    # the layout too - the rails - unless they are ports already
    used = {n for d in result["devices"] for n in d["nets"]} | {n for c in result["cells"] for n in c["nets"]}
    result["supplies"] = [s for s in SUPPLIES if s in used and s not in result["ports"]]
    return result


_cdl_ports = {}


def stdcell_ports(cell: str) -> list:
    flavor = STDCELL_RE.search(cell).group(1)
    if flavor not in _cdl_ports:
        cdl = Path(os.environ["ASAP7_STDCELLS"]) / "CDL" / "LVS" / f"asap7sc7p5t_28_{flavor}.cdl"
        ports = {}
        for line in cdl.read_text().splitlines():
            t = line.split()
            if t and t[0].upper() == ".SUBCKT":
                ports[t[1]] = t[2:]
        _cdl_ports[flavor] = ports
    return _cdl_ports[flavor][cell]


# ---- layout helpers ----------------------------------------------------------------------------

def _snap(v: float, grid: float) -> float:
    return round(v / grid) * grid


class Placer:
    """Parking rows below the cell (y < 0): pMOS, nMOS under it, then other cells - left to right
    from x = 0, new parts after the ones already parked in their row. Row-mode transistors are drawn
    in cell coordinates (pMOS 113..292 nm, nMOS -22..157 nm above their origin), so these origins
    keep every row clear of the cell and of the next row."""

    ROW_Y = {"pmos": -0.54, "nmos": -0.81, "cell": -1.35}

    def __init__(self, top: pya.Cell, has_mos: bool):
        self.base_y = 0.0
        self.row_y = dict(self.ROW_Y)
        if not has_mos:
            self.row_y["cell"] = -0.54
        self.x = {}
        for row, y in self.row_y.items():
            rights = [i.dbbox().right for i in top.each_inst() if abs(i.dcplx_trans.disp.y - y) < 1e-6]
            self.x[row] = _snap(max(rights) + ROW_GAP, GATE_PITCH) if rights else 0.0

    def place(self, row: str, width: float) -> pya.DTrans:
        x = self.x[row]
        self.x[row] = _snap(x + width + ROW_GAP, GATE_PITCH)
        return pya.DTrans(x, self.row_y[row])


def _cell_width(layout: pya.Layout, x: dict) -> float:
    """Width (um) of a standard cell of the netlist, 0 if unknown."""
    m = STDCELL_RE.search(x["cell"])
    if not m:
        return 0.0
    lib = pya.Library.library_by_name("asap7sc7p5t_28_" + m.group(1), "asap7")
    lc = lib.layout().cell(x["cell"]) if lib else None
    return lc.dbbox().width() if lc is not None else 0.0


def _frame_width(devices) -> int:
    """Gate pitches for the transistors chained per row (each device nf + 1 pitches, + 1)."""
    need = {"nmos": 1, "pmos": 1}
    for dev in devices:
        kind = dev["model"].partition("_")[0]
        if kind in need:
            p = dev["params"]
            need[kind] += int(float(p.get("m", 1))) * (int(float(p.get("nf", 1))) + 1)
    return max(3, *need.values())


def _ensure_boundary(top: pya.Cell, net: dict, cell_widths: float) -> bool:
    """Frame (transistor cells) or plain boundary (cells only) at the origin, unless the cell has
    one. Returns True if the cell has a standard-cell frame (transistors go in row mode)."""
    has_mos = any(d["model"].partition("_")[0] in ("nmos", "pmos") for d in net["devices"])
    if has_frame(top):
        return True
    layout = top.layout()
    bound = layout.find_layer(LAYERS["boundary"], 0)
    if bound is not None and not top.shapes(bound).is_empty():
        return False                              # the user's own boundary: leave it
    if has_mos:
        draw_frame(top, _frame_width(net["devices"]))
        return True
    if cell_widths > 0:
        w = max(_snap(cell_widths, GATE_PITCH), GATE_PITCH)
        top.shapes(layout.layer(LAYERS["boundary"], 0)).insert(pya.DBox(0, 0, w, 0.27))
    return False


def _layout_for(sch: Path, cell_name: str, gds: Path, layout: pya.Layout | None):
    if layout is not None:
        return layout, False
    layout = pya.Layout()
    layout.technology_name = "asap7"  # before reading: lets PCell/library instances resolve
    if gds.is_file():
        layout.read(str(gds))
    else:
        layout.dbu = DBU
    return layout, True


def _user_cell(wa, cell_name: str, layout: pya.Layout):
    """Copy a design cell's own layout view into `layout` (once). Returns the cell or None."""
    for lib in wa.libraries():
        c = lib.cell(cell_name)
        v = c.view("layout") if c else None
        if v is None or v.gds_cell:
            continue
        existing = layout.cell(cell_name)
        if existing is not None:
            return existing
        src = pya.Layout()
        src.read(str(v.path))
        src_cell = src.cell(cell_name) or src.top_cell()
        new = layout.create_cell(cell_name)
        new.copy_tree(src_cell)
        return new
    return None


def _add_pin(top: pya.Cell, name: str, at: pya.DPoint, metal: str = "m1"):
    """A pin: a square of the metal's minimum width on its pin purpose, centred on `at`, with the
    label - only the pin, no drawing shape (pins are metal only)."""
    if metal not in METALS:
        raise ValueError(f"pins are on metal layers, not {metal}")
    layout = top.layout()
    h = MIN_WIDTH[metal] / 2000
    li = layout.layer(LAYERS[metal], PIN)
    top.shapes(li).insert(pya.DBox(at.x - h, at.y - h, at.x + h, at.y + h))
    top.shapes(li).insert(pya.DText(name, pya.DTrans(at.x, at.y)))


def _top_pin_names(top: pya.Cell) -> set:
    li = top.layout().find_layer(LAYERS["m1"], PIN)
    if li is None:
        return set()
    return {s.text_string for s in top.shapes(li).each(pya.Shapes.STexts)}


# ---- generate / update ---------------------------------------------------------------------------

def generate(schematic, layout: pya.Layout | None = None) -> dict:
    """Create or update the layout view of the schematic's cell. If `layout` is given (a layout
    open in the GUI) it is edited in place and not saved; otherwise the .gds file is written."""
    register_library()
    sch = Path(schematic).resolve()
    Workarea = _workarea()
    wa = Workarea.find(sch.parent)
    if wa is None:
        raise RuntimeError(f"{sch} is not inside an OpenLayout workarea")
    cell = wa.cell_for_path(sch)
    if cell is None or cell.library.readonly:
        raise RuntimeError(f"{sch} is not a cell of a writable design library")
    gds = cell.path / f"{cell.name}.gds"
    net = parse_netlist(netlist_schematic(sch, wa.root), cell.name)

    layout, standalone = _layout_for(sch, cell.name, gds, layout)
    top = layout.cell(cell.name) or (layout.top_cell() if layout.cells() else None) or layout.create_cell(cell.name)
    existing = {instance_name(i): i for i in top.each_inst()}
    existing.pop(None, None)
    has_mos = any(d["model"].partition("_")[0] in ("nmos", "pmos") for d in net["devices"])
    placer = Placer(top, has_mos)
    row = _ensure_boundary(top, net, sum(_cell_width(layout, x) for x in net["cells"]))
    report = {"added": [], "updated": [], "unchanged": [], "extra": [], "skipped": [], "pins_added": [],
              "warnings": []}
    conn = {"version": 1, "schematic": sch.name, "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ports": net["ports"], "pins": {p: net["dirs"].get(p, "B") for p in net["ports"] + net["supplies"]},
            "instances": {}}
    seen = set()

    for dev in sorted(net["devices"], key=lambda d: _natural(d["name"])):
        kind, _, vt = dev["model"].partition("_")
        if kind not in ("nmos", "pmos"):
            report["skipped"].append(f"{dev['name']} ({dev['model']})")
            continue
        params = {"vt": vt or "rvt", "nfin": int(float(dev["params"].get("nfin", 1))),
                  "nf": int(float(dev["params"].get("nf", 1)))}
        if row:
            if params["nfin"] > ROW_MAX_FINS:
                report["warnings"].append(f"{dev['name']}: nfin {params['nfin']} > {ROW_MAX_FINS} fits no "
                                          f"7.5-track row - drawn with {ROW_MAX_FINS} (use more fingers)")
            params["row"] = True
        m = int(float(dev["params"].get("m", 1)))
        terms = dict(zip(("d", "g", "s", "b"), dev["nets"]))
        for k in range(m):
            name = dev["name"] if m == 1 else f"{dev['name']}.{k + 1}"
            seen.add(name)
            conn["instances"][name] = {"kind": "mos", "type": kind, "model": dev["model"], "params": params,
                                       "terminals": terms}
            inst = existing.get(name)
            if inst is not None:
                cur = inst.pcell_parameters_by_name()
                if any(str(cur.get(k2)) != str(v) for k2, v in params.items()):
                    inst.change_pcell_parameters(params)
                    if row and not cur.get("row"):    # now a row device: park it below the cell
                        inst.transform(pya.DTrans(0, placer.row_y[kind] - inst.dcplx_trans.disp.y))
                    report["updated"].append(name)
                else:
                    report["unchanged"].append(name)
                continue
            pc = layout.create_cell(kind, LIBRARY, params)
            t = placer.place(kind, pc.dbbox().width())
            new = top.insert(pya.DCellInstArray(pc.cell_index(), t))
            new.set_property(PROP, PREFIX + name)
            report["added"].append(name)

    for x in sorted(net["cells"], key=lambda c: _natural(c["name"])):
        name, cname = x["name"], x["cell"]
        seen.add(name)
        if STDCELL_RE.search(cname):
            lib_name = "asap7sc7p5t_28_" + STDCELL_RE.search(cname).group(1)
            lib = pya.Library.library_by_name(lib_name, "asap7")
            lc = lib.layout().cell(cname) if lib else None
            if lc is None:
                report["skipped"].append(f"{name} ({cname}: not in {lib_name})")
                continue
            ports = stdcell_ports(cname)
            target = layout.cell(layout.add_lib_cell(lib, lc.cell_index()))
            spec = {"kind": "cell", "lib": lib_name, "cell": cname}
        else:
            target = _user_cell(wa, cname, layout)
            ports = net["subckts"].get(cname, [])
            if target is None:
                report["skipped"].append(f"{name} ({cname}: no layout view)")
                continue
            spec = {"kind": "cell", "lib": "", "cell": cname}
        spec["terminals"] = dict(zip(ports, x["nets"]))
        conn["instances"][name] = spec
        inst = existing.get(name)
        if inst is not None:
            if inst.cell_index != target.cell_index():
                inst.cell_index = target.cell_index()
                report["updated"].append(name)
            else:
                report["unchanged"].append(name)
            continue
        t = placer.place("cell", target.dbbox().width())
        new = top.insert(pya.DCellInstArray(target.cell_index(), t))
        new.set_property(PROP, PREFIX + name)
        report["added"].append(name)

    have_pins = _top_pin_names(top)      # e.g. the frame's VDD / VSS rails
    y = placer.base_y
    for p in net["ports"] + net["supplies"]:
        if p not in have_pins:
            _add_pin(top, p, pya.DPoint(-0.324, y))
            report["pins_added"].append(p)
        y += 0.108

    report["extra"] = sorted(set(existing) - seen)
    conn_file(gds).write_text(json.dumps(conn, indent=1))
    if standalone:
        layout.write(str(gds))
    report["gds"] = str(gds)
    report["cell"] = cell.name
    return report


def _natural(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
