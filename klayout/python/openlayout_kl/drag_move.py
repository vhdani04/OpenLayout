"""Virtuoso-style move and stretch: drag and drop in KLayout's Select, Move and Partial modes.

KLayout's own move is click-to-pick-up, click-to-drop: the mouse release is ignored, and in Select
mode a press-drag on an object draws a selection box instead. Here, like in Virtuoso, pressing on an
object (or inside the current selection) and dragging moves it with the mouse, and releasing the
button drops it. A press-drag on empty space still draws a selection box; plain clicks still select.
Over a selection the cursor is the four-way move arrow.

KLayout's interactive move (also behind `m`) switches the editor into Move mode and stays there, so
the next plain click would pick an object up again. Like Virtuoso, the editor returns to Select
mode once a move is done.

`m` (move_under_mouse) works on the object under the mouse right away, like Virtuoso - KLayout's own
move key only sees it once the hover highlight has appeared.

Stretch is KLayout's Partial mode, which has the same click-to-pick-up / click-to-drop move. `s`
(stretch_under_mouse) picks up the edge or corner under the mouse right away - it follows the mouse
and a click places it - and the editor returns to Select mode afterwards; in Partial mode a
press-drag on an edge drops it on release.

When a move (drag, m) is done, the functions in after_move_hooks are called with the view - the
standard-cell code snaps moved transistors into chains there. The standard-cell frame's shapes cover
the whole cell, so picking (clicks too) prefers anything else under the mouse (stdcell.pick); a
press-drag that would pick up only an unselected frame shape draws a selection box, a selected
frame shape drags like anything else.

The move itself is KLayout's (move-angle constraint, snapping, dx/dy display, one undo step): this
service only selects the object under the press, starts KLayout's interactive move there and ends
it on release. It takes no mode of its own; it holds a mouse grab so it sees the press before the
selection box starts.
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
        # Only called when the mouse moved with the button down (a plain click never gets here).
        self._grab()
        if not prio or self.dragging or not self._plain_left(buttons):
            return False
        view = self._view
        if view.mode_name() not in MODES or not view.is_editable():
            return False
        if self.over_selection(p) and _frame_only(view):
            # selected frame shapes drag - unless there is something else (a transistor) under the press
            frame = list(view.each_object_selected())
            stdcell.pick(view, p)
            if not view.has_object_selection() or _frame_only(view):
                view.object_selection = frame
        elif not self.over_selection(p):
            stdcell.pick(view, p)
            if not view.has_object_selection() or _frame_only(view):
                view.clear_selection()
                return False      # empty space (or only an unselected frame shape): selection box
        if not _start_move():
            return False
        self.dragging = True
        return True

    def mouse_button_released_event(self, p, buttons, prio):
        if prio and self._view.mode_name() == "partial" and self._move_in_progress():
            # a dragged edge: Partial mode ends its stretch on Return too
            self._view.send_key_press_event(pya.KeyCode.Return, 0)
            if self.stretch_once:
                self._back_to_select()
            else:
                self._view.clear_selection()   # see _back_to_select
            self.moving = False
            return True
        if not (prio and self.dragging):
            return False
        self.dragging = False
        # KLayout's move ends on Return (at the last mouse position) - drop it where it was released
        self._view.send_key_press_event(pya.KeyCode.Return, 0)
        self.moving = False
        if self._view.mode_name() == "move":
            self._view.switch_mode("select")
        notify_moved(self._view)
        return True

    def mouse_click_event(self, p, buttons, prio):
        # Around KLayout's own click selection: this service sees the click first (prio, as it holds
        # a grab) and again after it (non-priority round). If the click picked only a frame shape
        # where something else lies (e.g. the transistor), that is taken instead - for a plain click
        # and for Shift (add to the selection).
        view = self._view
        left = buttons & pya.ButtonState.LeftButton
        other = buttons & (pya.ButtonState.ControlKey | pya.ButtonState.AltKey)
        if self.dragging or not left or other or view.mode_name() not in MODES:
            return False
        if prio:
            self.before_click = list(view.each_object_selected())
            return False
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
