"""3D capacitance extraction with FasterCap: the conductors of every net, built from their layout
shapes and a process stack, and the capacitance matrix between them.

The layout is 2.5D - every layer a slab between two heights - so a net's surface comes from
cutting the z axis at every layer boundary: inside each slice the net's cross-section is one 2D
region; its edges, extruded through the slice, are the side walls, and where the region grows or
shrinks from one slice to the next are the horizontal faces (no faces inside the conductor where
a via meets a metal). A layer may also be a plate - an infinitely thin sheet, as FastCap models
them - e.g. the source / drain node. The substrate is a plate under everything.

Dielectrics are horizontal layers: a dielectric constant up to the first interface, another above
it, ... (FastCap dielectric-interface panels, holed where conductors cross).

    conductors = {"A": [(Region, z0, z1), ...], ...}         (z in um; z0 == z1: a plate)
    names, matrix, panels = capacitance_matrix(conductors, dbu, k, workdir, [(z, k above)], window)
"""
import math
import re
import subprocess
from pathlib import Path

import klayout.db as kdb


def _rects(region):
    """Trapezoids / rectangles / triangles of a region, as lists of (x, y) points in dbu."""
    return [[(p.x, p.y) for p in poly.each_point_hull()]
            for poly in region.decompose_trapezoids_to_region().each()]


def _split(a, b, n):
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]


class Panels:
    """Collects the panels of one conductor (coordinates in um)."""

    def __init__(self, dbu, max_edge):
        self.dbu = dbu
        self.max_edge = max_edge        # um: longer panel edges are split (FasterCap refines further)
        self.quads, self.tris = [], []

    def horizontal(self, region, z):
        d = self.dbu
        for pts in _rects(region):
            if len(pts) == 4 and pts[0][0] == pts[1][0] and pts[1][1] == pts[2][1] and pts[2][0] == pts[3][0]:
                xs = sorted({p[0] for p in pts})
                ys = sorted({p[1] for p in pts})
                x0, x1, y0, y1 = xs[0] * d, xs[-1] * d, ys[0] * d, ys[-1] * d
                nx = max(1, math.ceil((x1 - x0) / self.max_edge))
                ny = max(1, math.ceil((y1 - y0) / self.max_edge))
                for i in range(nx):
                    for j in range(ny):
                        a, b = x0 + (x1 - x0) * i / nx, x0 + (x1 - x0) * (i + 1) / nx
                        c, e = y0 + (y1 - y0) * j / ny, y0 + (y1 - y0) * (j + 1) / ny
                        self.quads.append(((a, c, z), (b, c, z), (b, e, z), (a, e, z)))
            elif len(pts) == 4:
                self.quads.append(tuple((x * d, y * d, z) for x, y in pts))
            elif len(pts) == 3:
                self.tris.append(tuple((x * d, y * d, z) for x, y in pts))
            else:
                p = [(x * d, y * d, z) for x, y in pts]
                for i in range(1, len(p) - 1):
                    self.tris.append((p[0], p[i], p[i + 1]))

    def walls(self, region, z0, z1):
        d = self.dbu
        for poly in region.each():
            loops = [list(poly.each_point_hull())] + [list(poly.each_point_hole(h)) for h in range(poly.holes())]
            for loop in loops:
                for i in range(len(loop)):
                    a, b = loop[i], loop[(i + 1) % len(loop)]
                    a, b = (a.x * d, a.y * d), (b.x * d, b.y * d)
                    n = max(1, math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / self.max_edge))
                    pts = _split(a, b, n)
                    for p, q in zip(pts, pts[1:]):
                        self.quads.append(((p[0], p[1], z0), (q[0], q[1], z0), (q[0], q[1], z1), (p[0], p[1], z1)))

    def count(self):
        return len(self.quads) + len(self.tris)


def conductor_panels(pieces, dbu, max_edge, cuts=()):
    """The surface of one conductor from its (Region, z0, z1) pieces; walls are also split at the
    heights in `cuts` (dielectric interfaces). Returns (Panels, {cut z: cross-section there})."""
    solids = [(r, z0, z1) for r, z0, z1 in pieces if z1 > z0 and not r.is_empty()]
    plates = [(r, z0) for r, z0, z1 in pieces if z1 <= z0 and not r.is_empty()]
    pan = Panels(dbu, max_edge)
    zs = {z for _, z0, z1 in solids for z in (z0, z1)}
    zs |= {z for z in cuts if any(z0 < z < z1 for _, z0, z1 in solids)}
    zs = sorted(zs)

    def cross(lo, hi):                 # the cross-section in the slice lo..hi
        r = kdb.Region()
        for reg, z0, z1 in solids:
            if z0 <= lo + 1e-9 and z1 >= hi - 1e-9:
                r += reg
        return r.merged()

    slices = [cross(lo, hi) for lo, hi in zip(zs, zs[1:])]
    for i, (lo, hi) in enumerate(zip(zs, zs[1:])):
        if not slices[i].is_empty():
            pan.walls(slices[i], lo, hi)
    for i, z in enumerate(zs):
        below = slices[i - 1] if i > 0 else kdb.Region()
        above = slices[i] if i < len(slices) else kdb.Region()
        face = (below ^ above).merged()
        if not face.is_empty():
            pan.horizontal(face, z)
    for reg, z in plates:
        covered = kdb.Region()
        for j, (lo, hi) in enumerate(zip(zs, zs[1:])):
            if lo - 1e-9 <= z <= hi + 1e-9:          # a solid touching or crossing the plate
                covered += slices[j]
        sheet = (reg.merged() - covered).merged()
        if not sheet.is_empty():
            pan.horizontal(sheet, z)
    sections = {}
    for z in cuts:
        sections[z] = kdb.Region()
        for j, (lo, hi) in enumerate(zip(zs, zs[1:])):
            if lo < z < hi:
                sections[z] = slices[j]
    return pan, sections


def _fmt(kind, tag, pts):
    return f"{kind} {tag} " + " ".join(f"{c:.7g}" for p in pts for c in p)


def write_fastcap(conductors, dbu, workdir, k, interfaces=(), window=None, max_edge=0.03, iface_edge=0.06):
    """FastCap-format input. `k`: the dielectric constant below the first interface;
    `interfaces`: [(z, k above)] in ascending z - planar dielectric interfaces across `window` (a
    Box, dbu), holed where conductors cross them. Conductors are named c0, c1 ...; each one's
    panels go to the file of the dielectric around them (merged across files by FastCap's "+").
    Returns (list file, [names], panel count)."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    names = list(conductors)
    cuts = [z for z, _ in interfaces]
    perms = [k] + [kk for _, kk in interfaces]
    files = [[f"0 OpenLayout PEX conductors, k={kk:g}"] for kk in perms]
    holes = {z: kdb.Region() for z in cuts}
    total = 0

    def region_of(pts):
        zc = sum(p[2] for p in pts) / len(pts)
        return sum(1 for z in cuts if zc > z)

    for i, name in enumerate(names):
        pan, sections = conductor_panels(conductors[name], dbu, max_edge, cuts)
        for z, r in sections.items():
            holes[z] += r
        total += pan.count()
        tag = f"c{i}"
        for q in pan.quads:
            files[region_of(q)].append(_fmt("Q", tag, q))
        for t in pan.tris:
            files[region_of(t)].append(_fmt("T", tag, t))
    lst = []
    used = [j for j, f in enumerate(files) if len(f) > 1]
    for n, j in enumerate(used):
        (workdir / f"cond{j}.qui").write_text("\n".join(files[j]) + "\n")
        lst.append(f"C cond{j}.qui {perms[j]:g} 0 0 0" + (" +" if n < len(used) - 1 else ""))
    for j, z in enumerate(cuts):
        plane = (kdb.Region(window) - holes[z].merged()).merged()
        pan = Panels(dbu, iface_edge)
        pan.horizontal(plane, z)
        total += pan.count()
        lines = [f"0 interface z={z:g}"] + [_fmt("Q", "d", q) for q in pan.quads] + [_fmt("T", "d", t) for t in pan.tris]
        (workdir / f"iface{j}.qui").write_text("\n".join(lines) + "\n")
        c = window.center()
        # outer permittivity first, with the reference point on its side (above the plane)
        lst.append(f"D iface{j}.qui {perms[j + 1]:g} {perms[j]:g} 0 0 0 {c.x * dbu:.6g} {c.y * dbu:.6g} {z + 1:.6g}")
    (workdir / "list.lst").write_text("\n".join(lst) + "\n")
    return workdir / "list.lst", names, total


def parse_matrix(log_text):
    """The last capacitance matrix FasterCap printed: (conductor tags, rows)."""
    blocks = log_text.split("Capacitance matrix is:")
    if len(blocks) < 2:
        raise RuntimeError("FasterCap printed no capacitance matrix")
    block = blocks[-1].splitlines()
    m = re.match(r"\s*Dimension (\d+) x (\d+)", block[1])
    n = int(m.group(1))
    tags, rows = [], []
    for line in block[2:2 + n]:
        t = line.split()
        tags.append(t[0])
        rows.append([float(v) for v in t[1:]])
    return tags, rows


def capacitance_matrix(conductors, dbu, k, workdir, interfaces=(), window=None, max_edge=0.03, accuracy=0.05):
    """Maxwell capacitance matrix (F) between the conductors, by FasterCap: (names, matrix, panels)."""
    lst, names, npanels = write_fastcap(conductors, dbu, workdir, k, interfaces, window, max_edge)
    argv = ["FasterCap", "-b", f"-a{accuracy}", "-d0.5", "-m0.5", "-f2", "-ap", lst.name]
    res = subprocess.run(argv, cwd=workdir, capture_output=True, text=True)
    (Path(workdir) / "fastercap.log").write_text(res.stdout)
    if res.returncode != 0 or "Capacitance matrix is:" not in res.stdout:
        raise RuntimeError(f"FasterCap failed:\n{res.stdout[-800:]}{res.stderr[-400:]}")
    tags, rows = parse_matrix(res.stdout)
    # FasterCap names the conductors g<n>_<name>; ours are c<index>; coordinates are in um
    order = [int(re.search(r"c(\d+)$", t).group(1)) for t in tags]
    mat = [[0.0] * len(names) for _ in names]
    for a, ia in enumerate(order):
        for b, ib in enumerate(order):
            mat[ia][ib] = rows[a][b] * 1e-6
    return names, mat, npanels
