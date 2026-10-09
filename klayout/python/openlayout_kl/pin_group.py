"""A pin and its label move together.

A pin is a shape on a metal's pin purpose; its label is the text on the pin or label purpose of the
same metal that lies on it (Generate Layout's pins: a square with the label at its centre).
Selecting the pin shape selects its label too, so whatever then works on the selection takes the
label along: a drag, `m`, KLayout's Move, the arrow keys, copy, delete, mirror / rotate. A label
selected on its own (clicked) still moves by itself.
"""
import pya

from .asap7 import LABEL, PIN


def labels_of(layout, cell, layer, shape):
    """[(layer index, text shape)] of the labels on pin shape `shape` (on layer index `layer`)."""
    info = layout.get_info(layer)
    if info.datatype != PIN or shape.is_text() or shape.is_null():
        return []
    poly = shape.polygon
    if poly is None:
        return []
    out = []
    for dt in (PIN, LABEL):
        li = layout.find_layer(info.layer, dt)
        if li is None:
            continue
        for s in cell.shapes(li).each_touching(pya.Shapes.STexts, shape.bbox()):
            if poly.inside(pya.Point(s.text.x, s.text.y)):
                out.append((li, s))
    return out


class PinGroup:
    """Per view: a selected pin shape brings its labels into the selection."""

    def __init__(self, view):
        self.view = view
        self.busy = False
        view.on_selection_changed += self.selection_changed

    def selection_changed(self):
        view = self.view
        # Select mode only: KLayout's Partial (stretch) and Move services keep selections of their own
        if self.busy or view.mode_name() != "select":
            return
        try:
            sel = list(view.each_object_selected())
            add = []
            for o in sel:
                if o.is_cell_inst():
                    continue
                layout = view.cellview(o.cv_index).layout()
                for li, s in labels_of(layout, layout.cell(o.cell_index()), o.layer, o.shape):
                    p = o.dup()
                    p.layer = li
                    p.shape = s
                    if not any(p == q for q in sel) and not any(p == q for q in add):
                        add.append(p)
            if add:
                self.busy = True
                view.object_selection = sel + add
        except Exception as e:
            print(f"OpenLayout: pin label selection: {type(e).__name__}: {e}")
        finally:
            self.busy = False
