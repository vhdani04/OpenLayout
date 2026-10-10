"""Moving and stretching in KLayout, Virtuoso-style keys.

The behaviour:
- Drag-move: with something selected, the cursor is the four-way move arrow over it; a press-drag
  there moves the selection and the release drops it. A press-drag anywhere else draws a selection
  box; a click selects.
- Move command (`m`, infix): the selection - or, with nothing selected, the object under the mouse
  - follows the mouse from where it was when `m` was pressed, and a click places it. The command
  then repeats: click the next object to move (it follows from that click), and so on, until Esc
  or a right click.
- Stretch (`s`): the edge or corner under the mouse follows it and a click places it.
- Hover: where KLayout's hover highlight would show a frame shape although a click takes something
  else (stdcell.pick_non_frame - a wire, a contact, a transistor on top of the frame), or something a
  click cannot take (a locked layer, an instance with instances off - picking.py), the object a click
  does take is outlined instead, so the highlight always shows what a click selects.
- Click again on the same spot: the next object under the mouse, down through the stack to the
  frame's shapes (picking.candidates) - a GCUT under a transistor, a fin under a contact.
- Right-click in Select mode: the mirror / rotate menu (mirror.py) for the selection - or for the
  object under the mouse, which is selected first.

The move itself is KLayout's interactive move (move-angle constraint, snapping, dx/dy display, one
undo step). KLayout switches into its Move mode for it, where a plain click would pick objects up;
the editor goes back to Select mode once a move is placed. KLayout's move takes the placing click
itself, so the end of a move is noticed when the selection lands (or at the next mouse move).
Then the functions in after_move_hooks are called with the view - the standard-cell code snaps
moved transistors onto their row and into chains there.

The standard-cell frame's shapes cover the whole cell, so picking (clicks too) prefers anything else
under the mouse (stdcell.pick).

DRD hints (drd.py): this service also follows KLayout's own tools, which tell plugins nothing about
what they are drawing, from the mouse input it sees first: a box (Box mode) or polygon (Polygon
mode) being drawn, an edge being stretched (Partial mode, `s`), a selection being moved or copied
(any move: drag, `m`, KLayout's Move, copy `c`) and a cell about to be placed (Instance mode) - and
shows the gaps under the minimum spacing to the neighbouring shapes, on the same layer and between
layers. (The path tool and the via placer show theirs themselves.)

This service takes no mode of its own; it holds a mouse grab so it sees presses and clicks before
KLayout's selection does.
"""
import pya

from . import drd, mirror, picking, pin_group, stdcell

NAME = "openlayout_drag_move"
MODES = ("select", "move")
MOVE_ACTION = "@secrets.sel_move_interactive"
CATCH_PIXELS = 5
_under_mouse = None   # the DragMove of the view the mouse was last over, and where
after_move_hooks = []  # f(view), called when a move is done


def _safe(fn):
    """DRD hints must never break editing: report a failure and carry on"""
    def wrapper(*args, **kw):
        try:
            return fn(*args, **kw)
        except Exception as e:
            print(f"OpenLayout DRD ({fn.__name__}): {type(e).__name__}: {e}")
    wrapper.__name__ = fn.__name__
    return wrapper


def notify_moved(view):
    for hook in list(after_move_hooks):
        try:
            hook(view)
        except Exception as e:
            print(f"OpenLayout: after-move hook failed: {e}")


def _frame_only(view):
    return stdcell.frame_only(view)


def _start_move():
    mw = pya.Application.instance().main_window()
    menu = mw.menu() if mw is not None else None
    if menu is None or not menu.is_valid(MOVE_ACTION):
        return False
    menu.action(MOVE_ACTION).trigger()
    return True


def _status(text):
    mw = pya.Application.instance().main_window()
    if mw is not None:
        mw.message(text, 10000)


def move_under_mouse():
    """The `m` key: the Move command (infix, repeating until Esc)."""
    if _under_mouse is None:
        return
    plugin, p = _under_mouse
    plugin.move_command(p)


def stretch_under_mouse():
    """The `s` key: stretch the edge / corner under the mouse (Partial mode for one stretch)."""
    if _under_mouse is None:
        return
    plugin, p = _under_mouse
    view = plugin._view
    if not view.is_editable():
        return
    plugin.end_command()
    view.clear_selection()
    view.switch_mode("partial")
    plugin.stretch_once = True
    # A press at the mouse, dispatched by a drag beyond KLayout's 5 px click tolerance: Partial mode
    # picks the edge there and starts moving it; the mouse then moves it (button up) until the
    # click that places it.
    left = pya.ButtonState.LeftButton
    pp = plugin.pixel(p)
    view.send_mouse_press_event(pp, left)
    view.send_mouse_move_event(pp + pya.DVector(8, 0), left)
    if plugin._move_in_progress():
        view.send_mouse_move_event(pp, left)
    else:
        view.send_mouse_release_event(pp + pya.DVector(8, 0), left)   # nothing there: end the empty box


class DragMove(pya.Plugin):
    def __init__(self, view):
        super().__init__()
        self._view = view
        self.dragging = False      # a drag-move is in progress
        self.command = None        # the Move command: None, "pick" (waiting for an object) or "moving"
        self.grabbed = False
        self.move_cursor = False
        self.moving = False        # KLayout's move is in progress (seen in Move mode)
        self.stretch_once = False  # Partial mode was entered by `s`: back to Select after the stretch
        self.canvas = None
        self.timer = None
        self.watch_box = None
        self.switching = False     # this service switches KLayout's mode (which cancels - not Esc)
        self.esc_filter = None     # watches the canvas for Esc while a box / move shows hints
        self._drd_moving = None    # (origin, {layer: [DPolygon]}, skip, cv) of the selection being moved
        self._drawing = None       # ("box" | "polygon", [points]) being drawn with KLayout's tools
        self._stretching = None    # (origin, cv, layer, polygon, edge index, skip) of an edge stretch
        self.box_new = False       # a box / polygon / stretch was just started (KLayout then cancels other drags)
        self.drd_tried = False     # the selection being moved was looked at (it may have no checked layer)
        self.last_p = None         # the mouse position of the previous move event
        self.inst_cache = {}       # (cell name, angle, mirror) -> {layer: [DPolygon]} for Instance mode
        self.inst_shown = False
        self.hover_markers = []    # the outline of what a click takes, where KLayout's hover shows the frame
        self.hover_target = None   # ... and that object (an ObjectInstPath)
        self.last_pick = None      # (point, ObjectInstPath) of the last click's pick: clicked again, the next one
        view.on_transient_selection_changed += self._hover_changed
        self.pin_group = pin_group.PinGroup(view)   # a selected pin brings its label
        self.select_filter = picking.SelectionFilter(view)   # box selections too skip what can't be selected

    # ---- hover highlight ------------------------------------------------------------------------
    def _clear_hover(self):
        for m in self.hover_markers:
            m._destroy()
        self.hover_markers = []
        self.hover_target = None

    def _hover_changed(self):
        """KLayout's hover highlight changed: if it shows only frame shapes while a click would
        take something else, or something a click cannot take, show what a click takes instead."""
        view = self._view
        objs = list(view.each_object_selected_transient())
        if not objs or self.last_p is None or view.mode_name() != "select":
            return
        frame_only = all(stdcell.is_frame_object(o) for o in objs)
        blocked = not all(picking.allowed(view, o) for o in objs)
        if not frame_only and not blocked:
            self._clear_hover()
            return
        better = stdcell.pick_non_frame(view, self.last_p)
        if better is None and blocked:
            cands = picking.candidates(view, self.last_p)
            better = cands[0] if cands else None
        if better is None:
            if blocked:
                view.clear_transient_selection()
                self._clear_hover()
            return
        view.clear_transient_selection()
        self._clear_hover()
        self.hover_markers = hover_outline(view, better)
        self.hover_target = better

    def _grab(self):
        if not self.grabbed:
            self.grab_mouse()
            self.grabbed = True

    def _plain_left(self, buttons):
        mods = pya.ButtonState.ShiftKey | pya.ButtonState.ControlKey | pya.ButtonState.AltKey
        return (buttons & pya.ButtonState.LeftButton) and not (buttons & mods)

    def over_selection(self, p):
        """True where the selection can be dragged (within a few pixels, like KLayout's own picking -
        thin shapes such as fins or wires are picked from just beside them)"""
        view = self._view
        if not (view.mode_name() in MODES and view.is_editable() and view.has_object_selection()):
            return False
        tol = CATCH_PIXELS / view.viewport_trans().mag
        return view.selection_bbox().enlarged(tol, tol).contains(p)

    def pixel(self, p):
        """micrometers -> widget pixels (y down)"""
        q = self._view.viewport_trans() * p
        return pya.DPoint(q.x, self._view.viewport_height() - q.y)

    # ---- the Move command ---------------------------------------------------------------------
    def move_command(self, p):
        view = self._view
        if not view.is_editable():
            return
        self.end_command()
        if not self.over_selection(p) or (_frame_only(view) and stdcell.pick_non_frame(view, p) is not None):
            stdcell.pick(view, p)
        self.command = "pick"
        if view.has_object_selection():
            self._start(p)
        else:
            _status("Move: click the object to move (Esc to finish)")

    def _start(self, p):
        self.drd_start(p)
        self.switching = True
        try:
            started = _start_move()
        finally:
            self.switching = False
        if started:
            self.command = "moving" if self.command else None
            self.watch_drop()
            if self.command:
                _status("Move: click to place (Esc to finish)")

    def end_command(self):
        if self.command:
            self.command = None
            _status("Move finished")

    def watch_drop(self):
        """After a pick-up: notice the drop as soon as the selection has moved."""
        view = self._view
        self.watch_box = view.selection_bbox() if view.has_object_selection() else None
        if self.watch_box is None:
            return
        if self.timer is None:
            self.timer = pya.QTimer()
            self.timer.interval = 80
            self.timer.timeout = self._check_drop
        self.timer.start()

    def _check_drop(self):
        view = self._view
        if self.destroyed() or view.mode_name() != "move" or self.watch_box is None:
            self.timer.stop()
            return
        if not view.has_object_selection() or view.selection_bbox() != self.watch_box:
            self.timer.stop()
            self.watch_box = None
            self._back_to_select()

    def _back_to_select(self):
        self.drd_stop()
        stretched = self.stretch_once or self._view.mode_name() == "partial"
        if stretched:
            # KLayout keeps the stretched edge selected, and in stretch mode the next press would
            # move it again wherever it happens - a stretch leaves nothing selected
            self._view.clear_selection()
        self.moving = False
        self.stretch_once = False
        self.switching = True
        try:
            self._view.switch_mode("select")
        finally:
            self.switching = False
        if not stretched:
            notify_moved(self._view)
        if self.command == "moving":      # the Move command repeats: the next object
            self._view.clear_selection()
            self.command = "pick"
            _status("Move: click the next object to move (Esc to finish)")

    def _move_in_progress(self):
        """KLayout's move service is dragging: while it does, it is first in line for mouse events
        and sets the four-way cursor before this service sees the event (otherwise each mouse event
        starts with the cursor reset)."""
        if self.canvas is None:
            kids = [c for c in self._view.widget().children() if type(c).__name__ == "QWidget_Native"]
            self.canvas = kids[0] if kids else False
        return bool(self.canvas) and self.canvas.cursor.shape == pya.Qt.SizeAllCursor

    # ---- events -----------------------------------------------------------------------------------
    def mouse_moved_event(self, p, buttons, prio):
        global _under_mouse
        self._grab()
        if prio and self.hover_markers:
            self._clear_hover()
        _under_mouse = (self, p)
        mode = self._view.mode_name()
        last, self.last_p = self.last_p, p
        self.box_new = False
        if self._drawing is not None and mode != self._drawing[0]:
            self.drawing = None
        elif prio and self._drawing is not None:
            self.drd_drawing(p)
        if prio and mode == "instance":
            self.drd_instance(p)
            self.inst_shown = True
        elif prio and self.inst_shown:     # left Instance mode
            self.inst_shown = False
            drd.clear(self._view)
        if prio and mode == "partial" and not self.stretch_once and self._stretching is not None:
            if self._move_in_progress():
                self.drd_stretch(p)
            else:
                self.stretching = None
                drd.clear(self._view)
        if prio and (mode == "move" or (mode == "partial" and self.stretch_once)):
            if self._move_in_progress():
                self.moving = True
                if mode == "partial":
                    self.drd_stretch(p)
                else:
                    if self._drd_moving is None and not self.drd_tried:
                        # a move KLayout started itself (its Move tool, copy): from where the mouse was
                        self.drd_start(last or p)
                    self.drd_update(p)
                return False
            if self.moving:          # a move / stretch was just placed: back to Select mode
                self._back_to_select()
        # four-way arrow over a selection; back to the arrow once the mouse leaves it
        if prio and not (buttons & pya.ButtonState.LeftButton):
            over = self.over_selection(p)
            if over:
                self.set_cursor(pya.Cursor.SizeAll)
            elif self.move_cursor:
                self.set_cursor(pya.Cursor.Arrow)
            self.move_cursor = over
        return False

    def mouse_button_pressed_event(self, p, buttons, prio):
        # Only called when the mouse moved with the button down (a plain click never gets here).
        self._grab()
        view = self._view
        if prio and view.mode_name() == "box" and self._plain_left(buttons):
            self.drawing = ("box", [self.snap(p)])
            self.box_new = True
            return False
        if prio and view.mode_name() == "partial" and self._plain_left(buttons):
            self.stretch_start(p)            # the edge KLayout's Partial mode picks there
            return False
        if not prio or self.dragging or not self._plain_left(buttons) or self.command:
            return False
        if view.mode_name() != "select" or not view.is_editable() or not self.over_selection(p):
            return False                      # not on the selection: KLayout's selection box
        if _frame_only(view) and stdcell.pick_non_frame(view, p) is not None:
            return False                      # a frame shape selected, a transistor under the press
        if not _start_move():
            return False
        self.drd_start(p)          # after the switch to Move mode, which cancels drags (drag_cancel)
        self.dragging = True
        return True

    def mouse_button_released_event(self, p, buttons, prio):
        if prio and self._drawing is not None and self._drawing[0] == "box":
            self.drawing = None
            drd.clear(self._view)
            return False
        if prio and self._stretching is not None and not self.stretch_once:
            self.stretching = None
            drd.clear(self._view)
            return False
        if not (prio and self.dragging):
            return False
        self.dragging = False
        self.drd_stop()
        # KLayout's move ends on Return (at the last mouse position) - drop it where it was released
        self._view.send_key_press_event(pya.KeyCode.Return, 0)
        self.moving = False
        if self._view.mode_name() == "move":
            self._view.switch_mode("select")
        notify_moved(self._view)
        return True

    def mouse_click_event(self, p, buttons, prio):
        # This service sees a click first (prio, as it holds a grab) and again after KLayout's own
        # click selection (non-priority round).
        view = self._view
        mode = view.mode_name()
        if prio and mode == "box" and buttons & pya.ButtonState.LeftButton:
            if self._drawing is None:
                self.drawing = ("box", [self.snap(p)])
                self.box_new = True
            else:
                self.drawing = None
                drd.clear(view)
            return False
        if prio and mode == "polygon" and buttons & pya.ButtonState.LeftButton:
            if self._drawing is None:
                self.drawing = ("polygon", [self.snap(p)])
                self.box_new = True
            else:
                pts = self._drawing[1]
                q = self._ortho(pts[-1], self.snap(p))
                if q != pts[-1]:
                    pts.append(q)
            return False
        if prio and self.hover_markers:
            self._clear_hover()
        if prio and self.command and buttons & pya.ButtonState.RightButton:
            self.end_command()
            return True
        if prio and buttons & pya.ButtonState.RightButton and mode == "select" and view.is_editable():
            # the right-click menu: for the selection, else for what is under the mouse
            if not view.has_object_selection():
                stdcell.pick(view, p)
            if view.has_object_selection():
                mirror.show_menu(view)
                return True
            return False
        left = buttons & pya.ButtonState.LeftButton
        other = buttons & (pya.ButtonState.ControlKey | pya.ButtonState.AltKey)
        if not left or other or view.mode_name() != "select" or not view.is_editable():
            return False
        if prio and self.command == "pick":
            # the Move command waits for the next object: it follows from this click
            if stdcell.pick(view, p):
                self._start(p)
            return True
        if prio:
            self.before_click = list(view.each_object_selected())
            return False
        # after KLayout's selection (picking.py):
        before = getattr(self, "before_click", [])
        shift = bool(buttons & pya.ButtonState.ShiftKey)
        keep = before if shift else []
        now = list(view.each_object_selected())
        added = [o for o in now if not any(o == b for b in before)]
        # - the same spot clicked again (a plain click, the object picked there still selected): the
        #   next object under the mouse, down through the stack
        last = self.last_pick
        if not shift and last is not None and self.pixel(p).distance(self.pixel(last[0])) <= CATCH_PIXELS \
                and any(picking.same(last[1], b) for b in before):
            cands = picking.candidates(view, p)
            if len(cands) > 1:
                i = (next((k for k, c in enumerate(cands) if picking.same(c, last[1])), -1) + 1) % len(cands)
                view.object_selection = [cands[i]]
                self.last_pick = (p, cands[i])
                _status(f"{i + 1} of {len(cands)} under the mouse: {picking.describe(view, cands[i])}"
                        " - click again for the next")
                return False
        # - only frame shapes where something else lies (the transistor), something a click cannot take
        #   (a locked layer, an instance with instances off), or nothing although something is there:
        #   the top object a click can take
        frame_only = added and all(stdcell.is_frame_object(o) for o in added)
        blocked = added and not all(picking.allowed(view, o) for o in added)
        if frame_only or blocked or (not now and not shift):
            cands = picking.candidates(view, p)
            choice = next((c for c in cands if not picking.is_frame(c)), cands[0] if cands else None)
            if choice is not None or blocked:
                view.object_selection = keep + ([choice] if choice is not None else [])
        picked = [o for o in view.each_object_selected() if not any(o == b for b in before)]
        self.last_pick = (p, picked[0]) if len(picked) == 1 else None
        return False

    def mouse_double_click_event(self, p, buttons, prio):
        if prio and self._drawing is not None and self._drawing[0] == "polygon":
            self.drawing = None            # the polygon is finished
            drd.clear(self._view)
        return False

    def drag_cancel(self):          # Esc (KLayout also cancels when the mode changes)
        if self.box_new:           # the box / polygon tool starting its shape (it cancels twice), not Esc
            return
        if not self.switching:
            self.drd_stop()
            self.drawing = None
            self.end_command()

    # ---- DRD hints -------------------------------------------------------------------------------
    @property
    def drawing(self):
        return self._drawing

    @drawing.setter
    def drawing(self, value):
        self._drawing = value
        self._watch_esc()

    @property
    def stretching(self):
        return self._stretching

    @stretching.setter
    def stretching(self, value):
        self._stretching = value
        self._watch_esc()

    @property
    def drd_moving(self):
        return self._drd_moving

    @drd_moving.setter
    def drd_moving(self, value):
        self._drd_moving = value
        self._watch_esc()

    def _watch_esc(self):
        """Esc ends a box or a move without telling this service (KLayout's tool takes the key):
        while hints may be up, an event filter on the canvas sees it"""
        busy = self._drawing is not None or self._drd_moving is not None or self._stretching is not None
        if busy and self.esc_filter is None and self._move_in_progress() is not None and self.canvas:
            self.esc_filter = EscFilter(self)
            self.canvas.installEventFilter(self.esc_filter)
        elif not busy and self.esc_filter is not None:
            if self.canvas:
                self.canvas.removeEventFilter(self.esc_filter)
            self.esc_filter = None

    def escape(self):
        self.drawing = None
        self.drd_stop()

    def _current_layer(self):
        """(cellview, layer index) of the LSW's current drawing layer"""
        view = self._view
        cur = view.current_layer
        if cur.is_null() or cur.at_end() or cur.current().has_children():
            return None
        lp = cur.current()
        cv = view.cellview(lp.cellview() if lp.cellview() >= 0 else 0)
        if not cv.is_valid():
            return None
        return cv, cv.layout().layer(lp.source_layer, lp.source_datatype)

    @staticmethod
    def _ortho(last, q):
        """the next polygon point as KLayout's Manhattan connections place it"""
        if abs(q.x - last.x) >= abs(q.y - last.y):
            return pya.DPoint(q.x, last.y)
        return pya.DPoint(last.x, q.y)

    @_safe
    def drd_drawing(self, p):
        """the box / polygon being drawn, up to the mouse"""
        target = self._current_layer()
        if target is None:
            return
        cv, li = target
        ctx = cv.context_dtrans()
        kind, pts = self._drawing
        q = self.snap(p)
        if kind == "box":
            box = pya.DBox(pts[0], q)
            shape = pya.DPolygon(box) if box.width() > 0 and box.height() > 0 else None
        else:
            ring = pts + [self._ortho(pts[-1], q)]
            ring = [a for i, a in enumerate(ring) if i == 0 or a != ring[i - 1]]
            shape = pya.DPolygon(ring) if len(ring) >= 3 and pya.DPolygon(ring).area() > 0 else None
        if shape is None:
            drd.clear(self._view)
            return
        drd.show(self._view, cv.cell, li, [shape.transformed(ctx.inverted())], trans=ctx)

    @_safe
    def stretch_start(self, p):
        """the shape edge nearest to p in the current cell (what Partial mode stretches)"""
        self.stretching = None
        view = self._view
        cv = view.active_cellview()
        if not cv.is_valid():
            return
        layout, cell = cv.layout(), cv.cell
        ctx = cv.context_dtrans()
        q = ctx.inverted() * p
        tol = 6 / view.viewport_trans().mag
        win = pya.DBox(q.x - tol, q.y - tol, q.x + tol, q.y + tol).to_itype(layout.dbu)
        best = None
        for li in layout.layer_indexes():
            if not drd.checked(layout, li):
                continue
            for s in cell.shapes(li).each_touching(win):
                if not (s.is_box() or s.is_polygon() or s.is_path()):
                    continue
                poly = s.dpolygon
                for i, e in enumerate(poly.each_edge()):
                    if e.dx() != 0 and e.dy() != 0:
                        continue
                    d = e.distance_abs(q)
                    lo_x, hi_x = sorted((e.p1.x, e.p2.x))
                    lo_y, hi_y = sorted((e.p1.y, e.p2.y))
                    if not (lo_x - tol <= q.x <= hi_x + tol and lo_y - tol <= q.y <= hi_y + tol):
                        continue
                    if d <= tol and (best is None or d < best[0]):
                        best = (d, li, s, poly, i)
        if best is None:
            return
        self.box_new = True        # Partial mode now cancels the other drags: not an Esc
        _, li, shape, poly, i = best
        cidx = cell.cell_index()

        def skip(it, shape=shape, cidx=cidx):
            return it.cell_index() == cidx and it.shape() == shape
        self.stretching = (p, cv, li, poly, i, skip)

    @_safe
    def drd_stretch(self, p):
        if self._stretching is None:
            return
        origin, cv, li, poly, i, skip = self._stretching
        d = self.snap(p) - self.snap(origin)
        pts = list(poly.each_point_hull())
        a, b = pts[i], pts[(i + 1) % len(pts)]
        shift = pya.DVector(d.x, 0) if a.x == b.x else pya.DVector(0, d.y)   # the edge moves across itself
        pts[i], pts[(i + 1) % len(pts)] = a + shift, b + shift
        new = pya.DPolygon(pts)
        if new.area() <= 0:
            drd.clear(self._view)
            return
        drd.show(self._view, cv.cell, li, [new], skip, trans=cv.context_dtrans())

    @_safe
    def drd_instance(self, p):
        """the cell the Instance tool is about to place, at the mouse (KLayout puts the corner of
        its bounding box there unless "place origin" is set)"""
        mw = pya.Application.instance().main_window()
        cv = self._view.active_cellview()
        name = mw.get_config("edit-inst-cell-name") if mw else ""
        if not name or not cv.is_valid():
            drd.clear(self._view)
            return
        angle = float(mw.get_config("edit-inst-angle") or 0)
        mirror = mw.get_config("edit-inst-mirror") == "true"
        key = (id(cv.layout()), name, angle, mirror)
        if key not in self.inst_cache:
            self.inst_cache[key] = self._instance_shapes(cv.layout(), name, pya.DCplxTrans(1, angle, mirror, 0, 0))
        geo = self.inst_cache[key]
        if not geo:
            drd.clear(self._view)
            return
        shapes, bbox = geo
        ctx = cv.context_dtrans()
        q = ctx.inverted() * self.snap(p)
        d = q - pya.DPoint(0, 0) if mw.get_config("edit-inst-place-origin") == "true" else q - bbox.p1
        moved = {li: [poly.moved(d.x, d.y) for poly in polys] for li, polys in shapes.items()}
        drd.show_layers(self._view, cv.cell, moved, None, trans=ctx)

    @staticmethod
    def _instance_shapes(layout, name, trans):
        """({layer of `layout`: [DPolygon]}, bbox) of a cell of this layout or of a library
        (standard cells; not PCells, whose parameters the tool keeps to itself)"""
        src = layout.cell(name)
        src_layout = layout
        if src is None:
            for lname in pya.Library.library_names():
                lib = pya.Library.library_by_name(lname)
                if lib is None:
                    continue
                c = lib.layout().cell(name)
                if c is not None and not c.is_pcell_variant() and lib.layout().pcell_declaration(name) is None:
                    src, src_layout = c, lib.layout()
                    break
        if src is None:
            return None
        shapes = {}
        for sli in src_layout.layer_indexes():
            info = src_layout.get_info(sli)
            li = layout.find_layer(info)
            if li is None or not drd.checked(layout, li):
                continue
            it = src.begin_shapes_rec(sli)
            while not it.at_end():
                s = it.shape()
                if s.is_box() or s.is_polygon() or s.is_path():
                    poly = s.polygon.transformed(it.trans()).to_dtype(src_layout.dbu)
                    shapes.setdefault(li, []).append(poly.transformed(trans))
                it.next()
        bbox = (trans * src.dbbox()) if not src.bbox().empty() else pya.DBox(0, 0, 0, 0)
        return shapes, bbox

    def drd_start(self, p):
        """remember the selection (per layer, cell coordinates) as the move starts"""
        self.drd_tried = True
        try:
            self.drd_moving = None
            view = self._view
            shapes, objs = {}, []
            cv = None
            for obj in view.each_object_selected():
                cv = view.cellview(obj.cv_index)
                layout = cv.layout()
                dbu = layout.dbu
                objs.append(obj)
                if obj.is_cell_inst():
                    child = obj.inst().cell
                    for li in layout.layer_indexes():
                        if not drd.checked(layout, li):
                            continue
                        it = child.begin_shapes_rec(li)
                        while not it.at_end():
                            s = it.shape()
                            if s.is_box() or s.is_polygon() or s.is_path():
                                poly = s.polygon.transformed(it.trans()).to_dtype(dbu)
                                shapes.setdefault(li, []).append(poly.transformed(obj.dtrans()))
                            it.next()
                elif not obj.shape.is_text() and drd.checked(layout, obj.layer):
                    poly = obj.shape.polygon.to_dtype(dbu).transformed(obj.dtrans())
                    shapes.setdefault(obj.layer, []).append(poly)
            if cv is None or not shapes:
                return
            sel_shapes = [(o.cell_index(), o.shape) for o in objs if not o.is_cell_inst()]
            sel_paths = [[e.inst() for e in o.path] for o in objs if o.is_cell_inst()]

            def skip(it):
                if any(c == it.cell_index() and s == it.shape() for c, s in sel_shapes):
                    return True
                path = [e.inst() for e in it.path()]
                return any(len(path) >= len(sp) and all(a == b for a, b in zip(path, sp)) for sp in sel_paths)
            self.drd_moving = (p, shapes, skip, cv)
        except Exception as e:
            print(f"OpenLayout DRD: {e}")
            self.drd_moving = None

    @_safe
    def drd_update(self, p):
        if self.drd_moving is None:
            return
        origin, shapes, skip, cv = self.drd_moving
        d = self.snap(p) - self.snap(origin)          # KLayout's move snaps the displacement too
        moved = {li: [poly.moved(d.x, d.y) for poly in polys] for li, polys in shapes.items()}
        drd.show_layers(self._view, cv.cell, moved, skip, trans=cv.context_dtrans())

    def drd_stop(self):
        self.drd_moving = None
        self.drd_tried = False
        self.stretching = None
        drd.clear(self._view)

    def deactivated(self):
        self.dragging = False


def hover_outline(view, oip):
    """Markers outlining an object (an ObjectInstPath at the top), styled like the hover highlight."""
    color = view.get_config("sel-color")
    color = int(color.lstrip("#"), 16) if color.startswith("#") else 0xFFFFFF
    layout = view.cellview(oip.cv_index).layout()
    if oip.is_cell_inst():
        shapes = [oip.inst().dbbox()]
    else:
        shapes = [oip.shape.dpolygon] if oip.shape.is_box() or oip.shape.is_polygon() or oip.shape.is_path() \
            else [oip.shape.dbbox()]
    out = []
    for s in shapes:
        m = pya.Marker(view)
        m.set(s)
        m.color = color
        m.frame_color = color
        m.line_width = 1
        m.dither_pattern = 1           # outline only, like KLayout's hover
        m.vertex_size = 0
        out.append(m)
    return out


class EscFilter(pya.QObject):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def eventFilter(self, obj, event):
        if event.type() == pya.QEvent.KeyPress and getattr(event, "key", lambda: None)() == pya.Qt.Key_Escape.to_i():
            pya.QTimer.singleShot(0, self.service.escape)     # not while Qt delivers this event
        return False


class DragMoveFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = False
        self.register(-1000, NAME, "")

    def create_plugin(self, manager, root, view):
        return DragMove(view)
