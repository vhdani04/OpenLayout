"""Chaining (abutment) of OpenLayout FinFET PCells.

Two transistors chain when they share a source/drain column: the outer column of one lies on the
outer column of the other (the devices overlap by two gate pitches). Chained sides drop their dummy
gate and run the diffusion on (PCell parameters abut_left / abut_right).

- update(): after a move, a moved standard-cell-row transistor lands on the 54 nm gate grid with its
  origin on the nearest half-row line (a multiple of 135 nm): the row itself, a row stacked above
  or below (e.g. the nMOS row on top of an N/P/N cell), or - flipped top to bottom - the rail
  between two rows. Its fins then sit on the fin grid. A standalone transistor dropped into the
  cell's standard-cell frame becomes a row transistor first, in the row where it was dropped (its
  fins then sit on the frame's fins whatever its fin count); dropped elsewhere it lands on the gate
  grid with its fins on the 27 nm fin grid. A moved transistor
  dropped next to a compatible one (same type, row, VT
  and fin count; up to two gate pitches apart, or overlapping by up to one) snaps into abutment -
  if the schematic link knows the nets, only when the touching diffusions are on the same net,
  flipping the moved device if that makes them match. Every transistor's abut flags are then set
  from its neighbours, so moving one away restores its dummy gates.
- chain(): packs the given transistors into chains left to right (per row), each flipped as needed
  so that touching diffusions share a net; one whose nets match neither way stays where it is and
  starts the next chain.

Devices take part unrotated, mirrored left-right, flipped top to bottom, or both (R0, M90, M0, R180);
only devices of the same vertical orientation chain.
"""
import pya

from .connectivity import instance_name
from .pcells import CELL_HEIGHT, CPP, FIN_PITCH, LIBRARY, ROW_MAX_FINS

SNAP_GAP = 2 * CPP     # dropped this far apart (both dummy gates still there) it still chains
SNAP_OVERLAP = CPP     # or overlapping the neighbour by up to one more gate pitch
ROW_LINE = CELL_HEIGHT // 2   # nm: row transistors' origins snap to multiples of this (5 fin pitches)
R0, R180, M0, M90 = 0, 2, 4, 6  # Trans rotation codes: none, both, flipped top to bottom, left-right
ROT = {(False, False): R0, (True, False): M90, (False, True): M0, (True, True): R180}  # (lr, tb)


class Device:
    def __init__(self, inst, conn):
        self.inst = inst
        self.params = inst.pcell_parameters_by_name()
        self.kind = inst.pcell_declaration().name()
        self.nf = int(self.params.get("nf", 1))
        t = inst.dcplx_trans
        self.mirrored = inst.trans.rot in (M90, R180)    # left-right: the columns run leftwards
        self.flipped = inst.trans.rot in (M0, R180)      # top to bottom
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
        return (self.kind, p.get("vt"), int(p.get("nfin", 1)), bool(p.get("row")), self.flipped, self.y0)

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
        """mirror left-right in place (the same columns, ends swapped; top / bottom kept)"""
        span = self.left
        if self.mirrored:   # columns at x0 + 54 (j+1), the leftmost (j = 0) on span
            x0 = span - CPP
        else:               # columns at x0 - 54 (j+1), the leftmost (j = nf) on span
            x0 = span + CPP * (self.nf + 1)
        dbu = self.inst.cell.layout().dbu
        self.mirrored = not self.mirrored
        code = ROT[(self.mirrored, self.flipped)]          # 0-3: rotation, 4-7: mirrored, then rotated
        self.inst.trans = pya.Trans(code % 4, code >= 4, round(x0 / 1000 / dbu), round(self.y0 / 1000 / dbu))
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
    return inst.trans.rot in (R0, M90, M0, R180) and not inst.is_complex()


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


def _standalone_snap(dev, frame, messages):
    """A standalone (non-row) transistor: dropped into the standard-cell frame (frame: its DBox, or
    None) it becomes a row transistor in the row where it was dropped (_row_snap then puts it on
    the row line); elsewhere its origin snaps to the gate grid and the 27 nm fin grid, so its fins
    line up with any fin grid drawn on the same origin."""
    if dev.params.get("row"):
        return
    centre = dev.inst.dbbox().center()
    margin = ROW_LINE / 1000
    if frame is not None and frame.left <= centre.x <= frame.right and frame.bottom - margin <= centre.y \
            <= frame.top + margin:
        nfin = int(dev.params.get("nfin", 1))
        dev.inst.change_pcell_parameters({"row": True})
        dev.params = dev.inst.pcell_parameters_by_name()
        if centre.y < frame.bottom + CELL_HEIGHT / 1000:    # the cell's (first) row: onto it
            dy = round(frame.bottom * 1000, 3) + (CELL_HEIGHT if dev.flipped else 0) - dev.y0  # origin: row edge
        else:   # a row stacked above (an N/P/N cell's top nMOS row): its diffusion where it was dropped
            dy = round((centre.y - dev.inst.dbbox().center().y) * 1000, 3)
        dev.inst.transform(pya.DTrans(0, dy / 1000))
        dev.y0 += dy
        note = f" (drawn with {ROW_MAX_FINS} fins: a 7.5-track row has no room for {nfin})" if nfin > ROW_MAX_FINS else ""
        messages.append(f"{dev.name}: now a standard-cell row transistor{note}")
        return
    dx = round(dev.x0 / CPP) * CPP - dev.x0
    dy = round(dev.y0 / FIN_PITCH) * FIN_PITCH - dev.y0
    if dx or dy:
        dev.inst.transform(pya.DTrans(dx / 1000, dy / 1000))
        dev.x0 += dx
        dev.y0 += dy


def _row_snap(dev):
    """A row transistor lands on the gate grid, its origin on the nearest half-row line: a row's
    origin (y = 0, 270 nm, ...), the top half of a row (an N/P/N cell's upper nMOS row), or - flipped
    top to bottom - a rail. All are fin-grid multiples, so the fins line up with the frame's."""
    if not dev.params.get("row"):
        return
    dx = round(dev.x0 / CPP) * CPP - dev.x0      # columns at x0 +/- 54 (j+1): on the grid with x0
    dy = round(dev.y0 / ROW_LINE) * ROW_LINE - dev.y0
    if dx or dy:
        dev.inst.transform(pya.DTrans(dx / 1000, dy / 1000))
        dev.x0 += dx
        dev.y0 += dy


def update(cell, moved=(), conn=None, frame=None):
    """Snap moved transistors onto their row and into chains, and refresh all abut flags. frame:
    the DBox of the cell's standard-cell frame, if it has one. Returns messages."""
    messages = []
    devs = devices(cell, conn)
    moved_devs = [d for d in devs if any(d.inst == m for m in moved)]
    for d in moved_devs:
        _standalone_snap(d, frame, messages)
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
