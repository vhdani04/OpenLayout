"""Virtuoso-style drag and drop in KLayout's Select (and Move) mode.

KLayout's own move is click-to-pick-up, click-to-drop: the mouse release is ignored, and in Select
mode a press-drag on an object draws a selection box instead. Here, like in Virtuoso, pressing on an
object (or inside the current selection) and dragging moves it with the mouse, and releasing the
button drops it. A press-drag on empty space still draws a selection box; plain clicks still select.

The move itself is KLayout's (move-angle constraint, snapping, dx/dy display, one undo step): this
service only selects the object under the press, starts KLayout's interactive move there and ends
it on release. It takes no mode of its own; it holds a mouse grab so it sees the press before the
selection box starts.
"""
import pya

NAME = "openlayout_drag_move"
MODES = ("select", "move")


class DragMove(pya.Plugin):
    def __init__(self, view):
        super().__init__()
        self._view = view
        self.dragging = False
        self.grabbed = False

    def _grab(self):
        if not self.grabbed:
            self.grab_mouse()
            self.grabbed = True

    def _plain_left(self, buttons):
        mods = pya.ButtonState.ShiftKey | pya.ButtonState.ControlKey | pya.ButtonState.AltKey
        return (buttons & pya.ButtonState.LeftButton) and not (buttons & mods)

    def mouse_moved_event(self, p, buttons, prio):
        self._grab()
        return False

    def mouse_button_pressed_event(self, p, buttons, prio):
        # Only called when the mouse moved with the button down (a plain click never gets here).
        self._grab()
        if not prio or self.dragging or not self._plain_left(buttons):
            return False
        view = self._view
        if view.mode_name() not in MODES or not view.is_editable():
            return False
        if not (view.has_object_selection() and view.selection_bbox().contains(p)):
            view.select_from(p, pya.LayoutView.SelectionMode.Replace)
            if not view.has_object_selection():
                return False      # empty space: let the selection box start
        mw = pya.Application.instance().main_window()
        menu = mw.menu() if mw is not None else None
        if menu is None or not menu.is_valid("@secrets.sel_move_interactive"):
            return False
        menu.action("@secrets.sel_move_interactive").trigger()
        self.dragging = True
        return True

    def mouse_button_released_event(self, p, buttons, prio):
        if not (prio and self.dragging):
            return False
        self.dragging = False
        # KLayout's move ends on Return (at the last mouse position) - drop it where it was released
        self._view.send_key_press_event(pya.KeyCode.Return, 0)
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
