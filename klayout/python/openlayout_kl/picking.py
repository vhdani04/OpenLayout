"""What can be selected in the layout, and what a click takes.

Selectability, as in Virtuoso's LSW:
- object types (the Select window): instances (transistors, cells), vias, shapes, pins, labels,
  the boundary, and the standard-cell frame's shapes (rails, fins, GCUT, implants);
- layers: locked layers (LSW: right-click a layer > Lock; AS / NS) and hidden layers. NS ("only the
  current layer") also makes instances and vias unselectable - they are no layer; AS makes
  everything selectable again.
Whatever is not selectable is left out of clicks, box selections and Select All alike, and the
hover highlight shows only what a click can take.

A click takes the top selectable object under the mouse: shapes on the upper layers first (metal >
vias > LIG > LISD > gate, then any other layer; the smallest first), then transistors, vias and
other instances, then the frame's shapes. Clicking the same spot again takes the next one down.
"""
import pya

from .asap7 import LAYERS, PIN
from .connectivity import PROP

FRAME_TAG = "ol:frame"      # property 1 of the standard-cell frame's shapes
CATCH_PIXELS = 4            # a shape is taken this close to the mouse (thin fins, labels), like KLayout

# object types, in the Select tab's order: key, label
TYPES = [
    ("instance", "Instances (transistors, cells)"),
    ("via", "Vias"),
    ("shape", "Shapes"),
    ("pin", "Pins"),
    ("label", "Labels"),
    ("boundary", "Boundary"),
    ("frame", "Standard-cell frame (rails, fins, GCUT, implants)"),
]
types = {k: True for k, _ in TYPES}     # which types can be selected
locked = set()                          # (layer, datatype) of the locked layers
listeners = []                          # f() called when types or locks change (the LSW, the Select window)


def changed():
    for f in list(listeners):
        try:
            f()
        except Exception as e:
            print(f"OpenLayout: selectability listener failed: {e}")

# what lies on top wins: metal over vias over contacts over gate, then anything else drawn
_STACK = [f"m{k}" for k in range(9, 0, -1)] + [f"v{k}" for k in range(9, -1, -1)] + ["lig", "lisd", "gate"]
RANK = {LAYERS[n]: len(_STACK) - i for i, n in enumerate(_STACK)}
BOUNDARY = LAYERS["boundary"]


def select_all_types():
    """every type and layer selectable (AS)"""
    for k in types:
        types[k] = True
    locked.clear()


def is_locked(layout, layer_index):
    info = layout.get_info(layer_index)
    return (info.layer, info.datatype) in locked


def _pcell_name(inst):
    if not inst.is_pcell():
        return None
    decl = inst.pcell_declaration()
    return decl.name() if decl is not None else None


def inst_type(inst):
    name = _pcell_name(inst)
    return "frame" if name == "stdcell" else "via" if name == "via" else "instance"


def shape_type(layout, layer_index, shape):
    if shape.is_text():
        return "label"
    info = layout.get_info(layer_index)
    if info.layer == BOUNDARY:
        return "boundary"
    if shape.property(PROP) == FRAME_TAG:
        return "frame"
    return "pin" if info.datatype == PIN else "shape"


def object_type(view, o):
    if o.is_cell_inst():
        return inst_type(o.inst())
    return shape_type(view.cellview(o.cv_index).layout(), o.layer, o.shape)


def is_frame(o):
    """an ObjectInstPath of a frame shape (or an old frame instance)"""
    if o.is_cell_inst():
        return inst_type(o.inst()) == "frame"
    return o.shape.property(PROP) == FRAME_TAG


def allowed(view, o):
    """whether this ObjectInstPath can be selected: its type on, its layer unlocked"""
    if not types.get(object_type(view, o), True):
        return False
    return o.is_cell_inst() or not is_locked(view.cellview(o.cv_index).layout(), o.layer)


def same(a, b):
    """whether two ObjectInstPaths are the same object (KLayout's own paths and these may differ in
    how they spell an instance)"""
    if a.is_cell_inst() != b.is_cell_inst():
        return False
    if a.is_cell_inst():
        ia, ib = a.inst(), b.inst()
        return ia.cell_index == ib.cell_index and ia.dcplx_trans == ib.dcplx_trans
    return a.layer == b.layer and a.shape == b.shape


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
            kind = shape_type(layout, li, s)
            in_frame = s.property(PROP) == FRAME_TAG
            if not types[kind] or (in_frame and not frame):
                continue
            # the shape itself near the mouse, not just its bounding box (an L-shaped wire)
            if not s.is_text() and not s.is_box() and \
                    pya.Region(s.polygon).interacting(near_region).is_empty():
                continue
            # a label after the shapes of its layer (a pin label right after its pin)
            found.append(((2 if in_frame else 0, -rank, s.is_text(), s.dbbox().area()), "shape", (s, li)))
    for inst in cell.each_overlapping_inst(point):
        kind = inst_type(inst)
        if not types[kind] or (kind == "frame" and not frame):
            continue
        found.append(((3 if kind == "frame" else 1, 0, False, inst.dbbox().area()), "inst", inst))
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


class SelectionFilter:
    """Per view: whatever gets selected that cannot be (a box selection, Select All) is dropped, so
    selectability holds everywhere, not only for clicks."""

    def __init__(self, view):
        self.view = view
        self.busy = False
        view.on_selection_changed += self.selection_changed

    def selection_changed(self):
        view = self.view
        if self.busy or view.mode_name() != "select":
            return
        if all(types.values()) and not locked:
            return
        try:
            sel = list(view.each_object_selected())
            keep = [o for o in sel if allowed(view, o)]
            if len(keep) != len(sel):
                self.busy = True
                view.object_selection = keep
        except Exception as e:
            print(f"OpenLayout: selection filter: {type(e).__name__}: {e}")
        finally:
            self.busy = False
