"""Create Via (key O), like Virtuoso: pick a via from a menu, then place it with the mouse.

The dialog lists the ASAP7 vias (V0 from LISD or LIG up to M1, V1 ... V8) and the via stacks (e.g.
LIG -> M2 = V0 + V1), with rows and columns for via arrays. After *Place* the via follows the
mouse (centred on it, on the editing grid) and every click drops one - an OpenLayout_ASAP7 `via`
PCell instance, whose rows / columns / layers can be changed later with Q. Esc or a right click
ends placing.

Not a KLayout mode: while placing, this service holds the mouse grab, so it sees the clicks first.
"""
import pya

from .pcells import LIBRARY, via_choices, via_geometry

NAME = "openlayout_via"
PREVIEW_COLOR = 0x4FA3FF
_under_mouse = None             # (tool, point) of the view the mouse was last over
last = {"layers": "m1-m2", "rows": 1, "cols": 1}


def ask_via(parent, current):
    """The Create Via dialog: {"layers", "rows", "cols"} or None (cancelled)."""
    dlg = pya.QDialog(parent)
    dlg.windowTitle = "Create Via"
    lay = pya.QVBoxLayout(dlg)
    lay.addWidget(pya.QLabel("Via:", dlg))
    lst = pya.QListWidget(dlg)
    values = []
    for title, value in via_choices():
        lst.addItem(title)
        values.append(value)
    lst.currentRow = values.index(current["layers"]) if current["layers"] in values else 0
    lst.setMinimumWidth(320)
    lst.setMinimumHeight(360)
    lay.addWidget(lst)
    grid = pya.QHBoxLayout()
    grid.addWidget(pya.QLabel("Rows:", dlg))
    rows = pya.QSpinBox(dlg)
    rows.setRange(1, 32)
    rows.value = int(current["rows"])
    grid.addWidget(rows)
    grid.addWidget(pya.QLabel("Columns:", dlg))
    cols = pya.QSpinBox(dlg)
    cols.setRange(1, 32)
    cols.value = int(current["cols"])
    grid.addWidget(cols)
    lay.addLayout(grid)
    buttons = pya.QDialogButtonBox(dlg)
    place = buttons.addButton("Place", pya.QDialogButtonBox.AcceptRole)
    buttons.addButton(pya.QDialogButtonBox.Cancel)
    buttons.accepted = lambda: dlg.accept()
    buttons.rejected = lambda: dlg.reject()
    lst.itemDoubleClicked = lambda item: dlg.accept()
    place.setDefault(True)
    lay.addWidget(buttons)
    if dlg.exec_() != 1 or lst.currentRow < 0:          # 1 = QDialog::Accepted
        return None
    return {"layers": values[lst.currentRow], "rows": rows.value, "cols": cols.value}


def create_via():
    """The O key: choose a via, then place it where the mouse is."""
    if _under_mouse is None:
        return
    tool, _ = _under_mouse
    view = tool._view
    cv = view.active_cellview()
    if not view.is_editable() or not cv.is_valid() or cv.cell is None:
        return
    mw = pya.Application.instance().main_window()
    choice = ask_via(mw, last)
    if choice is None:
        return
    last.update(choice)
    tool.begin(choice)


class ViaPlacer(pya.Plugin):
    def __init__(self, view):
        super().__init__()
        self._view = view
        self.active = False
        self.params = None
        self.boxes = []          # (layer, DBox) of the via, centred on (0, 0)
        self.markers = []
        self.point = None

    def status(self, text):
        mw = pya.Application.instance().main_window()
        if mw is not None:
            mw.message(text, 10000)

    def begin(self, params):
        self.params = dict(params)
        geo = via_geometry(*params["layers"].split("-"), params["rows"], params["cols"])
        self.boxes = [(layer, pya.DBox(b[0] / 1000, b[1] / 1000, b[2] / 1000, b[3] / 1000))
                      for layer, bs in geo["shapes"].items() for b in bs]
        self.active = True
        self.grab_mouse()
        self.show(self.point)
        b, t = params["layers"].split("-")
        self.status(f"Via {b.upper()} → {t.upper()} {params['rows']}x{params['cols']}: click to place, "
                    "Esc or right click to finish")

    def finish(self):
        self.active = False
        self.markers = []
        self.ungrab_mouse()

    def show(self, p):
        if p is None:
            self.markers = []
            return
        if len(self.markers) != len(self.boxes):
            self.markers = []
            for layer, _ in self.boxes:
                m = pya.Marker(self._view)
                m.color = PREVIEW_COLOR
                m.line_width = 1
                m.dither_pattern = 1 if not layer.startswith("v") else 0
                self.markers.append(m)
        t = pya.DTrans(p.x, p.y)
        for m, (_, box) in zip(self.markers, self.boxes):
            m.set(t * box)

    def place(self, p):
        view = self._view
        cv = view.active_cellview()
        layout, cell = cv.layout(), cv.cell
        local = cv.context_dtrans().inverted() * p
        params = {"layers": self.params["layers"], "rows": self.params["rows"], "cols": self.params["cols"]}
        view.transaction("Place via")
        try:
            pc = layout.create_cell("via", LIBRARY, params)
            cell.insert(pya.DCellInstArray(pc.cell_index(), pya.DTrans(local.x, local.y)))
        finally:
            view.commit()

    # ---- events -----------------------------------------------------------------------------------
    def mouse_moved_event(self, p, buttons, prio):
        global _under_mouse
        _under_mouse = (self, p)
        if not (self.active and prio):
            self.point = p
            return False
        self.point = self.snap(p)
        self.show(self.point)
        return True

    def mouse_click_event(self, p, buttons, prio):
        if not (self.active and prio):
            return False
        if buttons & pya.ButtonState.RightButton:
            self.finish()
            self.status("Via placing finished")
            return True
        if buttons & pya.ButtonState.LeftButton:
            self.place(self.snap(p))
        return True

    def mouse_button_pressed_event(self, p, buttons, prio):
        return self.active and prio      # no drags / selection boxes while placing

    def mouse_button_released_event(self, p, buttons, prio):
        return self.active and prio

    def drag_cancel(self):              # Esc
        if self.active:
            self.finish()
            self.status("Via placing finished")

    def deactivated(self):
        if self.active:
            self.finish()


class ViaPlacerFactory(pya.PluginFactory):
    def __init__(self):
        super().__init__()
        self.has_tool_entry = False
        self.register(-1150, NAME, "")

    def create_plugin(self, manager, root, view):
        return ViaPlacer(view)
