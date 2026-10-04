"""Custom standard cells in the open layout view: the cell frame (template) and chaining commands.

- insert_frame(): puts the OpenLayout_ASAP7 `stdcell` frame at the origin of the current cell (or
  resizes the one there) and labels the rails as the VDD / VSS pins. Transistors then go in with
  `row` on, at y = 0 (schematic-driven generation does that by itself once a frame is there).
- chain_selected(): Virtuoso-style chaining of the selected transistors.
- after_move(): called when a move / align is done - snaps moved transistors into chains.
"""
import math

import pya

from . import chain
from .asap7 import LAYERS, PIN
from .connectivity import load_conn
from .pcells import CELL_HEIGHT, CPP, LIBRARY

FRAME = "stdcell"


def _is_frame(inst):
    if not inst.is_pcell():
        return False
    decl = inst.pcell_declaration()
    return decl is not None and decl.name() == FRAME and (inst.cell.library() is None
                                                          or inst.cell.library().name() == LIBRARY)


def find_frame(cell):
    return next((i for i in cell.each_inst() if _is_frame(i)), None)


def is_frame_selection(view):
    """True if the selection is nothing but standard-cell frames."""
    objs = list(view.each_object_selected())
    return bool(objs) and all(o.is_cell_inst() and _is_frame(o.inst()) for o in objs)


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


def insert_frame(view, cpp=None, vt=None):
    """Insert (or resize) the frame of the view's current cell. Returns the frame instance."""
    cv = view.active_cellview()
    cell = cv.cell
    frame = find_frame(cell)
    params = {"cpp": int(cpp or default_width(cell))}
    if vt:
        params["vt"] = vt
    view.transaction("Standard-cell frame")
    try:
        if frame is not None:
            frame.change_pcell_parameters(params)
        else:
            pc = cv.layout().create_cell(FRAME, LIBRARY, params)
            frame = cell.insert(pya.DCellInstArray(pc.cell_index(), pya.DTrans()))
        _rail_pins(cell)
    finally:
        view.commit()
    return frame


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
        messages = chain.update(cell, moved, _conn(view))
    finally:
        view.commit()
    return messages
