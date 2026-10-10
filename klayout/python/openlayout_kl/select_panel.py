"""Select: the dock window that sets what can be selected in the layout (picking.py).

One switch per object type - instances (transistors, cells), vias, shapes, pins, labels, the
boundary, the standard-cell frame - with presets (All, Shapes only), and the locked layers (locked
in the LSW: right-click a layer, AS / NS) with a button to unlock them. Turning a type off also
drops it from the current selection.
"""
import pya

from . import picking


class SelectPanel:
    def __init__(self, mw: pya.MainWindow, ui: dict):
        self.mw = mw
        self.ui = ui
        self.boxes = {}
        self._syncing = False

        self.dock = pya.QDockWidget("Select", mw)
        self.dock.objectName = "openlayout_select"
        body = pya.QWidget(self.dock)
        lay = pya.QVBoxLayout(body)
        lay.setContentsMargins(6, 4, 6, 6)
        lay.setSpacing(2)

        head = pya.QLabel("Selectable in the layout", body)
        head.styleSheet = "font-weight: 600; padding: 2px 0 4px 0;"
        lay.addWidget(head)
        for key, label in picking.TYPES:
            b = pya.QCheckBox(label, body)
            b.checked = picking.types[key]
            b.toggled = lambda on, key=key: self.set_type(key, on)
            lay.addWidget(b)
            self.boxes[key] = b

        row = pya.QHBoxLayout()
        for label, tip, slot in (("All", "Every type selectable", self.all_types),
                                 ("Shapes only", "Shapes, pins and labels - not instances, vias or the frame",
                                  self.shapes_only)):
            btn = pya.QPushButton(label, body)
            btn.toolTip = tip
            btn.clicked = slot
            row.addWidget(btn)
        lay.addSpacing(4)
        lay.addLayout(row)

        lay.addSpacing(6)
        locks = pya.QHBoxLayout()
        self.locked = pya.QLabel("", body)
        self.unlock = pya.QPushButton("Unlock all layers", body)
        self.unlock.toolTip = "Layers are locked in the LSW: right-click a layer, or AS / NS"
        self.unlock.clicked = self.unlock_layers
        locks.addWidget(self.locked, 1)
        locks.addWidget(self.unlock)
        lay.addLayout(locks)

        hint = pya.QLabel("Click the same spot again for the next object underneath.", body)
        hint.wordWrap = True
        hint.styleSheet = f"color: {ui['dim']}; padding-top: 6px;"
        lay.addWidget(hint)
        lay.addStretch(1)

        self.dock.setWidget(body)
        mw.addDockWidget(pya.Qt.RightDockWidgetArea, self.dock)
        picking.listeners.append(self.sync)
        self.sync()

    # ---- state -> widgets -------------------------------------------------------------------
    def sync(self):
        self._syncing = True
        try:
            for key, b in self.boxes.items():
                if b.checked != picking.types[key]:
                    b.checked = picking.types[key]
            n = len(picking.locked)
            self.locked.text = f"Locked layers: {n}" if n else "No layers locked"
            self.unlock.enabled = bool(n)
        finally:
            self._syncing = False

    # ---- widgets -> state -------------------------------------------------------------------
    def set_type(self, key, on):
        if self._syncing:
            return
        picking.types[key] = bool(on)
        self.drop_unselectable()
        picking.changed()

    def all_types(self):
        for k in picking.types:
            picking.types[k] = True
        picking.changed()

    def shapes_only(self):
        for k in picking.types:
            picking.types[k] = k in ("shape", "pin", "label")
        self.drop_unselectable()
        picking.changed()

    def unlock_layers(self):
        picking.locked.clear()
        picking.changed()

    def drop_unselectable(self):
        """what is selected now and no longer can be is unselected"""
        view = self.mw.current_view()
        if view is None:
            return
        sel = list(view.each_object_selected())
        keep = [o for o in sel if picking.allowed(view, o)]
        if len(keep) != len(sel):
            view.object_selection = keep
