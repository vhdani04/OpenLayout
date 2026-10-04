"""Schematic-driven connectivity: the link between a layout and its schematic, and the check that
finds open nets (with flight lines) and shorts - OpenLayout's take on Layout XL's incomplete nets.

The link lives next to the layout as <cell>.ol.json (written by generate.py):
  {"schematic": "inv.sch", "ports": [...], "pins": {"A": "I", ...},
   "instances": {"M1": {"kind": "mos", "type": "pmos", "terminals": {"d": "Y", "g": "A", ...}, ...},
                 "U1": {"kind": "cell", "lib": "...", "cell": "...", "terminals": {"A": "n1", ...}}}}
Layout instances carry GDS property 1 = "ol:<instance name>" so the link survives moves and edits.
"""
import json
from pathlib import Path

import pya

from .asap7 import CONNECTIONS, LABEL, LAYERS, METALS, PIN
from .pcells import mos_geometry_from

PROP = 1
PREFIX = "ol:"
SKIP_TERMINALS = {"b"}  # FinFET bulk: tied through wells/taps, not routed


def conn_file(layout_path) -> Path:
    p = Path(layout_path)
    return p.with_name(p.stem + ".ol.json")


def load_conn(layout_path):
    f = conn_file(layout_path)
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return None


def instance_name(inst):
    v = inst.property(PROP)
    return v[len(PREFIX):] if isinstance(v, str) and v.startswith(PREFIX) else None


class Terminal:
    __slots__ = ("owner", "term", "net", "point", "layer", "cluster")

    def __init__(self, owner, term, net, point, layer):
        self.owner, self.term, self.net, self.point, self.layer = owner, term, net, point, layer
        self.cluster = None

    @property
    def label(self):
        return f"{self.owner}.{self.term}" if self.owner else f"pin {self.term}"


def cell_pin_points(cell, recursive=True):
    """{pin name: [(DPoint, metal)]} from text labels on metal pin/label purposes."""
    layout = cell.layout()
    pins = {}
    for metal in METALS:
        for dt in (PIN, LABEL):
            li = layout.find_layer(LAYERS[metal], dt)
            if li is None:
                continue
            if recursive:
                it = cell.begin_shapes_rec(li)
                while not it.at_end():
                    s = it.shape()
                    if s.is_text():
                        pt = it.trans() * pya.Point(s.text.x, s.text.y)
                        pins.setdefault(s.text_string, []).append((pt.to_dtype(layout.dbu), metal))
                    it.next()
            else:
                for s in cell.shapes(li).each(pya.Shapes.STexts):
                    pins.setdefault(s.text_string, []).append((s.dtext.trans.disp.to_p(), metal))
    return pins


def terminals(layout, top, conn):
    """All terminals (instance terminals, top-level pins) of the linked layout, in top coordinates."""
    out, found = [], set()
    pin_cache = {}
    for inst in top.each_inst():
        name = instance_name(inst)
        spec = conn["instances"].get(name) if name else None
        if spec is None:
            continue
        found.add(name)
        trans = inst.dcplx_trans
        if spec["kind"] == "mos":
            geo = mos_geometry_from(spec["type"], inst.pcell_parameters_by_name())
            for term, net in spec["terminals"].items():
                if term in SKIP_TERMINALS:
                    continue
                for x, y, layer in geo["terminals"].get(term, []):
                    out.append(Terminal(name, term, net, trans * pya.DPoint(x / 1000, y / 1000), layer))
        else:
            ci = inst.cell_index
            if ci not in pin_cache:
                pin_cache[ci] = cell_pin_points(layout.cell(ci))
            for term, net in spec["terminals"].items():
                for pt, metal in pin_cache[ci].get(term, []):
                    out.append(Terminal(name, term, net, trans * pt, metal))
    top_pins = cell_pin_points(top, recursive=False)
    for pin in conn.get("pins", {}):
        for pt, metal in top_pins.get(pin, []):
            out.append(Terminal(None, pin, pin, pt, metal))
    return out, found


def extract(layout, top):
    """Flat net extraction over the ASAP7 conductor stack. Returns (l2n, regions by name)."""
    def region(name):
        r = pya.Region()
        for dt in (0, PIN):
            li = layout.find_layer(LAYERS[name], dt)
            if li is not None:
                r += pya.Region(top.begin_shapes_rec(li))
        return r.merged()

    regions = {name: region(name) for name in
               ["gate", "lig", "lisd", "v0"] + METALS + [f"v{i}" for i in range(1, 9)]}
    # GCUT removes gate material: without it, dummy gates would tie the rails together.
    drawn_gate = regions["gate"]
    regions["gate"] = drawn_gate - region("gcut")
    regions["sd"] = region("active") - drawn_gate
    l2n = pya.LayoutToNetlist(top.name, layout.dbu)
    for name, r in regions.items():
        l2n.register(r, name)
    for name, r in regions.items():
        l2n.connect(r)
    for a, b in CONNECTIONS:
        l2n.connect(regions[a], regions[b])
    l2n.extract_netlist()
    return l2n, regions


def _mst(groups):
    """Flight lines: minimum spanning tree between clusters, joining their closest terminals."""
    lines = []
    connected, rest = [groups[0]], groups[1:]
    while rest:
        best = None
        for gi, g in enumerate(rest):
            for a in (t for c in connected for t in c):
                for b in g:
                    d = a.point.distance(b.point)
                    if best is None or d < best[0]:
                        best = (d, gi, a, b)
        _, gi, a, b = best
        lines.append((a.point, b.point))
        connected.append(rest.pop(gi))
    return lines


def check(layout, top, conn):
    """Compare layout connectivity against the schematic link."""
    terms, found = terminals(layout, top, conn)
    l2n, regions = extract(layout, top)
    for i, t in enumerate(terms):
        net = l2n.probe_net(regions[t.layer], t.point) if t.layer in regions else None
        t.cluster = net.cluster_id if net is not None else ("isolated", i)
    by_net = {}
    for t in terms:
        by_net.setdefault(t.net, []).append(t)
    owners = {}
    for t in terms:
        if not isinstance(t.cluster, tuple):
            owners.setdefault(t.cluster, set()).add(t.net)
    nets = {}
    for net, ts in by_net.items():
        groups = {}
        for t in ts:
            groups.setdefault(t.cluster, []).append(t)
        group_list = sorted(groups.values(), key=lambda g: (-len(g), g[0].label))
        shorted = set()
        for c in groups:
            shorted |= owners.get(c, set())
        shorted.discard(net)
        nets[net] = {
            "terminals": len(ts),
            "pieces": len(group_list),
            "lines": _mst(group_list) if len(group_list) > 1 else [],
            "unconnected": [t.label for g in group_list[1:] for t in g],
            "shorts": sorted(shorted),
            "points": [t.point for t in ts],
        }
    in_layout = {instance_name(i) for i in top.each_inst()} - {None}
    return {
        "nets": nets,
        "missing": sorted(set(conn["instances"]) - found),
        "extra": sorted(in_layout - set(conn["instances"])),
    }


def summary(result):
    nets = result["nets"]
    opens = sum(1 for n in nets.values() if n["pieces"] > 1)
    shorts = sum(1 for n in nets.values() if n["shorts"])
    return {"nets": len(nets), "open": opens, "shorts": shorts,
            "missing": len(result["missing"]), "extra": len(result["extra"])}
