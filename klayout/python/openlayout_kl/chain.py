"""Chaining (abutment) of OpenLayout FinFET PCells.

Two transistors chain when they share a source/drain column: the outer column of one lies on the
outer column of the other (the devices overlap by two gate pitches). Chained sides drop their dummy
gate and run the diffusion on (PCell parameters abut_left / abut_right).

- update(): after a move, a moved standard-cell-row transistor lands on the 54 nm gate grid and,
  dropped onto the cell (within half a cell of y = 0), onto the row itself. A moved transistor
  dropped next to a compatible one (same type, row, VT
  and fin count; up to two gate pitches apart, or overlapping by up to one) snaps into abutment -
  if the schematic link knows the nets, only when the touching diffusions are on the same net,
  flipping the moved device if that makes them match. Every transistor's abut flags are then set
  from its neighbours, so moving one away restores its dummy gates.
- chain(): packs the given transistors into chains left to right (per row), each flipped as needed
  so that touching diffusions share a net; one whose nets match neither way stays where it is and
  starts the next chain.

Only unrotated devices take part (R0, or mirrored left-right: M90).
"""
import pya

from .connectivity import instance_name
from .pcells import CPP, LIBRARY

SNAP_GAP = 2 * CPP     # dropped this far apart (both dummy gates still there) it still chains
SNAP_OVERLAP = CPP     # or overlapping the neighbour by up to one more gate pitch
ROW_CATCH = 135        # nm: a row transistor dropped this close to y = 0 goes onto the row
R0, M90 = 0, 6         # Trans rotation codes: none, mirrored left-right


class Device:
    def __init__(self, inst, conn):
        self.inst = inst
        self.params = inst.pcell_parameters_by_name()
        self.kind = inst.pcell_declaration().name()
        self.nf = int(self.params.get("nf", 1))
        t = inst.dcplx_trans
        self.mirrored = inst.trans.rot == M90
        self.x0 = round(t.disp.x * 1000, 3)       # nm
        self.y0 = round(t.disp.y * 1000, 3)
        name = instance_name(inst)
        spec = (conn or {}).get("instances", {}).get(name) if name else None
        self.name = name or self.kind
        self.nets = spec.get("terminals", {}) if spec else {}

    @property
    def width(self):
        return CPP * (self.nf + 2)

    def row_key(self):
        p = self.params
        return (self.kind, p.get("vt"), int(p.get("nfin", 1)), bool(p.get("row")), self.y0)

    def column_x(self, j):
        """global x (nm) of source/drain column j"""
        local = CPP * (j + 1)
        return self.x0 - local if self.mirrored else self.x0 + local

    @property
    def left(self):
        return min(self.column_x(0), self.column_x(self.nf))

    @property
    def right(self):
        return max(self.column_x(0), self.column_x(self.nf))

    def end_column(self, side):
        """local column index at the global 'left' / 'right' end"""
        first_is_left = not self.mirrored
        return 0 if (side == "left") == first_is_left else self.nf

    def net(self, side):
        j = self.end_column(side)
        return self.nets.get("s" if j % 2 == 0 else "d")

    def flipped_net(self, side):
        """net at `side` if the device were mirrored in place"""
        j = self.nf - self.end_column(side)
        return self.nets.get("s" if j % 2 == 0 else "d")

    def move(self, dx):
        if dx:
            self.inst.transform(pya.DTrans(dx / 1000, 0))
            self.x0 += dx

    def flip(self):
        """mirror left-right in place (the same columns, ends swapped)"""
        span = self.left
        if self.mirrored:   # -> R0: columns at x0 + 54 (j+1), the leftmost (j = 0) on span
            x0, rot = span - CPP, R0
        else:               # -> M90: columns at x0 - 54 (j+1), the leftmost (j = nf) on span
            x0, rot = span + CPP * (self.nf + 1), M90
        dbu = self.inst.cell.layout().dbu
        base = pya.Trans.M90 if rot == M90 else pya.Trans.R0
        self.inst.trans = pya.Trans(base, round(x0 / 1000 / dbu), round(self.y0 / 1000 / dbu))
        self.mirrored = rot == M90
        self.x0 = x0


def _is_device(inst):
    if not inst.is_pcell():
        return False
    decl = inst.pcell_declaration()
    if decl is None or decl.name() not in ("nmos", "pmos"):
        return False
    lib = inst.cell.library()
    if lib is not None and lib.name() != LIBRARY:
        return False
    return inst.trans.rot in (R0, M90) and not inst.is_complex()


def devices(cell, conn=None):
    return [Device(i, conn) for i in cell.each_inst() if _is_device(i)]


def _nets_ok(a_net, b_net):
    return a_net is None or b_net is None or a_net == b_net


def _snap(dev, others, messages):
    """Move (and maybe flip) dev into abutment with the nearest compatible neighbour."""
    best = None
    for o in others:
        if o.inst == dev.inst or o.row_key() != dev.row_key():
            continue
        for side, shift in (("right", o.left - dev.right), ("left", o.right - dev.left)):
            # side: dev's side facing o; shift: dev's move to make the columns meet
            gap = shift if side == "right" else -shift
            if -SNAP_OVERLAP <= gap <= SNAP_GAP and (best is None or abs(shift) < abs(best[2])):
                best = (o, side, shift)
    if best is None:
        return
    o, side, shift = best
    other_side = "left" if side == "right" else "right"
    if not _nets_ok(dev.net(side), o.net(other_side)):
        if _nets_ok(dev.flipped_net(side), o.net(other_side)):
            dev.flip()
        else:
            messages.append(f"{dev.name} not chained to {o.name}: {dev.net(side)} vs {o.net(other_side)}")
            return
    dev.move(shift)


def _set_flags(devs):
    """abut flags of every device from its neighbours (local left/right: mirrored devices swap)."""
    for d in devs:
        has = {"left": False, "right": False}
        for o in devs:
            if o.inst == d.inst or o.row_key() != d.row_key():
                continue
            if abs(o.right - d.left) < 0.01 and _nets_ok(o.net("right"), d.net("left")):
                has["left"] = True
            if abs(o.left - d.right) < 0.01 and _nets_ok(o.net("left"), d.net("right")):
                has["right"] = True
        if d.mirrored:
            has = {"left": has["right"], "right": has["left"]}
        want = {"abut_left": has["left"], "abut_right": has["right"]}
        if any(bool(d.params.get(k)) != v for k, v in want.items()):
            d.inst.change_pcell_parameters(want)
            d.params.update(want)


def _row_snap(dev):
    """A row transistor lands on the gate grid; dropped onto the cell's row (origin within half a
    cell of y = 0) it goes onto the row exactly."""
    if not dev.params.get("row"):
        return
    dx = round(dev.x0 / CPP) * CPP - dev.x0      # columns at x0 +/- 54 (j+1): on the grid with x0
    dy = -dev.y0 if abs(dev.y0) <= ROW_CATCH else 0
    if dx or dy:
        dev.inst.transform(pya.DTrans(dx / 1000, dy / 1000))
        dev.x0 += dx
        dev.y0 += dy


def update(cell, moved=(), conn=None):
    """Snap moved transistors onto their row and into chains, and refresh all abut flags.
    Returns messages."""
    messages = []
    devs = devices(cell, conn)
    moved_devs = [d for d in devs if any(d.inst == m for m in moved)]
    for d in moved_devs:
        _row_snap(d)
    for d in moved_devs:
        _snap(d, devs, messages)
    _set_flags(devs)
    return messages


def chain(cell, insts, conn=None):
    """Chain the given transistors left to right, per row. Returns messages."""
    messages = []
    devs = devices(cell, conn)
    chosen = [d for d in devs if any(d.inst == i for i in insts)]
    rows = {}
    for d in chosen:
        rows.setdefault(d.row_key(), []).append(d)
    for row in rows.values():
        row.sort(key=lambda d: d.left)
        for prev, d in zip(row, row[1:]):
            if not _nets_ok(d.net("left"), prev.net("right")):
                if _nets_ok(d.flipped_net("left"), prev.net("right")):
                    d.flip()
                else:
                    messages.append(f"{d.name} not chained to {prev.name}: {prev.name} ends on "
                                    f"{prev.net('right')}, {d.name} has {d.net('left')} / {d.flipped_net('left')}")
                    continue
            d.move(prev.right - d.left)
    skipped = [d.name for d in devs if any(d.inst == i for i in insts)
               and len(rows.get(d.row_key(), [])) < 2]
    if skipped:
        messages.append("nothing to chain with in the same row: " + ", ".join(sorted(set(skipped))))
    _set_flags(devs)
    return messages
