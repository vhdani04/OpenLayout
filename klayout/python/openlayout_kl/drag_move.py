"""Virtuoso-style move and stretch in KLayout: click to pick up, click to drop.

Moving: a click selects; a second click on the selected object (the cursor is the four-way move
arrow over a selection) picks it up - it follows the mouse - and the next click drops it. A
press-drag always draws a selection box (plain clicks still select). This is KLayout's own
interactive move (move-angle constraint, snapping, dx/dy display, one undo step), started at the
click.

KLayout's interactive move (also behind `m`) switches the editor into Move mode and stays there, so
the next plain click would pick an object up again. Like Virtuoso, the editor returns to Select
mode once a move is done.

`m` (move_under_mouse) works on the object under the mouse right away, like Virtuoso - KLayout's own
move key only sees it once the hover highlight has appeared.

Stretch is KLayout's Partial mode, which has the same click-to-pick-up / click-to-drop move. `s`
(stretch_under_mouse) picks up the edge or corner under the mouse right away - it follows the mouse
and a click places it - and the editor returns to Select mode afterwards.

When a move (click-click, m) is done - noticed when the selection lands (KLayout's move takes the
dropping click itself), or else at the next mouse move - the functions in after_move_hooks are
called with the view -
the standard-cell code snaps moved transistors onto their row and into chains there. The
standard-cell frame's shapes cover the whole cell, so picking (clicks too) prefers anything else
under the mouse (stdcell.pick); with a frame shape selected, a click on a transistor selects the
transistor rather than picking up the frame shape.

This service takes no mode of its own; it holds a mouse grab so it sees clicks before KLayout's
selection does.
"""
import pya

from . import stdcell

NAME = "openlayout_drag_move"
MODES = ("select", "move")
MOVE_ACTION = "@secrets.sel_move_interactive"
CATCH_PIXELS = 5
_under_mouse = None   # the DragMove of the view the mouse was last over, and where
after_move_hooks = []  # f(view), called when a move is done


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


def move_under_mouse():
    """The `m` key: move the selection if the mouse is on it, else the object under the mouse."""
    if _under_mouse is not None:
        plugin, p = _under_mouse
        view = plugin._view
        if view.is_editable() and not plugin.over_selection(p):
            stdcell.pick(view, p)
        if _start_move():
            plugin.watch_drop()
        return
    _start_move()


def stretch_under_mouse():
    """The `s` key: stretch the edge / corner under the mouse (Partial mode for one stretch)."""
    if _under_mouse is None:
        return
    plugin, p = _under_mouse
    view = plugin._view
    if not view.is_editable():
        return
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
        self.dragging = False
        self.grabbed = False
        self.move_cursor = False
        self.moving = False      # KLayout's move is in progress (seen in Move mode)
        self.stretch_once = False  # Partial mode was entered by `s`: back to Select after the stretch
        self.canvas = None

    def _grab(self):
        if not self.grabbed:
            self.grab_mouse()
            self.grabbed = True

    def _plain_left(self, buttons):
        mods = pya.ButtonState.ShiftKey | pya.ButtonState.ControlKey | pya.ButtonState.AltKey
        return (buttons & pya.ButtonState.LeftButton) and not (buttons & mods)

    def over_selection(self, p):
        """True where a press-drag moves the current selection (within a few pixels, like KLayout's
        own picking - thin shapes such as fins or wires are picked from just beside them)"""
        view = self._view
        if not (view.mode_name() in MODES and view.is_editable() and view.has_object_selection()):
            return False
        tol = CATCH_PIXELS / view.viewport_trans().mag
        return view.selection_bbox().enlarged(tol, tol).contains(p)

    def watch_drop(self):
        """After a pick-up: notice the drop as soon as the selection has moved."""
        view = self._view
        self.watch_box = view.selection_bbox() if view.has_object_selection() else None
        if self.watch_box is None:
            return
        if getattr(self, "timer", None) is None:
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

    def pixel(self, p):
        """micrometers -> widget pixels (y down)"""
        q = self._view.viewport_trans() * p
        return pya.DPoint(q.x, self._view.viewport_height() - q.y)

    def _back_to_select(self):
        stretched = self.stretch_once or self._view.mode_name() == "partial"
        if stretched:
            # KLayout keeps the stretched edge selected, and in stretch mode the next press would
            # move it again wherever it happens - a stretch leaves nothing selected
            self._view.clear_selection()
        self.moving = False
        self.stretch_once = False
        self._view.switch_mode("select")
        if not stretched:
            notify_moved(self._view)

    def _move_in_progress(self):
        """KLayout's move service is dragging: while it does, it is first in line for mouse events
        and sets the four-way cursor before this service sees the event (otherwise each mouse event
        starts with the cursor reset)."""
        if self.canvas is None:
            kids = [c for c in self._view.widget().children() if type(c).__name__ == "QWidget_Native"]
            self.canvas = kids[0] if kids else False
        return bool(self.canvas) and self.canvas.cursor.shape == pya.Qt.SizeAllCursor

    def mouse_moved_event(self, p, buttons, prio):
        global _under_mouse
        self._grab()
        _under_mouse = (self, p)
        mode = self._view.mode_name()
        if prio and (mode == "move" or (mode == "partial" and self.stretch_once)):
            if self._move_in_progress():
                self.moving = True
                return False
            if self.moving:          # a move / stretch was just dropped: back to Select mode
                self._back_to_select()
        # four-way arrow over a selection, like Virtuoso; back to the arrow once the mouse leaves it
        if prio and not (buttons & pya.ButtonState.LeftButton):
            over = self.over_selection(p)
            if over:
                self.set_cursor(pya.Cursor.SizeAll)
            elif self.move_cursor:
                self.set_cursor(pya.Cursor.Arrow)
            self.move_cursor = over
        return False

    def mouse_button_pressed_event(self, p, buttons, prio):
        self._grab()
        return False             # press-drags are KLayout's: a selection box

    def mouse_click_event(self, p, buttons, prio):
        # This service sees a click first (prio, as it holds a grab) and again after KLayout's own
        # click selection (non-priority round).
        view = self._view
        left = buttons & pya.ButtonState.LeftButton
        other = buttons & (pya.ButtonState.ControlKey | pya.ButtonState.AltKey)
        if not left or other or view.mode_name() != "select" or not view.is_editable():
            return False
        if prio:
            # a plain click on the selection picks it up (unless it is only a frame shape with a
            # transistor or other object under the click: that one gets selected instead)
            if not (buttons & pya.ButtonState.ShiftKey) and self.over_selection(p) \
                    and not (_frame_only(view) and stdcell.pick_non_frame(view, p) is not None):
                if _start_move():
                    self.watch_drop()
                    return True
                return False
            self.before_click = list(view.each_object_selected())
            return False
        # after KLayout's selection: a click that only picked a frame shape where something else lies
        # (e.g. the transistor) takes that instead - for a plain click and for Shift (add)
        before = getattr(self, "before_click", [])
        added = [o for o in view.each_object_selected() if not any(o == b for b in before)]
        if added and all(stdcell.is_frame_object(o) for o in added):
            better = stdcell.pick_non_frame(view, p)
            if better is not None:
                keep = before if buttons & pya.ButtonState.ShiftKey else []
                view.object_selection = keep + [better]
        return False

    def deactivated(self):
        self.dragging = False


class DragMoveFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = False
        self.register(-1000, NAME, "")

    def create_plugin(self, manager, root, view):
        return DragMove(view)
