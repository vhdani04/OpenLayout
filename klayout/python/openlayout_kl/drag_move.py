"""Virtuoso-style drag and drop in KLayout's Select (and Move) mode.

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

The move itself is KLayout's (move-angle constraint, snapping, dx/dy display, one undo step): this
service only selects the object under the press, starts KLayout's interactive move there and ends
it on release. It takes no mode of its own; it holds a mouse grab so it sees the press before the
selection box starts.
"""
import pya

NAME = "openlayout_drag_move"
MODES = ("select", "move")
MOVE_ACTION = "@secrets.sel_move_interactive"
_under_mouse = None   # the DragMove of the view the mouse was last over, and where


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
            view.select_from(p, pya.LayoutView.SelectionMode.Replace)
    _start_move()


class DragMove(pya.Plugin):
    def __init__(self, view):
        super().__init__()
        self._view = view
        self.dragging = False
        self.grabbed = False
        self.move_cursor = False
        self.moving = False      # KLayout's move is in progress (seen in Move mode)
        self.canvas = None

    def _grab(self):
        if not self.grabbed:
            self.grab_mouse()
            self.grabbed = True

    def _plain_left(self, buttons):
        mods = pya.ButtonState.ShiftKey | pya.ButtonState.ControlKey | pya.ButtonState.AltKey
        return (buttons & pya.ButtonState.LeftButton) and not (buttons & mods)

    def over_selection(self, p):
        """True where a press-drag moves the current selection"""
        view = self._view
        return (view.mode_name() in MODES and view.is_editable() and view.has_object_selection()
                and view.selection_bbox().contains(p))

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
        if prio and self._view.mode_name() == "move":
            if self._move_in_progress():
                self.moving = True
                return False
            if self.moving:          # a move was just dropped: back to Select mode
                self.moving = False
                self._view.switch_mode("select")
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
        if not self.over_selection(p):
            view.select_from(p, pya.LayoutView.SelectionMode.Replace)
            if not view.has_object_selection():
                return False      # empty space: let the selection box start
        if not _start_move():
            return False
        self.dragging = True
        return True

    def mouse_button_released_event(self, p, buttons, prio):
        if not (prio and self.dragging):
            return False
        self.dragging = False
        # KLayout's move ends on Return (at the last mouse position) - drop it where it was released
        self._view.send_key_press_event(pya.KeyCode.Return, 0)
        self.moving = False
        if self._view.mode_name() == "move":
            self._view.switch_mode("select")
        return True

    def deactivated(self):
        self.dragging = False


class DragMoveFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = False
        self.register(-1000, NAME, "")

    def create_plugin(self, manager, root, view):
        return DragMove(view)
