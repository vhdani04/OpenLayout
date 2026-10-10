"""What a click in the layout takes: selectability and click-again cycling.

- Locked layers (LSW: right-click a layer > Lock) and hidden layers are never taken by a click;
  with *Instances selectable* off (LSW) neither are cell and PCell instances, so the shapes under a
  transistor - a GCUT, a fin, a rail - can be clicked directly.
- Clicking the same spot again takes the next object under the mouse, from the top down: shapes on
  the upper layers first (metal > vias > LIG > LISD > gate, then any other layer; the smallest
  first), then transistors and other instances, then the standard-cell frame's shapes (its rails,
  GCUT, fins, boundary).
"""
import pya

from .asap7 import LAYERS, PIN
from .connectivity import PROP

FRAME_TAG = "ol:frame"      # property 1 of the standard-cell frame's shapes
CATCH_PIXELS = 4            # a shape is taken this close to the mouse (thin fins, labels), like KLayout

locked = set()              # (layer, datatype) of the locked layers
instances = True            # instances can be clicked

# what lies on top wins: metal over vias over contacts over gate, then anything else drawn
_STACK = [f"m{k}" for k in range(9, 0, -1)] + [f"v{k}" for k in range(9, -1, -1)] + ["lig", "lisd", "gate"]
RANK = {LAYERS[n]: len(_STACK) - i for i, n in enumerate(_STACK)}


def is_locked(layout, layer_index):
    info = layout.get_info(layer_index)
    return (info.layer, info.datatype) in locked


def _is_frame_inst(inst):
    if not inst.is_pcell():
        return False
    decl = inst.pcell_declaration()
    return decl is not None and decl.name() == "stdcell"


def is_frame(o):
    """an ObjectInstPath of a frame shape (or an old frame instance)"""
    if o.is_cell_inst():
        return _is_frame_inst(o.inst())
    return o.shape.property(PROP) == FRAME_TAG


def same(a, b):
    """whether two ObjectInstPaths are the same object (KLayout's own paths and these may differ in
    how they spell an instance)"""
    if a.is_cell_inst() != b.is_cell_inst():
        return False
    if a.is_cell_inst():
        ia, ib = a.inst(), b.inst()
        return ia.cell_index == ib.cell_index and ia.dcplx_trans == ib.dcplx_trans
    return a.layer == b.layer and a.shape == b.shape


def allowed(view, o):
    """whether a click may take this ObjectInstPath (its layer unlocked; instances switched on)"""
    if o.is_cell_inst():
        return instances
    return not is_locked(view.cellview(o.cv_index).layout(), o.layer)


def visible_layers(view, cv):
    out = set()
    it = view.begin_layers()
    while not it.at_end():
        lp = it.current()
        if lp.cellview() == cv.index() and lp.visible and lp.layer_index() >= 0:
            out.add(lp.layer_index())
        it.next()
    return out


def candidates(view, p, frame=True):
    """[ObjectInstPath] of what a click at p (micrometers) may take, from the top down (see the
    module docstring); frame=False leaves out the frame's shapes."""
    cv = view.active_cellview()
    if not cv.is_valid() or cv.cell is None:
        return []
    cell, layout = cv.cell, cv.layout()
    q = cv.context_dtrans().inverted() * p
    point = pya.DBox(q, q).to_itype(layout.dbu)
    tol = CATCH_PIXELS / view.viewport_trans().mag
    near = pya.DBox(q.x - tol, q.y - tol, q.x + tol, q.y + tol).to_itype(layout.dbu)
    near_region = pya.Region(near)
    found = []          # (sort key, kind, payload)
    for li in visible_layers(view, cv):
        if is_locked(layout, li):
            continue
        info = layout.get_info(li)
        rank = RANK.get(info.layer, 0) if info.datatype in (0, PIN) else 0
        for s in cell.shapes(li).each_touching(near):
            # the shape itself near the mouse, not just its bounding box (an L-shaped wire)
            if not s.is_text() and not s.is_box() and \
                    pya.Region(s.polygon).interacting(near_region).is_empty():
                continue
            in_frame = s.property(PROP) == FRAME_TAG
            if in_frame and not frame:
                continue
            # a label after the shapes of its layer (a pin label right after its pin)
            found.append(((2 if in_frame else 0, -rank, s.is_text(), s.dbbox().area()), "shape", (s, li)))
    if instances:
        for inst in cell.each_overlapping_inst(point):
            in_frame = _is_frame_inst(inst)
            if in_frame and not frame:
                continue
            found.append(((3 if in_frame else 1, 0, False, inst.dbbox().area()), "inst", inst))
    found.sort(key=lambda f: f[0])
    out = []
    for _key, kind, payload in found:
        oip = pya.ObjectInstPath()
        oip.top = cell.cell_index()
        oip.cv_index = cv.index()
        if kind == "shape":
            oip.shape, oip.layer = payload
        else:
            oip.append_path(pya.InstElement(payload))
        out.append(oip)
    return out


def describe(view, o):
    """a short name for an object in the status bar"""
    from .connectivity import instance_name
    if o.is_cell_inst():
        inst = o.inst()
        name = instance_name(inst)
        return f"{name} ({inst.cell.basic_name()})" if name else inst.cell.basic_name()
    layout = view.cellview(o.cv_index).layout()
    info = layout.get_info(o.layer)
    names = {v: k for k, v in LAYERS.items()}
    layer = names.get(info.layer, str(info.layer)).upper()
    purpose = {0: "", PIN: " pin", 2: " label"}.get(info.datatype, f"/{info.datatype}")
    what = "label" if o.shape.is_text() else "shape"
    return f"{layer}{purpose} {what}" + (" (frame)" if is_frame(o) else "")
