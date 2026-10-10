"""Custom standard cells in the open layout view: the cell frame (template) and chaining commands.

- draw_frame() / insert_frame(): draws the standard-cell frame (boundary, well/implant split, VT,
  fin rows, M1 + LIG rails, GCUT, edge dummy gates) as plain shapes at the origin of the cell - no
  extra hierarchy level, every shape selectable and editable - and labels the rails as the VDD /
  VSS pins. The shapes carry the property 1 = "ol:frame", so drawing the frame again (another width
  or VT) replaces them; an older frame PCell instance is replaced the same way.
- The frame covers the whole cell, so picking prefers anything else: a click, drag, m or a on a spot
  where a transistor (or another shape) lies takes that, and only empty spots give a frame shape
  (pick()).
- chain_selected(): chaining of the selected transistors.
- after_move(): called when a move / align is done - snaps moved transistors into chains.
"""
import math

import pya

from . import chain, picking
from .asap7 import LAYERS, PIN
from .connectivity import PROP, load_conn
from .pcells import CELL_HEIGHT, CPP, LIBRARY, stdcell_geometry
from .picking import FRAME_TAG     # property 1 of the frame's shapes

FRAME = "stdcell"          # the earlier frame PCell (still converted when found)


def _is_frame(inst):
    if not inst.is_pcell():
        return False
    decl = inst.pcell_declaration()
    return decl is not None and decl.name() == FRAME and (inst.cell.library() is None
                                                          or inst.cell.library().name() == LIBRARY)


def frame_shapes(cell):
    layout = cell.layout()
    out = []
    for li in layout.layer_indexes():
        for s in cell.shapes(li).each():
            if s.property(PROP) == FRAME_TAG:
                out.append(s)
    return out


def has_frame(cell):
    return bool(frame_shapes(cell)) or any(_is_frame(i) for i in cell.each_inst())


def frame_params(cell):
    """{cpp, vt} of the cell's frame, or None"""
    layout = cell.layout()
    for s in frame_shapes(cell):
        if layout.get_info(s.layer) == pya.LayerInfo(LAYERS["boundary"], 0):
            cpp = round(s.dbbox().width() * 1000 / CPP)
            vt = "rvt"
            for name in ("lvt", "slvt"):
                li = layout.find_layer(LAYERS[name], 0)
                if li is not None and any(x.property(PROP) == FRAME_TAG for x in cell.shapes(li).each()):
                    vt = name
            return {"cpp": cpp, "vt": vt}
    for i in cell.each_inst():
        if _is_frame(i):
            p = i.pcell_parameters_by_name()
            return {"cpp": int(p.get("cpp", 3)), "vt": p.get("vt", "rvt")}
    return None


def frame_box(cell):
    """The DBox of the cell's standard-cell frame (its boundary, as drawn - stretched to more rows,
    e.g. an N/P/N cell, it covers them all), or None."""
    layout = cell.layout()
    for s in frame_shapes(cell):
        if layout.get_info(s.layer) == pya.LayerInfo(LAYERS["boundary"], 0):
            return s.dbbox()
    p = frame_params(cell)
    if p is None:
        return None
    return pya.DBox(0, 0, p["cpp"] * CPP / 1000, CELL_HEIGHT / 1000)


def is_frame_object(o):
    """an ObjectInstPath of a frame shape (or an old frame instance)"""
    if o.is_cell_inst():
        return _is_frame(o.inst())
    return o.shape.property(PROP) == FRAME_TAG


def frame_only(view):
    objs = list(view.each_object_selected())
    return bool(objs) and all(is_frame_object(o) for o in objs)


def is_frame_selection(view):
    return frame_only(view)


def default_width(cell):
    """Gate pitches that cover the cell's devices (at least 3)."""
    right = 0.0
    for inst in cell.each_inst():
        if not _is_frame(inst):
            right = max(right, inst.dbbox().right)
    return max(3, math.ceil(round(right * 1000, 3) / CPP))


def _rail_pins(cell):
    """VDD / VSS pin labels on the M1 rails (top level), unless the cell has them already."""
    layout = cell.layout()
    li = layout.layer(LAYERS["m1"], PIN)
    have = {s.text_string for s in cell.shapes(li).each(pya.Shapes.STexts)}
    for name, y in (("VSS", 0.0), ("VDD", CELL_HEIGHT / 1000)):
        if name not in have:
            cell.shapes(li).insert(pya.DText(name, pya.DTrans(0.03, y)))


def draw_frame(cell, cpp, vt="rvt"):
    """Draw (or redraw) the frame as plain shapes in cell, at the origin."""
    layout = cell.layout()
    for s in frame_shapes(cell):
        s.delete()
    for inst in [i for i in cell.each_inst() if _is_frame(i)]:
        inst.delete()
    for name, boxes in stdcell_geometry(int(cpp), vt)["shapes"].items():
        li = layout.layer(LAYERS[name], 0)
        for b in boxes:
            cell.shapes(li).insert(pya.DBox(*(v / 1000 for v in b))).set_property(PROP, FRAME_TAG)
    _rail_pins(cell)


def insert_frame(view, cpp=None, vt=None):
    """Draw (or redraw at another width / VT) the frame of the view's current cell."""
    cv = view.active_cellview()
    cell = cv.cell
    cur = frame_params(cell) or {}
    view.transaction("Standard-cell frame")
    try:
        draw_frame(cell, int(cpp or cur.get("cpp") or default_width(cell)), vt or cur.get("vt", "rvt"))
    finally:
        view.commit()


def pick(view, p, mode=pya.LayoutView.SelectionMode.Replace):
    """Select what is at p (micrometers), preferring anything over the frame and skipping what
    cannot be clicked (locked layers, instances when switched off - picking.py). Returns True if
    something is selected."""
    view.select_from(p, mode)
    if mode != pya.LayoutView.SelectionMode.Replace:
        return view.has_object_selection()
    sel = list(view.each_object_selected())
    if sel and all(picking.allowed(view, o) for o in sel) and not frame_only(view):
        return True
    cands = picking.candidates(view, p)
    view.object_selection = cands[:1]
    return view.has_object_selection()


def pick_non_frame(view, p):
    """ObjectInstPath of what a click at p should take when the frame is under it: the topmost
    selectable non-frame object there (picking.candidates) - or None."""
    cands = picking.candidates(view, p, frame=False)
    return cands[0] if cands else None


def _conn(view):
    cv = view.active_cellview()
    return load_conn(cv.filename()) if cv.filename() else None


def chain_selected(view):
    cv = view.active_cellview()
    insts = [o.inst() for o in view.each_object_selected() if o.is_cell_inst()]
    view.transaction("Chain transistors")
    try:
        messages = chain.chain(cv.cell, insts, _conn(view))
    finally:
        view.commit()
    return messages


def after_move(view):
    """Snap moved transistors into chains (and refresh abut flags) after a move."""
    cv = view.active_cellview()
    if not cv.is_valid() or not view.is_editable():
        return []
    cell = cv.cell
    if not any(chain._is_device(i) for i in cell.each_inst()):
        return []
    moved = [o.inst() for o in view.each_object_selected() if o.is_cell_inst()]
    view.transaction("Chain transistors")
    try:
        messages = chain.update(cell, moved, _conn(view), frame_box(cell))
    finally:
        view.commit()
    return messages


def refresh_chains(view):
    """Refresh every transistor's abut flags (dummy gates) from its neighbours, moving nothing - after
    a mirror or rotation. Runs inside the caller's transaction."""
    cv = view.active_cellview()
    if not cv.is_valid() or not view.is_editable():
        return
    cell = cv.cell
    if any(chain._is_device(i) for i in cell.each_inst()):
        chain.update(cell, (), _conn(view), frame_box(cell))
