"""Virtuoso-style path tool for KLayout (key P).

- Start on the edge of an existing shape on the current layer: the path takes that edge's length
  as its width, starts flush at the edge's midpoint and leaves it perpendicularly - so it continues
  the wire you clicked. Anywhere else the path uses the layer's minimum width.
- The path is drawn along its centre line; its end is flush with the cursor. A click is a corner
  (the corner's centre sits on the click); the last click (double-click or Enter) is the end.
- While drawing, the segment snaps onto the facing edge of the next shape on the same layer as soon
  as the path's end reaches it; clicking while snapped places the path flush against that edge and
  finishes it.
- Alignment guides, as in Virtuoso: when the path's leading edge lines up with a corner or an edge
  centre of a nearby shape on the same layer (within GUIDE_PIXELS of the cursor), the end snaps to
  it and a dashed orange line joins that point to the nearest corner of the leading edge. Lined up
  with the centre of a shape's edge, the next turn runs into that shape centred on it.
- The preview is drawn with the current layer's colors and fill pattern.
- Segments are horizontal or vertical only.
- Click to add points; double-click or Enter to finish; Backspace removes the last point; Esc
  cancels.
"""
import os
from pathlib import Path

import pya

from .asap7 import LAYER_NAME, MIN_WIDTH

TOOL_NAME = "openlayout_path"  # KLayout cuts menu names at "::"
PICK_PIXELS = 6    # how close the start click must be to an edge
SNAP_PIXELS = 12   # gravity of facing edges while drawing
GUIDE_PIXELS = 400  # how far around the cursor shapes are looked at for alignment guides
GUIDE_COLOR = 0xFFA31A


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
        self.axis = None           # forced direction of the first segment ("h"/"v") when started on an edge
        self.snapped_flags = []    # per point: True if it sits on a target edge (path ends flush there)
        self.hover = None          # (point, edge) of the last mouse move while drawing
        self.preview = None
        self.edge_marker = None
        self.guide = None          # DEdge: dashed alignment line from a shape's corner / edge centre
        self.guide_marker = None

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

    def pixels(self, n) -> float:
        view = self._view
        return n * view.box().width() / max(1, view.viewport_width())

    def layer_edges(self, box: pya.DBox):
        """Axis-parallel edges of shapes on the current layer touching `box` (micrometers)."""
        t = self.target()
        if t is None:
            return []
        cv, cell, li, _ = t
        dbu = cv.layout().dbu
        edges = []
        it = cell.begin_shapes_rec_touching(li, box)
        while not it.at_end():
            shape = it.shape()
            if shape.is_box() or shape.is_polygon() or shape.is_path():
                for e in shape.polygon.transformed(it.trans()).each_edge():
                    de = e.to_dtype(dbu)
                    if de.dx() == 0 or de.dy() == 0:
                        edges.append(de)
            it.next()
        return edges

    def pick_edge(self, p: pya.DPoint):
        """Closest axis-parallel edge of a shape on the current layer within a few pixels."""
        tol = self.pixels(PICK_PIXELS)
        best, best_d = None, tol
        for e in self.layer_edges(pya.DBox(p.x - tol, p.y - tol, p.x + tol, p.y + tol)):
            d = _segment_distance(p, e)
            if d < best_d:
                best, best_d = e, d
        return best

    def snap_to_edge(self, cand: pya.DPoint):
        """Snap the current segment onto the facing edge of the next shape it runs into.

        The snap is triggered by the path's leading front (the end plus its half-width extension),
        not the cursor: as soon as the front comes within SNAP_PIXELS of a facing edge - or the
        cursor is pushed up to half a width past it - the segment ends flush on that edge. Facing
        means the shape lies ahead (polygon hulls are clockwise, so the interior is to the right of
        each edge). A horizontal segment snaps to vertical edges its centerline crosses, and vice
        versa; the nearest qualifying edge ahead wins. Returns (point, edge or None)."""
        last = self.points[-1]
        horizontal = cand.y == last.y and cand.x != last.x
        vertical = cand.x == last.x and cand.y != last.y
        if not (horizontal or vertical):
            return cand, None
        tol = self.pixels(SNAP_PIXELS)
        half = self.width / 2
        if horizontal:
            sign = 1 if cand.x > last.x else -1
            reach = sign * (cand.x - last.x)
            lo_u, hi_u = reach - half - tol, reach + half + tol
            xs = sorted((last.x + sign * lo_u, last.x + sign * hi_u))
            box = pya.DBox(xs[0], last.y - half, xs[1], last.y + half)
        else:
            sign = 1 if cand.y > last.y else -1
            reach = sign * (cand.y - last.y)
            lo_u, hi_u = reach - half - tol, reach + half + tol
            ys = sorted((last.y + sign * lo_u, last.y + sign * hi_u))
            box = pya.DBox(last.x - half, ys[0], last.x + half, ys[1])
        best = None
        for e in self.layer_edges(box):
            if horizontal and e.dx() == 0:
                lo, hi = sorted((e.p1.y, e.p2.y))
                facing = (1 if e.dy() > 0 else -1) == sign
                u = sign * (e.p1.x - last.x)
                hit = pya.DPoint(e.p1.x, last.y)
                crosses = lo <= last.y <= hi
            elif vertical and e.dy() == 0:
                lo, hi = sorted((e.p1.x, e.p2.x))
                facing = (-1 if e.dx() > 0 else 1) == sign
                u = sign * (e.p1.y - last.y)
                hit = pya.DPoint(last.x, e.p1.y)
                crosses = lo <= last.x <= hi
            else:
                continue
            # ahead of the start, the end (at the cursor) within reach, not too far past it
            if crosses and facing and u > 0 and reach >= u - tol and reach <= u + half + tol:
                if best is None or u < best[0]:
                    best = (u, hit, e)
        return (best[1], best[2]) if best else (cand, None)

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

    def features(self, box: pya.DBox):
        """Corners and edge centres of the shapes on the current layer touching box."""
        pts = []
        for e in self.layer_edges(box):
            pts.append(e.p1)
            pts.append(pya.DPoint((e.p1.x + e.p2.x) / 2, (e.p1.y + e.p2.y) / 2))
        return pts

    def find_guide(self, cand: pya.DPoint):
        """Alignment of the leading edge (the flush end at cand) with a corner or edge centre of a
        shape beside the path: (end point, DEdge guide or None). Within SNAP_PIXELS the end snaps to
        it; the guide joins the point to the nearest corner of the leading edge."""
        last = self.points[-1]
        horizontal = cand.y == last.y and cand.x != last.x
        vertical = cand.x == last.x and cand.y != last.y
        if not (horizontal or vertical):
            return cand, None
        r = self.pixels(GUIDE_PIXELS)
        tol = self.pixels(SNAP_PIXELS)
        half = self.width / 2
        best = None
        for f in self.features(pya.DBox(cand.x - r, cand.y - r, cand.x + r, cand.y + r)):
            if horizontal:
                along, across = abs(f.x - cand.x), abs(f.y - last.y)
            else:
                along, across = abs(f.y - cand.y), abs(f.x - last.x)
            if along > tol or across <= half or across > r:
                continue            # not lined up, beside the path's own band, or too far away
            key = (round(along, 9), across)
            if best is None or key < best[0]:
                best = (key, f)
        if best is None:
            return cand, None
        f = best[1]
        if horizontal:
            end = pya.DPoint(f.x, cand.y)
            corner_y = last.y + (half if f.y > last.y else -half)
            return end, pya.DEdge(f.x, f.y, f.x, corner_y)
        end = pya.DPoint(cand.x, f.y)
        corner_x = last.x + (half if f.x > last.x else -half)
        return end, pya.DEdge(f.x, f.y, corner_x, f.y)

    def next_point(self, p: pya.DPoint):
        """Constrained, grid-snapped and edge-snapped next vertex: (point, target edge or None).
        Also sets self.guide (see find_guide)."""
        cand = self.constrain(self.snapped(p))
        nxt, edge = self.snap_to_edge(cand)
        if edge is not None:
            self.guide = None
            return nxt, edge
        nxt, self.guide = self.find_guide(cand)
        return nxt, None

    def make_path(self, pts, end_flush=True) -> pya.DPath:
        # the end is flush: the cursor / last click is the path's end edge
        return pya.DPath(pts, self.width, self.bgn_ext, 0.0)

    def show_preview(self, pts, end_flush=False):
        if self.preview is None:
            self.preview = pya.Marker(self._view)
            self.preview.line_width = 1
            self.preview.vertex_size = 0
            t = self.target()
            if t is not None:  # draw the preview in the layer's own texture
                lp = t[3]
                self.preview.color = lp.eff_fill_color(True) & 0xFFFFFF
                self.preview.frame_color = lp.eff_frame_color(True) & 0xFFFFFF
                self.preview.dither_pattern = lp.eff_dither_pattern(True)
        self.preview.set(self.make_path(pts, end_flush).polygon())

    def show_guide(self):
        if self.guide is None:
            self.guide_marker = None
            return
        if self.guide_marker is None:
            self.guide_marker = pya.Marker(self._view)
            self.guide_marker.vertex_size = 0
        self.guide_marker.color = GUIDE_COLOR
        self.guide_marker.frame_color = GUIDE_COLOR
        self.guide_marker.line_width = 1
        self.guide_marker.line_style = 2                       # dashed
        self.guide_marker.set(self.guide)

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
        nxt, edge = self.next_point(p)
        self.hover = (nxt, edge)
        self.show_edge(edge)
        self.show_guide()
        self.show_preview(self.points + [nxt], end_flush=edge is not None)
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
            self.snapped_flags = [False]
            self.show_edge(None)
            return True
        if self.hover is not None and (self.hover[1] is not None or self.guide is not None):
            nxt, edge = self.hover   # click into the snapped position shown in the preview
        else:
            nxt, edge = self.next_point(p)
        if edge is not None:
            if nxt != self.points[-1]:
                self.points.append(nxt)
                self.snapped_flags.append(True)
            self.finish()             # snapped onto a shape: the path is placed
            return True
        if nxt != self.points[-1]:            # a corner, centred on the click
            self.points.append(nxt)
            self.snapped_flags.append(False)
        self.guide = None
        self.show_guide()
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
            self.snapped_flags.pop()
            self.hover = None
            if self.points:
                self.show_preview(self.points)
            else:
                self.reset()
        else:
            return False
        return True

    def finish(self):
        t = self.target()
        keep = [i for i, q in enumerate(self.points) if i == 0 or q != self.points[i - 1]]
        pts = [self.points[i] for i in keep]
        if t is not None and len(pts) >= 2:
            cv, cell, li, _ = t
            path = self.make_path(pts, end_flush=self.snapped_flags[keep[-1]])
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
