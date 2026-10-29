"""Parasitic extraction (PEX) of ASAP7 layouts - like a commercial 3D extractor: a
transistor-level SPICE netlist of the layout with the resistance of every wire and contact and the
capacitance between all nets, for post-layout simulation (`openlayout sim`).

    openlayout pex <layout.gds> [--cell NAME] [--out FILE] [--mode rc|c] [--rmodel reference|openroad]
                   [--schematic cell.spice]

1. Extraction: the ASAP7 LVS deck (pdk/asap7/klayout/lvs/asap7.lvs -rd pex=1) on a flattened copy
   of the cell - devices, nets and their shapes on the conductor layers.
2. Capacitance: a 3D field solver. fieldsolver.py builds the conductors of every net as 3D bodies
   from the ASAP7 process description (pdk/asap7/klayout/pex/asap7_pex.json: heights, a denser
   front-end dielectric under the k = 3.23 metal stack, calibrated against the library's
   reference extraction netlists) and FasterCap solves the capacitance matrix between all of them. Floating
   shapes (dummy gates) are grounded.
3. Resistance: KLayout's RNetExtractor turns each signal net into a resistor network between its
   pins and the transistor terminals (by default the sheet / via resistances of the library's
   reference extraction; --rmodel openroad: OpenROAD's setRC.tcl for M1-M9). Supply nets stay
   ideal. The capacitances of a net are spread over the nodes of its network by the wire area
   nearest to each node.
4. Netlist: <cell>.pex.spice, a subcircuit with the cell's pins (in the schematic's order when there
   is one) - N<i> d g s b <model> l=... nfin=... for the BSIM-CMG transistors, R and C elements.

docs/PEX.md has the process stack, where its numbers come from, and the comparison with the
library's reference extraction netlists.
"""
import argparse
import bisect
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import klayout.db as kdb
import klayout.pex as klp

from . import fieldsolver

FLOW = Path(os.environ.get("OPENLAYOUT_HOME", Path.home() / "openlayout/flow"))
DECK = FLOW / "pdk/asap7/klayout/lvs/asap7.lvs"
TECH_JSON = FLOW / "pdk/asap7/klayout/pex/asap7_pex.json"

HALO = 0.3              # um: the substrate plate and the dielectric interfaces reach this far out
MAX_EDGE = 0.03         # um: initial panel size of the conductor surfaces (FasterCap refines)
ACCURACY = 0.05         # FasterCap's relative stop criterion (-a)
FIN_PITCH_W = 0.027     # um of device width per fin (LVS: W = nfin x 27 nm)
TILE = 0.05             # um: wire pieces assigned to the nearest network node for the capacitance
MIN_C = 1e-20           # F: smaller capacitances are dropped (0.01 aF)
MIN_R = 1e-3            # Ohm: nodes joined by less are one node (e.g. two terminals on one diffusion)
WIN_MIN = 48            # conductors: more and --cap auto solves window by window
WIN_HALO = 0.10         # um: the context solved around each window (at least; _clear_halo)
WIN_GAP = 0.005         # um: between a net's piece in the window and its piece in the context
WIN_MIN_CC = 0.005      # windowed: couplings under this share of both nets' totals go to ground
POWER_RE = re.compile(r"^(VDD|VSS|VCC|GND|VPWR|VGND)", re.I)

# R network: conductor layers (LVS names) and cuts (cut, bottom, top) - the cut "v0lig" is V0 on LIG
# and "liglisd" the touching LIG / LISD overlap (no resistance of its own)
CONDUCTORS = ["gate", "sdx", "lig", "lisd"] + [f"m{i}" for i in range(1, 10)]
CUTS = [("gcon", "gate", "lig"), ("sdt", "sdx", "lisd"), ("v0", "lisd", "m1"), ("v0lig", "lig", "m1"),
        ("liglisd", "lig", "lisd")] + [(f"v{i}", f"m{i}", f"m{i + 1}") for i in range(1, 9)]
# nominal cut sizes (um^2), to turn the per-via resistance into KLayout's area resistance
CUT_AREA = {"gcon": 0.020 * 0.018, "sdt": 0.024 * 0.054, "v0": 0.018 ** 2, "v1": 0.018 ** 2,
            "v2": 0.018 ** 2, "v3": 0.018 ** 2, "v4": 0.024 ** 2, "v5": 0.024 ** 2, "v6": 0.032 ** 2,
            "v7": 0.032 ** 2, "v8": 0.040 ** 2}


def log(msg):
    print(msg, flush=True)


# ---- 1. extraction --------------------------------------------------------------------------------
def flatten(gds, cell, out):
    """`cell` of `gds` flattened into `out` - the labels of the cells below dropped (their pins are not
    the cell's)."""
    layout = kdb.Layout()
    layout.read(str(gds))
    top = layout.cell(cell)
    if top is None:
        raise SystemExit(f"openlayout pex: no cell {cell} in {gds}")
    for ci in top.called_cells():
        c = layout.cell(ci)
        for li in layout.layer_indexes():
            texts = [s for s in c.shapes(li).each() if s.is_text()]
            for s in texts:
                c.shapes(li).erase(s)
    top.flatten(True)
    opt = kdb.SaveLayoutOptions()
    opt.select_cell(top.cell_index())
    layout.write(str(out), opt)


def extract_netlist(gds, cell, work, schematic=None):
    flat = work / f"{cell}.flat.gds"
    flatten(gds, cell, flat)
    report = work / f"{cell}.pex.lvsdb"
    argv = ["klayout", "-b", "-r", str(DECK), "-rd", f"input={flat}", "-rd", f"topcell={cell}",
            "-rd", "pex=1", "-rd", f"report={report}"]
    if schematic:
        argv += ["-rd", f"schematic={schematic}"]
    res = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    if not re.search(r"^RESULT PEX-LVS ", res.stdout, re.M) or not report.is_file():
        raise SystemExit(f"openlayout pex: the extraction failed:\n{(res.stdout + res.stderr)[-1500:]}")
    lvsdb = kdb.LayoutVsSchematic()
    lvsdb.read(str(report))
    return lvsdb


# ---- 2. capacitance (FasterCap) -------------------------------------------------------------------
def load_tech():
    return json.loads(Path(TECH_JSON).read_text())


def solver_conductors(lvsdb, circ, tech, substrate_net):
    """{net: [(Region, z0, z1)]} for the field solver, and the window (Box, dbu) around them. The
    source / drain node is the diffusion `sd_gap` off every gate; the substrate is a plate on
    `substrate_net`."""
    dbu = lvsdb.internal_layout().dbu
    gap = int(round(tech["sd_gap"] / dbu))
    gates = lvsdb.layer_by_name("gate").merged()
    gates = gates.sized(gap) if gap > 0 else gates
    gate_index = kdb.Shapes()            # for the gates near a net (not the whole layout's every time)
    gate_index.insert(gates)
    heights = {n: (c["z0"], c["z1"]) for n, c in tech["conductors"].items()}
    heights.update({n: (c["z0"], c["z1"]) for n, c in tech["cuts"].items() if c["z1"] > c["z0"]})
    sources = {n: ("sd" if n == "sdx" else n) for n in heights}
    conds, bbox = {}, kdb.Box()
    for net in circ.each_net():
        pieces = []
        for name, (z0, z1) in heights.items():
            layer = lvsdb.layer_by_name(sources[name])
            if layer is None:
                continue
            r = lvsdb.shapes_of_net(net, layer, True)
            if r.is_empty():
                continue
            if name == "sdx":
                near = kdb.Region([s.polygon for s in gate_index.each_overlapping(r.bbox())])
                r = (r - near).merged()
            else:
                r = r.merged()
            if not r.is_empty():
                pieces.append((r, z0, z1))
                bbox += r.bbox()
        if pieces:
            conds[net.expanded_name()] = pieces
    halo = int(round(HALO / dbu))
    window = bbox.enlarged(halo, halo)
    conds.setdefault(substrate_net, []).append((kdb.Region(window), tech["substrate_z"], tech["substrate_z"]))
    return conds, window


def capacitance(lvsdb, cell, work, tech, substrate_net, cap="auto", grid=None, halo=WIN_HALO, cache=True,
                stats=None, jobs=1):
    """{net: C} ground and {(net, net): C} coupling capacitances (F), by FasterCap - flat (one solve
    of every net) or windowed (windowed_capacitance); `cap` "auto": windowed above WIN_MIN conductors."""
    circ = lvsdb.netlist().circuit_by_name(cell)
    conds, window = solver_conductors(lvsdb, circ, tech, substrate_net)
    if cap == "window" or (cap == "auto" and len(conds) > WIN_MIN):
        plate = conds[substrate_net].pop()
        if not conds[substrate_net]:
            del conds[substrate_net]
        return windowed_capacitance(conds, plate, window, lvsdb.internal_layout().dbu, tech, work,
                                    substrate_net, grid, halo, cache, stats, jobs)
    diel = tech["dielectric"]
    names, mat, _ = fieldsolver.capacitance_matrix(
        conds, lvsdb.internal_layout().dbu, diel["k"], work / "fastercap",
        [(i["z"], i["k_above"]) for i in diel["interfaces"]], window, MAX_EDGE, ACCURACY)
    ground, coupling = defaultdict(float), {}
    for i, a in enumerate(names):
        ground[a] += sum(mat[i])                                   # what is left: to infinity
        for j in range(i + 1, len(names)):
            c = -(mat[i][j] + mat[j][i]) / 2
            if c > 0:
                coupling[(a, names[j])] = c
    return dict(ground), coupling, None


# ---- 2b. windowed capacitance (large blocks) ------------------------------------------------------
def array_grid(gds, cell):
    """(x0, y0, px, py) um: origin and pitch of the cell placed most often in `cell` (an array's bit
    cell) - the windows of windowed_capacitance - or None when no cell is placed twice. The pitch is
    that of the placed cells' boxes, the origin that of their placements (rows mirrored about a
    shared rail have it on the rail)."""
    layout = kdb.Layout()
    layout.read(str(gds))
    top = layout.cell(cell)
    if top is None:
        return None
    boxes, origins = defaultdict(list), defaultdict(list)
    for inst in top.each_inst():
        bbox = layout.cell(inst.cell_index).bbox()
        for t in inst.cell_inst.each_cplx_trans():
            boxes[inst.cell_index].append(bbox.transformed(t))
            origins[inst.cell_index].append(t.disp)
    ci = max(boxes, key=lambda c: len(boxes[c]), default=None)
    best = boxes[ci] if ci is not None else []
    if len(best) < 2:
        return None

    def pitch(values, size):
        v = sorted(set(values))
        d = [b - a for a, b in zip(v, v[1:]) if b > a]
        return min(d) if d else size

    xs, ys = [b.left for b in best], [b.bottom for b in best]
    d = layout.dbu
    return (min(p.x for p in origins[ci]) * d, min(p.y for p in origins[ci]) * d,
            pitch(xs, best[0].width()) * d, pitch(ys, best[0].height()) * d)


def _edge_costs(conds, bbox, origin, pitch, vertical, dbu, candidates, sides):
    """For each candidate d (dbu): the conductor area near the lines origin + k * pitch + s(d) for s
    in `sides` - how much a window edge there would cut shapes lengthwise. Looked at in a few
    pitches at the block's centre."""
    c = bbox.center()
    span = 3 * pitch
    sample = kdb.Box(c.x - span, bbox.bottom, c.x + span, bbox.top) if vertical else \
        kdb.Box(bbox.left, c.y - span, bbox.right, c.y + span)
    shapes = kdb.Region()
    for pieces in conds.values():
        for r, _, _ in pieces:
            if r.bbox().overlaps(sample):
                shapes += r & kdb.Region(sample)
    shapes.merged_semantics = False
    band = max(1, int(round(0.004 / dbu)))
    lo, hi = (sample.left, sample.right) if vertical else (sample.bottom, sample.top)
    costs = []
    for d in candidates:
        edges = kdb.Region()
        for side in sides:
            o = origin + side(d)
            e = o + ((lo - o) // pitch) * pitch
            while e <= hi:
                edges.insert(kdb.Box(e - band, sample.bottom, e + band, sample.top) if vertical else
                             kdb.Box(sample.left, e - band, sample.right, e + band))
                e += pitch
        costs.append((shapes & edges).area())
    return costs


def _runs(costs):
    """(length, start) of the runs of the least cost (within 5 %)."""
    best = min(costs)
    runs, start = [], None
    for k, cst in enumerate(costs + [None]):
        if cst is not None and cst <= best * 1.05:
            start = k if start is None else start
        elif start is not None:
            runs.append((k - start, start))
            start = None
    return runs


def _clear_offset(conds, bbox, origin, pitch, vertical, dbu):
    """The shift of the window edges (dbu, 0 .. pitch) that cuts the fewest shapes lengthwise - a wire
    split along its length by WIN_GAP couples hugely to itself and the cancellation costs accuracy
    (mirrored rows put the rail exactly on the cell's edge): the middle of the longest clear run."""
    step = max(1, int(round(0.002 / dbu)))
    length, start = max(_runs(_edge_costs(conds, bbox, origin, pitch, vertical, dbu, range(0, pitch, step),
                                          [lambda d: d])))
    return int(round((start + (length - 1) / 2) * step))


def _clear_halo(conds, bbox, origin, pitch, vertical, dbu, h):
    """The halo (dbu, h .. h + 50 nm) whose outer edges cut the fewest shapes lengthwise - a context
    shape cut along its length leaves a sliver that shields its window too little: the smallest one
    a step inside a clear run."""
    step = max(1, int(round(0.002 / dbu)))
    cands = list(range(h, h + int(round(0.05 / dbu)) + 1, step))
    runs = _runs(_edge_costs(conds, bbox, origin, pitch, vertical, dbu, cands, [lambda d: -d, lambda d: d]))
    length, start = min(runs, key=lambda r: r[1])
    return cands[start + (1 if length > 2 else 0)]


def _geometry_key(pieces, dx, dy):
    return ";".join(sorted(f"{z0:g},{z1:g}:" + " ".join(sorted(str(p) for p in r.moved(dx, dy).each()))
                           for r, z0, z1 in pieces))


def windowed_capacitance(conds, plate, window, dbu, tech, work, substrate_net, grid=None, halo=WIN_HALO,
                         cache=True, stats=None, jobs=1):
    """Ground and coupling capacitances window by window, for blocks too large for one solve. The
    block is cut into a grid of windows - by default the pitch of its array (array_grid), `grid` =
    (x0, y0, px, py) um, shifted to cut across wires rather than along them (_clear_offset); the
    outer windows reach to the block's edges (no slivers). Each window is solved with the context
    `halo` um around it: the nets' pieces in the window, and apart from them (WIN_GAP) their pieces
    in the context, the substrate plate under both. The window's rows of the matrix (whole nets summed) are its share of the ground
    capacitances and couplings; a coupling between two windows' nets is the mean of both windows'
    rows. Windows alike - the same shapes in and around them, as in an array - are solved once
    (FasterCap, `jobs` at a time) and the result is kept in ~/.cache/openlayout/pex for later runs."""
    import hashlib
    diel = tech["dielectric"]
    ifaces = [(i["z"], i["k_above"]) for i in diel["interfaces"]]
    bbox = kdb.Box()
    for pieces in conds.values():
        for r, _, _ in pieces:
            bbox += r.bbox()
    if grid is None:
        grid = (bbox.left * dbu, bbox.bottom * dbu, 1.0, 1.0)
    x0, y0, px, py = (int(round(v / dbu)) for v in grid)
    x0 += _clear_offset(conds, bbox, x0, px, True, dbu)
    y0 += _clear_offset(conds, bbox, y0, py, False, dbu)
    h, g = int(round(halo / dbu)), max(1, int(round(WIN_GAP / dbu)))
    hx = _clear_halo(conds, bbox, x0, px, True, dbu, h)
    hy = _clear_halo(conds, bbox, y0, py, False, dbu, h)
    h = max(hx, hy)
    PLATE = "\0plate"

    def bounds(lo, hi, o, p):          # window edges: the grid inside the block, the block's edges outside
        k = math.ceil((lo + p / 2 - o) / p)
        inner = []
        while o + k * p < hi - p / 2:
            inner.append(o + k * p)
            k += 1
        return [lo] + inner + [hi]

    xb, yb = bounds(bbox.left, bbox.right, x0, px), bounds(bbox.bottom, bbox.top, y0, py)

    def span(edges, lo, hi):
        return range(max(0, bisect.bisect_right(edges, lo) - 1), min(len(edges) - 1, bisect.bisect_left(edges, hi)))

    # the windows each net's pieces reach into (with the halo)
    buckets = defaultdict(set)
    for name, pieces in conds.items():
        for r, _, _ in pieces:
            b = r.bbox()
            for i in span(xb, b.left - h, b.right + h):
                for j in span(yb, b.bottom - h, b.top + h):
                    buckets[(i, j)].add(name)

    salt = hashlib.sha256((Path(TECH_JSON).read_text() + repr((MAX_EDGE, ACCURACY, hx, hy, g, px, py, dbu, "win4")))
                          .encode()).hexdigest()
    cdir = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "openlayout" / "pex"
    if cache:
        cdir.mkdir(parents=True, exist_ok=True)
    solved, results = {}, {}            # in this run: key -> result; window -> (key, net names)
    pending = {}                         # key -> (conductors, box) of the kinds of window to solve
    nhit = ndisk = biggest = 0
    t0 = time.time()
    windows = sorted(buckets)
    for n, (i, j) in enumerate(windows):
        core = kdb.Box(xb[i], yb[j], xb[i + 1], yb[j + 1])
        clip = core.enlarged(hx, hy)
        core_r, clip_r, inner_r = kdb.Region(core), kdb.Region(clip), kdb.Region(core.enlarged(g, g))
        items = []                       # (kind, net, pieces): "c" in the window, "h" in the context
        for name in buckets[(i, j)]:
            cp, hp = [], []
            for r, z0, z1 in conds[name]:
                if not r.bbox().overlaps(clip):
                    continue
                c = (r & core_r).merged()
                o = ((r & clip_r) - inner_r).merged()
                if not c.is_empty():
                    cp.append((c, z0, z1))
                if not o.is_empty():
                    hp.append((o, z0, z1))
            if cp:
                items.append(("c", name, cp))
            if hp:
                items.append(("h", name, hp))
        if not any(k == "c" for k, _, _ in items):
            continue
        sub = (plate[0] & clip_r).merged()
        if not sub.is_empty():
            items.append(("h", PLATE, [(sub, plate[1], plate[2])]))
        # canonical form: nets numbered by their pieces' shapes, relative to the window
        keyed = sorted((kind, _geometry_key(pieces, -core.left, -core.bottom), name, pieces)
                       for kind, name, pieces in items)
        index = {}
        for _, _, name, _ in keyed:
            index.setdefault(name, len(index))
        text = f"{core.width()} {core.height()}\n" + "\n".join(f"{kind}{index[name]}|{gk}" for kind, gk, name, _ in keyed)
        key = hashlib.sha256((salt + text).encode()).hexdigest()
        if key in solved or key in pending:
            nhit += 1
        elif cache and (cdir / f"{key}.json").is_file():
            solved[key] = {int(a): {"ground": v["ground"], "to": {int(b): c for b, c in v["to"].items()}}
                           for a, v in json.loads((cdir / f"{key}.json").read_text()).items()}
            ndisk += 1
        else:
            pending[key] = ({f"{kind}{index[name]}": [(r.moved(-core.left, -core.bottom), z0, z1)
                                                      for r, z0, z1 in pieces]
                             for kind, _, name, pieces in keyed}, clip.moved(-core.left, -core.bottom))
        results[(i, j)] = (key, {k: name for name, k in index.items()})
        if (n + 1) % 1000 == 0:
            log(f"    windows {n + 1}/{len(windows)}: {len(pending)} to solve, {nhit} alike ({time.time() - t0:.0f} s)")

    def solve(item):                     # one kind of window: its rows of the matrix, per net
        k, (key, (moved, box)) = item
        names, mat, _ = fieldsolver.capacitance_matrix(moved, dbu, diel["k"], work / "fastercap" / f"w{k}", ifaces,
                                                       box, MAX_EDGE, ACCURACY)
        res = {}
        for a, na in enumerate(names):
            if na[0] != "c":
                continue
            to = defaultdict(float)
            for b, nb in enumerate(names):
                to[int(nb[1:])] += mat[a][b]
            to.pop(int(na[1:]))
            res[int(na[1:])] = {"ground": sum(mat[a]), "to": {kk: -v for kk, v in to.items()}}
        if cache:
            (cdir / f"{key}.json").write_text(json.dumps(res))
        return key, res, len(names)

    nsolve = len(pending)
    if pending:
        log(f"    {nsolve} kinds of window to solve, {max(1, jobs)} at a time")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:     # FasterCap runs as its own process
        for key, res, nc in pool.map(solve, enumerate(pending.items())):
            solved[key] = res
            biggest = max(biggest, nc)

    # sum the windows' shares: self capacitance and directed couplings per net
    self_c, directed, has_core = defaultdict(float), defaultdict(float), set()
    for key, names in results.values():
        for ka, v in solved[key].items():
            a = names[ka]
            has_core.add(a)
            self_c[a] += v["ground"] + sum(v["to"].values())
            for kb, c in v["to"].items():
                directed[(a, names[kb])] += c
    coupling = defaultdict(float)
    for a, b in {tuple(sorted(k)) for k in directed if PLATE not in k}:
        ab, ba = directed.get((a, b)), directed.get((b, a))
        coupling[(a, b)] += (ab + ba) / 2 if ab is not None and ba is not None else (ab if ab is not None else ba)
    for (a, b), c in directed.items():
        if b == PLATE and a != substrate_net:
            coupling[tuple(sorted((a, substrate_net)))] += c
    coupling = {k: c for k, c in coupling.items() if c > 0}
    ground = dict(self_c)
    for (a, b), c in coupling.items():
        ground[a] = ground.get(a, 0.0) - c
        ground[b] = ground.get(b, 0.0) - c
    ground = {k: max(0.0, v) for k, v in ground.items()}

    # the same capacitances where they are: each window's share with its box (um), for the nodes of
    # the R networks in it; couplings under WIN_MIN_CC of either net's total go to ground
    total = defaultdict(float, ground)
    for (a, b), c in coupling.items():
        total[a] += c
        total[b] += c
    small = {k for k, c in coupling.items() if c < WIN_MIN_CC * min(total[k[0]], total[k[1]])}
    rows = defaultdict(float)
    for key, names in results.values():
        for ka, v in solved[key].items():
            rows[names[ka]] += v["ground"]
    local = []
    for (i, j), (key, names) in results.items():
        p = (xb[i] * dbu, yb[j] * dbu, xb[i + 1] * dbu, yb[j + 1] * dbu)
        for ka, v in solved[key].items():
            a = names[ka]
            g_here = v["ground"] * (ground[a] / rows[a] if rows[a] > 0 else 0.0)
            for kb, c in v["to"].items():
                b = names[kb]
                if b == PLATE:
                    b = substrate_net
                elif (b, a) in directed:                     # the other half comes from b's windows
                    c /= 2
                pair = tuple(sorted((a, b)))
                if a == b or pair not in coupling:
                    continue
                if pair in small:
                    g_here += c
                    local.append((b, None, c, p))
                else:
                    local.append((a, b, c, p))
            local.append((a, None, g_here, p))
    log(f"  windows: {len(results)} of {px * dbu:g} x {py * dbu:g} um at ({x0 * dbu:g}, {y0 * dbu:g}) "
        f"(+{hx * dbu:g} / {hy * dbu:g} um), {nsolve} solved "
        f"(up to {biggest} conductors), {nhit} alike, {ndisk} from the cache ({time.time() - t0:.1f} s); "
        f"{len(coupling) - len(small)} of {len(coupling)} couplings kept")
    if stats is not None:
        kinds = {}
        stats.update(windows=len(results), solved=nsolve, alike=nhit, cached=ndisk, conductors=biggest,
                     halo=(hx * dbu, hy * dbu),
                     kinds={f"{i},{j}": kinds.setdefault(key, len(kinds)) for (i, j), (key, _) in sorted(results.items())})
    return ground, coupling, local


# ---- 3. resistance (KLayout RNetExtractor) --------------------------------------------------------
def r_tech(tech, rmodel="reference"):
    """The KLayout R extractor technology (layer ids index CONDUCTORS + CUTS). rmodel "openroad":
    OpenROAD's M1-M9 / V1-V8 values."""
    ids = {name: i for i, name in enumerate(CONDUCTORS + [c[0] for c in CUTS])}
    rt = klp.RExtractorTech()
    for name in CONDUCTORS:
        spec = tech["conductors"][name]
        c = klp.RExtractorTechConductor()
        c.layer = ids[name]
        c.resistance = spec["openroad_sheet"] if rmodel == "openroad" and "openroad_sheet" in spec else spec["sheet"]
        c.algorithm = klp.RExtractorTechConductor.SquareCounting
        rt.add_conductor(c)
    for cut, bottom, top in CUTS:
        v = klp.RExtractorTechVia()
        v.cut_layer, v.bottom_conductor, v.top_conductor = ids[cut], ids[bottom], ids[top]
        spec = tech["cuts"].get("v0" if cut == "v0lig" else cut)
        if spec is None:                   # the LIG / LISD overlap: touching, no resistance of its own
            v.resistance = 1e-7
        elif rmodel == "openroad" and "openroad_rarea" in spec:
            v.resistance = spec["openroad_rarea"]
        else:
            v.resistance = spec["rarea"]                                               # Ohm um^2
        v.merge_distance = 0.0
        rt.add_via(v)
    return rt, ids


def net_geometry(lvsdb, net):
    """{layer name: Region} of a net, the derived cuts included."""
    g = {}
    for name in CONDUCTORS + ["gcon", "sdt", "v0"] + [f"v{i}" for i in range(1, 9)]:
        layer = lvsdb.layer_by_name(name)
        if layer is None:
            continue
        r = lvsdb.shapes_of_net(net, layer, True)
        if not r.is_empty():
            g[name] = r.merged()
    if "v0" in g:
        on_lisd = g["v0"] & g["lisd"] if "lisd" in g else kdb.Region()
        g["v0lig"] = g["v0"] - on_lisd
        g["v0"] = on_lisd
    if "lig" in g and "lisd" in g:
        g["liglisd"] = g["lig"] & g["lisd"]
    return {k: v for k, v in g.items() if not v.is_empty()}


def pin_points(gds, cell):
    """{label: DPoint} of the cell's own labels (the pins)."""
    layout = kdb.Layout()
    layout.read(str(gds))
    top = layout.cell(cell)
    pts = {}
    for li in layout.layer_indexes():
        for s in top.shapes(li).each():
            if s.is_text():
                pts.setdefault(s.text_string, s.dtext.trans.disp.to_p())
    return pts


def r_network(lvsdb, net, tech, ids, terminals, pin_point):
    """The resistor network of `net`: (nodes {object_id: (kind, info, DBox, layer)},
    elements [(a, b, R)], geometry)."""
    dbu = lvsdb.internal_layout().dbu
    geo = net_geometry(lvsdb, net)
    vertex, polygon = defaultdict(list), defaultdict(list)
    vertex_info, polygon_info = defaultdict(list), defaultdict(list)
    for key, layer, poly in terminals:              # transistor terminals: polygon ports
        polygon[ids[layer]].append(poly)
        polygon_info[ids[layer]].append(key)
    if pin_point is not None:                        # the pin: a vertex port on the top-most layer there
        p = pin_point.to_itype(dbu)
        probe = kdb.Region(kdb.Box(p, p).enlarged(1, 1))
        for name in reversed(CONDUCTORS):
            if name in geo and not geo[name].interacting(probe).is_empty():
                vertex[ids[name]].append(p)
                vertex_info[ids[name]].append("pin")
                break
    regions = {ids[k]: v for k, v in geo.items()}
    network = klp.RNetExtractor(dbu).extract(tech, regions, dict(vertex), dict(polygon))
    nodes = {}
    for n in network.each_node():
        t = n.type()
        if t == klp.RNodeType.VertexPort:
            kind, info = "pin", None
        elif t == klp.RNodeType.PolygonPort:
            kind, info = "terminal", polygon_info[n.layer()][n.port_index()]
        else:
            kind, info = "internal", None
        nodes[n.object_id()] = (kind, info, n.location(), n.layer())
    elements = [(e.a().object_id(), e.b().object_id(), e.resistance()) for e in network.each_element()]
    return nodes, elements, geo


def node_weights(nodes, geo, ids, dbu):
    """{node id: share of the net's wire area nearest to it} (sums to 1)."""
    by_layer = defaultdict(list)
    for nid, (_, _, box, layer) in nodes.items():
        by_layer[layer].append((nid, box.center()))
    every = [x for v in by_layer.values() for x in v]
    w = defaultdict(float)
    for name in CONDUCTORS:
        if name not in geo:
            continue
        cands = by_layer.get(ids[name]) or every
        for poly in geo[name].decompose_trapezoids_to_region().each():
            b = poly.bbox().to_dtype(dbu)
            n = max(1, math.ceil(max(b.width(), b.height()) / TILE))
            horizontal = b.width() >= b.height()
            for k in range(n):
                if horizontal:
                    piece = kdb.DBox(b.left + k * b.width() / n, b.bottom, b.left + (k + 1) * b.width() / n, b.top)
                else:
                    piece = kdb.DBox(b.left, b.bottom + k * b.height() / n, b.right, b.bottom + (k + 1) * b.height() / n)
                c = piece.center()
                nid = min(cands, key=lambda x: (x[1].x - c.x) ** 2 + (x[1].y - c.y) ** 2)[0]
                w[nid] += piece.area()
    total = sum(w.values())
    if total <= 0:
        return {nid: 1 / len(nodes) for nid in nodes}
    return {nid: w[nid] / total for nid in nodes}


# ---- 4. netlist -----------------------------------------------------------------------------------
def spice_name(name):
    if name.startswith("$"):
        name = "net" + name[1:]
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def extract(gds, cell=None, out=None, mode="rc", schematic=None, keep=False, rmodel="reference", cap="auto",
            window=None, halo=WIN_HALO, cache=True, jobs=1):
    """PEX of `cell` in `gds` into `out` (<cell>.pex.spice next to the layout). Returns a summary.
    `cap`: "flat" (one FasterCap solve), "window" (windowed_capacitance; `window` = (wx, wy) um,
    default the array's pitch, `jobs` FasterCaps at a time) or "auto" (windowed above WIN_MIN conductors)."""
    tech = load_tech()
    gds = Path(gds).resolve()
    if cell is None:
        layout = kdb.Layout()
        layout.read(str(gds))
        cell = layout.top_cell().name
    out = Path(out) if out else gds.with_name(f"{cell}.pex.spice")
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="ol_pex_"))
    t0 = time.time()
    log(f"PEX {cell}: layout {gds}")
    lvsdb = extract_netlist(gds, cell, work, schematic)
    circ = lvsdb.netlist().circuit_by_name(cell)
    if circ is None:
        raise SystemExit(f"openlayout pex: no circuit {cell} extracted")
    log(f"  extracted: {sum(1 for _ in circ.each_device())} transistors, {sum(1 for _ in circ.each_net())} nets"
        f" ({time.time() - t0:.1f} s)")

    nets = {n.expanded_name(): n for n in circ.each_net()}
    pins = [p.name() for p in circ.each_pin()]
    ref = lvsdb.reference.circuit_by_name(cell.upper()) if lvsdb.reference else None
    if ref is not None:
        order = [p.name() for p in ref.each_pin()]
        if sorted(x.upper() for x in order) == sorted(x.upper() for x in pins):
            by_upper = {x.upper(): x for x in pins}
            pins = [by_upper[x.upper()] for x in order]
    power = {n for n in nets if POWER_RE.match(n)}
    vss = next((n for n in pins if n.upper().startswith(("VSS", "GND", "VGND"))), None) or \
        next((n for n in nets if n.upper().startswith("VSS")), "0")
    vdd = next((n for n in pins if n.upper().startswith(("VDD", "VCC", "VPWR"))), None) or \
        next((n for n in nets if n.upper().startswith("VDD")), vss)
    floating = {name for name, n in nets.items() if n.pin_count() == 0 and n.terminal_count() == 0}

    t1 = time.time()
    grid, wstats = array_grid(gds, cell), {}
    if window:
        grid = (grid[0] if grid else 0.0, grid[1] if grid else 0.0) + tuple(window)
    ground, coupling, local = capacitance(lvsdb, cell, work, tech, vss if vss != "0" else "SUBSTRATE", cap, grid,
                                          halo, cache, wstats, jobs)
    log(f"  capacitance: FasterCap, {len(ground)} conductors ({time.time() - t1:.1f} s)")

    # device terminals: (net, (device index, terminal), layer, polygon)
    devices = list(circ.each_device())
    dev_index = {d.id(): i for i, d in enumerate(devices)}
    terminals = defaultdict(list)
    sdx = lvsdb.layer_by_name("sdx")
    to_um = kdb.CplxTrans(lvsdb.internal_layout().dbu)
    in_abstract = {}       # (device abstract, terminal): its shapes in the abstract's frame

    def terminal_shapes(tr):
        # shapes_of_terminal takes longer the larger the layout: once per abstract, then moved
        d = tr.device()
        if d.device_abstract is None or any(True for _ in d.each_combined_abstract()):
            return lvsdb.shapes_of_terminal(tr, kdb.ICplxTrans())
        t = to_um.inverted() * d.trans * to_um
        key = (d.device_abstract.cell_index(), tr.terminal_id())
        if key not in in_abstract:
            in_abstract[key] = lvsdb.shapes_of_terminal(tr, t.inverted())
        return {li: reg.transformed(t) for li, reg in in_abstract[key].items()}

    for name, n in nets.items():
        sd_of_net = None
        for tr in n.each_terminal():
            d, t = tr.device(), tr.terminal_def().name
            key = (dev_index[d.id()], t)
            for li, reg in terminal_shapes(tr).items():
                lname = lvsdb.layer_name(li)
                if lname == "sd":                     # source / drain: on the sdx node of the net
                    if sd_of_net is None:
                        sd_of_net = lvsdb.shapes_of_net(n, sdx, True).merged()
                    reg = reg & sd_of_net
                    lname = "sdx"
                if lname not in CONDUCTORS:
                    continue
                for poly in reg.merged().each():
                    terminals[name].append((key, lname, poly))

    node_of_terminal = {}
    r_lines, c_lines = [], []
    net_nodes = {}         # net -> {node name: (weight, DPoint or None)}
    t2 = time.time()
    rt, ids = r_tech(tech, rmodel)
    pts = pin_points(work / f"{cell}.flat.gds", cell) if mode == "rc" else {}
    for name, n in nets.items():
        sname = spice_name(name)
        if name in floating:
            net_nodes[name] = {spice_name(vss) if vss != "0" else "0": (1.0, None)}
            continue
        multi = mode == "rc" and name not in power and len(terminals[name]) + (n.pin_count() > 0) >= 2
        if not multi:
            net_nodes[name] = {sname: (1.0, None)}
            for key, _, _ in terminals[name]:
                node_of_terminal[key] = sname
            continue
        nodes, elements, geo = r_network(lvsdb, n, rt, ids, terminals[name], pts.get(name))
        names, k = {}, 0
        for nid, (kind, info, _, _) in nodes.items():
            if kind == "pin":
                names[nid] = sname
            else:
                k += 1
                names[nid] = f"{sname}_{k}" if n.pin_count() > 0 or k > 1 else sname
        if n.pin_count() > 0 and sname not in names.values():
            # no pin node (label not on a conductor): the first terminal node is the pin
            first = next(iter(names))
            names[first] = sname
        # join the nodes a (near) zero resistance connects - the pin's name wins
        for a, b, r in elements:
            if r < MIN_R and names[a] != names[b]:
                keep, drop = sorted((names[a], names[b]), key=lambda x: (x != sname, len(x), x))
                for nid in names:
                    if names[nid] == drop:
                        names[nid] = keep
        elements = [e for e in elements if names[e[0]] != names[e[1]]]
        for nid, (kind, info, _, _) in nodes.items():
            if kind == "terminal":
                node_of_terminal.setdefault(info, names[nid])
        for key, _, _ in terminals[name]:
            node_of_terminal.setdefault(key, sname)
        for a, b, r in elements:
            r_lines.append((names[a], names[b], r))
        weights = node_weights(nodes, geo, ids, lvsdb.internal_layout().dbu)
        nn = {}
        for nid, wv in weights.items():
            w0, p0 = nn.get(names[nid], (0.0, None))
            nn[names[nid]] = (w0 + wv, p0 or nodes[nid][2].center())
        net_nodes[name] = nn
    log(f"  resistance: {len(r_lines)} resistors ({time.time() - t2:.1f} s)")

    # capacitances onto the nodes: ground ones to VSS, couplings node to node
    gnd = spice_name(vss) if vss != "0" else "0"
    caps = defaultdict(float)
    total = defaultdict(float)

    def add(a, b, c):
        if a != b and c > 0:
            caps[tuple(sorted((a, b)))] += c

    for name, c in ground.items():
        if name not in net_nodes:
            continue
        total[name] += c
        if local is not None:
            continue
        for node, (wv, _) in net_nodes[name].items():
            add(node, gnd, c * wv)
    spread = {}

    def share(net, box):
        # the nodes of `net` in the window box (x0, y0, x1, y1 um) by their wire area, else the nearest
        if (net, box) not in spread:
            nn = [(k, w, q) for k, (w, q) in net_nodes[net].items() if q is not None]
            inside = [x for x in nn if box[0] <= x[2].x <= box[2] and box[1] <= x[2].y <= box[3]]
            tot = sum(w for _, w, _ in inside)
            if inside and tot > 0:
                spread[(net, box)] = [(k, w / tot, q) for k, w, q in inside]
            elif nn:
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                spread[(net, box)] = [min(nn, key=lambda x: (x[2].x - cx) ** 2 + (x[2].y - cy) ** 2)[:1] + (1.0, None)]
            else:
                spread[(net, box)] = [(next(iter(net_nodes[net])), 1.0, None)]
        return spread[(net, box)]

    for a, b, c, box in local or ():                 # windowed: each window's share in the window
        if a not in net_nodes or (b is not None and b not in net_nodes):
            continue
        sa = share(a, box)
        if b is None:
            for node, w, _ in sa:
                add(node, gnd, c * w)
            continue
        sb = share(b, box)
        if len(sa) < len(sb):
            sa, sb = sb, sa
        for node, w, q in sa:                         # each to the nearest node of the other net
            target = sb[0][0] if len(sb) == 1 or q is None else \
                min(sb, key=lambda x: (x[2].x - q.x) ** 2 + (x[2].y - q.y) ** 2)[0]
            add(node, target, c * w)
    for (a, b), c in coupling.items():
        if a not in net_nodes or b not in net_nodes:
            continue
        total[a] += c
        total[b] += c
        if local is not None:
            continue
        na, nb = net_nodes[a], net_nodes[b]
        if len(na) < len(nb):
            na, nb = nb, na
        # spread over the nodes of the net with more of them, each to the nearest node of the other
        for node, (wv, p) in na.items():
            if len(nb) == 1 or p is None:
                target = next(iter(nb))
            else:
                target = min((x for x in nb.items() if x[1][1] is not None),
                             key=lambda x: (x[1][1].x - p.x) ** 2 + (x[1][1].y - p.y) ** 2)[0]
            add(node, target, c * wv)
    for (a, b), c in sorted(caps.items()):
        if c >= MIN_C:
            c_lines.append((a, b, c))

    # write
    lines = [f"* {cell} - parasitic extraction by OpenLayout (openlayout pex, mode {mode})",
             f"* layout: {gds}",
             f"* C: FasterCap 3D field solver (k = {tech['dielectric']['k']:g} front end, "
             + ", ".join(f"{i['k_above']:g} above z = {i['z']:g} um" for i in tech["dielectric"]["interfaces"])
             + f"); R: KLayout RNetExtractor, {rmodel} sheet / via resistances",
             f"* {len(devices)} transistors, {len(r_lines)} resistors, {len(c_lines)} capacitors",
             "* total capacitance per net (fF): " +
             ", ".join(f"{spice_name(n)} {total[n] * 1e15:.4f}" for n in pins + sorted(set(total) - set(pins) - floating)
                       if n in total),
             "", f".subckt {cell} " + " ".join(spice_name(p) for p in pins)]
    for i, d in enumerate(devices):
        cls = d.device_class().name
        node = {t.name: node_of_terminal.get((i, t.name), spice_name(d.net_for_terminal(t.id()).expanded_name()))
                for t in d.device_class().terminal_definitions()}
        bulk = spice_name(vdd if cls.startswith("pmos") else vss)
        nfin = max(1, round(d.parameter("W") / FIN_PITCH_W))
        lines.append(f"N{i + 1} {node['D']} {node['G']} {node['S']} {bulk} {cls} l={d.parameter('L') * 1000:g}n nfin={nfin}")
    for k, (a, b, r) in enumerate(r_lines):
        lines.append(f"R{k + 1} {a} {b} {r:.6g}")
    for k, (a, b, c) in enumerate(c_lines):
        lines.append(f"C{k + 1} {a} {b} {c * 1e15:.6g}f")
    lines += [".ends", ""]
    out.write_text("\n".join(lines))
    summary = {"cell": cell, "out": str(out), "devices": len(devices), "resistors": len(r_lines),
               "capacitors": len(c_lines), "total_fF": {n: total[n] * 1e15 for n in pins if n in total},
               "all_fF": {spice_name(n): c * 1e15 for n, c in total.items() if n not in floating},
               "seconds": time.time() - t0, "work": str(work),
               "windows": wstats or None}
    log(f"  netlist: {out}")
    log(f"RESULT PEX {cell} devices={len(devices)} resistors={len(r_lines)} capacitors={len(c_lines)} "
        + " ".join(f"C({spice_name(n)})={v:.4f}fF" for n, v in summary["total_fF"].items()))
    if not keep:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(prog="openlayout pex", description=__doc__.split("\n\n")[0])
    ap.add_argument("layout")
    ap.add_argument("--cell")
    ap.add_argument("--out", help="netlist file (default <cell>.pex.spice next to the layout)")
    ap.add_argument("--mode", choices=("rc", "c"), default="rc",
                    help="rc: resistor networks and capacitances (default); c: capacitances only")
    ap.add_argument("--rmodel", choices=("reference", "openroad"), default="reference",
                    help="reference: the library's reference-extraction sheet / via resistances (default); "
                         "openroad: OpenROAD's setRC.tcl values for M1-M9 / V1-V8")
    ap.add_argument("--schematic", help="SPICE netlist of the cell, for the order of the pins")
    ap.add_argument("--cap", choices=("auto", "flat", "window"), default="auto",
                    help="flat: one 3D solve of every net; window: window by window, alike windows solved "
                         f"once (large blocks); auto (default): window above {WIN_MIN} nets")
    ap.add_argument("--window", help="WX,WY: window size in um (default: the pitch of the array's cell)")
    ap.add_argument("--halo", type=float, default=WIN_HALO, help=f"context around each window, um (default {WIN_HALO})")
    ap.add_argument("--jobs", type=int, default=1, help="windows solved at the same time (default 1)")
    ap.add_argument("--no-cache", action="store_true", help="solve every window again (no ~/.cache/openlayout/pex)")
    ap.add_argument("--keep", action="store_true", help="keep the working files (FasterCap input, LVSDB)")
    a = ap.parse_args(argv)
    window = tuple(float(v) for v in a.window.split(",")) if a.window else None
    extract(a.layout, a.cell, a.out, a.mode, a.schematic, a.keep, a.rmodel, a.cap, window, a.halo, not a.no_cache,
            a.jobs)


if __name__ == "__main__":
    main()
