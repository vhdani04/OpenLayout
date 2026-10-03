"""Virtuoso-style path tool for KLayout (key P).

- Start on the edge of an existing shape on the current layer: the path takes that edge's length
  as its width, starts flush at the edge's midpoint and leaves it perpendicularly - so it continues
  the wire you clicked. Anywhere else the path uses the layer's minimum width.
- Segments are horizontal or vertical only.
- Click to add points; double-click or Enter to finish; Backspace removes the last point; Esc
  cancels.
"""
import os
from pathlib import Path

import pya

from .asap7 import LAYER_NAME, MIN_WIDTH

TOOL_NAME = "openlayout_path"  # KLayout cuts menu names at "::"
PICK_PIXELS = 6


def _segment_distance(p: pya.DPoint, e: pya.DEdge) -> float:
    dx, dy = e.p2.x - e.p1.x, e.p2.y - e.p1.y
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((p.x - e.p1.x) * dx + (p.y - e.p1.y) * dy) / n))
    cx, cy = e.p1.x + t * dx, e.p1.y + t * dy
    return ((p.x - cx) ** 2 + (p.y - cy) ** 2) ** 0.5


class PathTool(pya.Plugin):
    def __init__(self, view):
        super().__init__()
        self._view = view
        self.reset()

    # ---- state ------------------------------------------------------------------------------
    def reset(self):
        self.points = []
        self.width = None
        self.bgn_ext = 0.0
        self.axis = None          # forced direction of the first segment ("h"/"v") when started on an edge
        self.preview = None
        self.edge_marker = None

    def activated(self):
        self.reset()
        self.status("Path: click to start (click an edge to continue that wire at its width)")

    def deactivated(self):
        self.reset()

    def status(self, text):
        mw = pya.Application.instance().main_window()
        if mw is not None:
            mw.message(text, 6000)

    # ---- helpers ----------------------------------------------------------------------------
    def target(self):
        """(cellview, cell, layer index, layer properties) of the current drawing layer."""
        view = self._view
        cur = view.current_layer
        if cur.is_null() or cur.at_end() or cur.current().has_children():
            return None
        lp = cur.current()
        cv = view.cellview(lp.cellview() if lp.cellview() >= 0 else 0)
        if not cv.is_valid():
            return None
        layout = cv.layout()
        li = layout.layer(lp.source_layer, lp.source_datatype)
        return cv, cv.cell, li, lp

    def default_width(self, lp) -> float:
        return MIN_WIDTH.get(LAYER_NAME.get(lp.source_layer, ""), 18) / 1000.0

    def pick_edge(self, p: pya.DPoint):
        """Closest axis-parallel edge of a shape on the current layer within a few pixels."""
        t = self.target()
        if t is None:
            return None
        cv, cell, li, _ = t
        view = self._view
        tol = PICK_PIXELS * view.box().width() / max(1, view.viewport_width())
        dbu = cv.layout().dbu
        search = pya.DBox(p.x - tol, p.y - tol, p.x + tol, p.y + tol)
        best, best_d = None, tol
        it = cell.begin_shapes_rec_touching(li, search)
        while not it.at_end():
            shape = it.shape()
            if shape.is_box() or shape.is_polygon() or shape.is_path():
                poly = shape.polygon.transformed(it.trans())
                for e in poly.each_edge():
                    de = e.to_dtype(dbu)
                    if de.dx() != 0 and de.dy() != 0:
                        continue
                    d = _segment_distance(p, de)
                    if d < best_d:
                        best, best_d = de, d
            it.next()
        return best

    def snapped(self, p: pya.DPoint) -> pya.DPoint:
        last = self.points[-1] if self.points else p
        try:
            return self.snap2(p, last, True, pya.Plugin.AC_Ortho, True)
        except Exception:
            return p

    def constrain(self, p: pya.DPoint) -> pya.DPoint:
        """Next vertex: horizontal or vertical from the last point."""
        last = self.points[-1]
        axis = self.axis if len(self.points) == 1 and self.axis else (
            "h" if abs(p.x - last.x) >= abs(p.y - last.y) else "v")
        return pya.DPoint(p.x, last.y) if axis == "h" else pya.DPoint(last.x, p.y)

    def make_path(self, pts) -> pya.DPath:
        return pya.DPath(pts, self.width, self.bgn_ext, self.width / 2)

    def show_preview(self, pts):
        if self.preview is None:
            self.preview = pya.Marker(self._view)
            self.preview.color = 0xE8B04B
            self.preview.frame_color = 0xE8B04B
            self.preview.dither_pattern = 1
            self.preview.line_width = 1
        self.preview.set(self.make_path(pts).polygon())

    def show_edge(self, edge):
        if edge is None:
            self.edge_marker = None
            return
        if self.edge_marker is None:
            self.edge_marker = pya.Marker(self._view)
            self.edge_marker.color = 0x4FA3FF
            self.edge_marker.line_width = 3
        self.edge_marker.set(edge)

    # ---- events -----------------------------------------------------------------------------
    def mouse_moved_event(self, p, buttons, prio):
        if not prio:
            return False
        if not self.points:
            self.show_edge(self.pick_edge(p))
            return False
        nxt = self.constrain(self.snapped(p))
        self.show_preview(self.points + [nxt])
        return True

    def mouse_click_event(self, p, buttons, prio):
        if not prio or not (buttons & pya.ButtonState.LeftButton):
            return False
        t = self.target()
        if t is None:
            self.status("Path: select a drawing layer in the LSW first")
            return True
        if not self.points:
            edge = self.pick_edge(p)
            if edge is not None:
                self.width = edge.length()
                self.bgn_ext = 0.0
                self.axis = "v" if edge.dy() == 0 else "h"
                self.points = [pya.DPoint((edge.p1.x + edge.p2.x) / 2, (edge.p1.y + edge.p2.y) / 2)]
                self.status(f"Path: continuing edge, width {self.width * 1000:.0f} nm")
            else:
                self.width = self.default_width(t[3])
                self.bgn_ext = self.width / 2
                self.axis = None
                self.points = [self.snapped(p)]
                self.status(f"Path: width {self.width * 1000:.0f} nm (double-click or Enter to finish)")
            self.show_edge(None)
            return True
        nxt = self.constrain(self.snapped(p))
        if nxt != self.points[-1]:
            self.points.append(nxt)
        return True

    def mouse_double_click_event(self, p, buttons, prio):
        if prio and self.points:
            self.finish()
            return True
        return False

    def key_event(self, key, buttons):
        if not self.points:
            return False
        if key in (pya.KeyCode.Return, pya.KeyCode.Enter):
            self.finish()
        elif key == pya.KeyCode.Escape:
            self.reset()
            self.status("Path cancelled")
        elif key == pya.KeyCode.Backspace:
            self.points.pop()
            if self.points:
                self.show_preview(self.points)
            else:
                self.reset()
        else:
            return False
        return True

    def finish(self):
        t = self.target()
        pts = [q for i, q in enumerate(self.points) if i == 0 or q != self.points[i - 1]]
        if t is not None and len(pts) >= 2:
            cv, cell, li, _ = t
            path = self.make_path(pts)
            try:
                path = path.transformed(cv.context_dtrans().inverted())
            except Exception:
                pass
            self._view.transaction("Create path")
            try:
                cell.shapes(li).insert(path)
            finally:
                self._view.commit()
            self.status(f"Path created ({len(pts) - 1} segment(s), {self.width * 1000:.0f} nm)")
        self.reset()


class PathToolFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = True
        icon = Path(os.environ.get("OPENLAYOUT_HOME", Path.home() / "openlayout/flow")) / "share/icons/tool_path.svg"
        self.register(-900, TOOL_NAME, "Path", str(icon))

    def create_plugin(self, manager, root, view):
        return PathTool(view)
