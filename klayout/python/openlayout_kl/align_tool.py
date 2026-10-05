"""Align (key A).

Select what should move (or point at it), press A, click an edge of the selection (the reference),
then click a parallel edge of anything else (the target): the selection moves so the two edges line
up - sideways for vertical edges, up/down for horizontal ones - as one undo step. Edges are those of
shapes (also inside instances, e.g. a transistor's diffusion or gate) and of instance outlines; the
edge under the mouse is highlighted. Instance outlines win over the shapes inside them within reach of
the mouse (a transistor is full of fin edges). Esc or a right click cancels.

Not a KLayout mode: while aligning, this service holds the mouse grab, so it sees the clicks first.
"""
import pya

from . import stdcell
from .drag_move import notify_moved

NAME = "openlayout_align"
PICK_PIXELS = 8
REF_COLOR, HOVER_COLOR = 0xE8B04B, 0x4FA3FF
_under_mouse = None   # (tool, point) of the view the mouse was last over


def _segment_distance(p, e):
    dx, dy = e.p2.x - e.p1.x, e.p2.y - e.p1.y
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((p.x - e.p1.x) * dx + (p.y - e.p1.y) * dy) / n))
    return ((p.x - e.p1.x - t * dx) ** 2 + (p.y - e.p1.y - t * dy) ** 2) ** 0.5


def _axis(e):
    """'v' or 'h' for axis-parallel edges, None otherwise"""
    if e.p1.x == e.p2.x and e.p1.y != e.p2.y:
        return "v"
    if e.p1.y == e.p2.y and e.p1.x != e.p2.x:
        return "h"
    return None


def _shape_edges(shape, trans):
    if shape.is_box() or shape.is_polygon() or shape.is_path():
        poly = shape.dpolygon
        if poly is not None:
            return [trans * e for e in poly.each_edge()]
    return []


def _box_edges(box):
    return [pya.DEdge(box.left, box.bottom, box.left, box.top), pya.DEdge(box.right, box.bottom, box.right, box.top),
            pya.DEdge(box.left, box.bottom, box.right, box.bottom), pya.DEdge(box.left, box.top, box.right, box.top)]


def start():
    """The A key."""
    if _under_mouse is None:
        return
    tool, p = _under_mouse
    tool.begin(p)


class AlignTool(pya.Plugin):
    def __init__(self, view):
        super().__init__()
        self._view = view
        self.active = False
        self.ref = None
        self.markers = []
        self.hover_marker = None

    # ---- geometry -------------------------------------------------------------------------------
    def _layers(self, cv_index):
        out = []
        it = self._view.begin_layers()
        while not it.at_end():
            lp = it.current()
            if lp.cellview() == cv_index and lp.visible and not lp.has_children() and lp.layer_index() >= 0:
                out.append(lp.layer_index())
            it.next()
        return out

    def _tolerance(self):
        return PICK_PIXELS / self._view.viewport_trans().mag

    def _cell_edges(self, layout, cell, trans, layers, near, exclude_top=None):
        """(edge, rank) of the shapes (all levels) of cell near `near` (a box in view coordinates),
        mapped with trans (cell -> view): rank 0 for the cell's own shapes, 1 inside instances.
        Top-level instances / shapes in exclude_top are skipped."""
        search = (trans.inverted() * near).to_itype(layout.dbu)   # the iterator searches in DBU
        edges = []
        for li in layers:
            it = pya.RecursiveShapeIterator(layout, cell, li, search)
            while not it.at_end():
                path = it.path()
                if exclude_top is not None:
                    key = path[0].inst() if path else it.shape()
                    if any(type(key) is type(x) and key == x for x in exclude_top):
                        it.next()
                        continue
                edges += [(e, 1 if path else 0) for e in _shape_edges(it.shape(), trans * it.dtrans())]
                it.next()
        return edges

    def _selected(self):
        return [o for o in self._view.each_object_selected() if o.is_cell_inst() or o.shape.dpolygon is not None]

    # Edges come as (edge, rank): rank 0 for objects of the edited cell (instance outlines, shapes),
    # rank 1 for shapes inside instances.
    def selection_edges(self, near):
        cv = self._view.active_cellview()
        layers = self._layers(cv.index())
        edges = []
        for o in self._selected():
            t = o.dtrans()   # for an instance: includes the instance's own transformation
            if o.is_cell_inst():
                inst = o.inst()
                ti = t
                edges += [(e, 0) for e in _box_edges(ti * inst.cell.dbbox())]
                edges += [(e, 1) for e, _ in self._cell_edges(cv.layout(), inst.cell, ti, layers, near)]
            else:
                edges += [(e, 0) for e in _shape_edges(o.shape, t)]
        return edges

    def other_edges(self, near):
        cv = self._view.active_cellview()
        layout, cell = cv.layout(), cv.cell
        ctx = cv.context_dtrans()
        layers = self._layers(cv.index())
        sel = self._selected()
        exclude = [o.inst() if o.is_cell_inst() else o.shape for o in sel]
        edges = self._cell_edges(layout, cell, ctx, layers, near, exclude)
        for inst in cell.each_overlapping_inst(ctx.inverted() * near):
            if not any(type(x) is pya.Instance and inst == x for x in exclude):
                edges += [(e, 0) for e in _box_edges(ctx * inst.dcplx_trans * inst.cell.dbbox())]
        return edges

    def pick(self, p):
        """The edge for the current step nearest to p: (edge, axis) or None."""
        tol = self._tolerance()
        near = pya.DBox(p.x - tol, p.y - tol, p.x + tol, p.y + tol)
        edges = self.selection_edges(near) if self.ref is None else self.other_edges(near)
        want = None if self.ref is None else self.ref[1]
        best, best_key = None, None
        for e, rank in edges:
            ax = _axis(e)
            if ax is None or (want is not None and ax != want):
                continue
            d = _segment_distance(p, e)
            if d <= tol and (best_key is None or (rank, d) < best_key):
                best, best_key = (e, ax), (rank, d)
        return best

    # ---- markers ----------------------------------------------------------------------------------
    def _marker(self, edge, color):
        m = pya.Marker(self._view)
        m.color = color
        m.line_width = 3
        m.set(edge)
        return m

    def show_hover(self, hit):
        if hit is None:
            self.hover_marker = None
        else:
            if self.hover_marker is None:
                self.hover_marker = self._marker(hit[0], HOVER_COLOR)
            self.hover_marker.set(hit[0])

    # ---- flow -------------------------------------------------------------------------------------
    def status(self, text):
        mw = pya.Application.instance().main_window()
        if mw is not None:
            mw.message(text, 10000)

    def begin(self, p):
        view = self._view
        if not view.is_editable():
            return
        if not view.has_object_selection():
            stdcell.pick(view, p)
        if not self._selected():
            self.status("Align: select the objects to align first")
            return
        self.active = True
        self.ref = None
        self.grab_mouse()
        self.status("Align: click the edge of the selection to align")
        self.show_hover(self.pick(p))

    def finish(self):
        self.active = False
        self.ref = None
        self.markers = []
        self.hover_marker = None
        self.ungrab_mouse()

    def cancel(self):
        if self.active:
            self.finish()
            self.status("Align cancelled")

    def align(self, target):
        (re, axis), te = self.ref, target[0]
        d = pya.DVector(te.p1.x - re.p1.x, 0) if axis == "v" else pya.DVector(0, te.p1.y - re.p1.y)
        view = self._view
        objs = list(view.each_object_selected())
        view.transaction("Align")
        try:
            for o in objs:
                if o.is_cell_inst():
                    parent = o.dtrans() * o.inst().dcplx_trans.inverted()   # parent cell -> view
                    o.inst().transform(pya.DTrans(parent.inverted() * d))
                elif o.shape.dpolygon is not None:
                    o.shape.transform(pya.DTrans(o.dtrans().inverted() * d))
        finally:
            view.commit()
        self.finish()
        view.object_selection = objs
        notify_moved(view)
        dist = abs(d.x if axis == "v" else d.y) * 1000
        self.status(f"Aligned: moved {dist:.1f} nm {'sideways' if axis == 'v' else 'up/down'}")

    # ---- events -----------------------------------------------------------------------------------
    def mouse_moved_event(self, p, buttons, prio):
        global _under_mouse
        _under_mouse = (self, p)
        if not (self.active and prio):
            return False
        self.show_hover(self.pick(p))
        return True

    def mouse_click_event(self, p, buttons, prio):
        if not (self.active and prio):
            return False
        if buttons & pya.ButtonState.RightButton:
            self.cancel()
            return True
        if not buttons & pya.ButtonState.LeftButton:
            return True
        hit = self.pick(p)
        if hit is None:
            self.status("Align: no edge here" if self.ref is None else
                        f"Align: click a {'vertical' if self.ref[1] == 'v' else 'horizontal'} edge to align to")
            return True
        if self.ref is None:
            self.ref = hit
            self.markers = [self._marker(hit[0], REF_COLOR)]
            self.hover_marker = None
            self.status("Align: click the edge to align it to")
        else:
            self.align(hit)
        return True

    def mouse_button_pressed_event(self, p, buttons, prio):
        return self.active and prio      # no drags / selection boxes while aligning

    def mouse_button_released_event(self, p, buttons, prio):
        return self.active and prio

    def drag_cancel(self):              # Esc
        self.cancel()

    def deactivated(self):
        self.cancel()


class AlignToolFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = False
        self.register(-1100, NAME, "")

    def create_plugin(self, manager, root, view):
        return AlignTool(view)
