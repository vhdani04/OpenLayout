# $description: OpenLayout look and feel
# $autorun
# $show-in-menu: false
#
# OpenLayout look & feel for KLayout: dark UI from share/theme/openlayout.json, Virtuoso Layout
# Suite key bindings, an OpenLayout menu (cross-tool navigation through the hub) and an
# LSW-style layer palette.  Set OPENLAYOUT_KEYS=klayout to keep KLayout's own key bindings.
import json
import os
import subprocess

import pya

FLOW = os.environ.get("OPENLAYOUT_HOME", os.path.expanduser("~/openlayout/flow"))
THEME = json.load(open(os.path.join(FLOW, "share", "theme", "openlayout.json")))
UI, CANVAS = THEME["ui"], THEME["canvas"]

# KLayout menu path -> Virtuoso key.  Interactive move/copy are KLayout's "secret" actions that
# work like Virtuoso's m/c (pick a reference point, then the destination).
VIRTUOSO_KEYS = {
    "edit_menu.mode_menu.box": "R",
    "edit_menu.mode_menu.path": "P",
    "edit_menu.mode_menu.polygon": "Shift+P",
    "edit_menu.mode_menu.instance": "I",
    "edit_menu.mode_menu.text": "L",
    "edit_menu.mode_menu.ruler": "K",
    "edit_menu.mode_menu.partial": "S",
    "edit_menu.clear_all_rulers": "Shift+K",
    "@secrets.sel_move_interactive": "M",
    "@secrets.duplicate_interactive": "C",
    "edit_menu.show_properties": "Q",
    "edit_menu.undo": "U",
    "edit_menu.redo": "Shift+U",
    "edit_menu.select_menu.select_all": "Ctrl+A",
    "zoom_menu.zoom_fit": "F",
    "zoom_menu.zoom_in": "Ctrl+Z",
    "zoom_menu.zoom_out": "Shift+Z",
    "zoom_menu.max_hier": "Shift+F",
    "zoom_menu.max_hier_0": "Ctrl+F",
    "zoom_menu.descend_into": "X",
    "zoom_menu.ascend": "B",
    "zoom_menu.select_current_cell": "",
    "file_menu.save": "Ctrl+S",
}

KEYS_HELP = """Virtuoso-style keys (KLayout)
  r        rectangle            p / Shift+p   path / polygon
  i        instance             l             label
  k        ruler                Shift+k       clear rulers
  m        move                 c             copy
  s        stretch (partial)    q             properties
  u        undo                 Shift+u       redo
  f        fit                  Ctrl+z/Shift+z  zoom in / out
  Shift+f  show all levels      Ctrl+f        top level only
  x        descend into cell    b             return (ascend)
  Del      delete               Esc           cancel
  Ctrl+s   save
OpenLayout menu: open schematic/symbol, show in Library Manager, LSW"""


def qcolor(hex_color):
    return pya.QColor(hex_color)


def apply_theme(mw):
    pal = pya.QPalette()
    roles = [("Window", "window"), ("Base", "base"), ("AlternateBase", "alt"), ("Button", "panel"),
             ("ToolTipBase", "panel"), ("Text", "text"), ("WindowText", "text"), ("ButtonText", "text"),
             ("ToolTipText", "text"), ("Highlight", "select"), ("Link", "accent")]
    for role, key in roles:
        pal.setColor(getattr(pya.QPalette, role), qcolor(UI[key]))
    pal.setColor(pya.QPalette.HighlightedText, qcolor("#ffffff"))
    for role in ("Text", "WindowText", "ButtonText"):
        pal.setColor(pya.QPalette.Disabled, getattr(pya.QPalette, role), qcolor(UI["dim"]))
    pya.QApplication.setStyle("Fusion")
    pya.QApplication.setPalette(pal)
    mw.setStyleSheet(
        f"QToolBar {{ background: {UI['panel']}; border: none; border-bottom: 1px solid {UI['border']}; }}"
        f"QDockWidget::title {{ background: {UI['panel']}; padding: 4px; }}"
        f"QStatusBar {{ background: {UI['panel']}; border-top: 1px solid {UI['border']}; }}"
        f"QMenu::item:selected, QMenuBar::item:selected {{ background: {UI['select']}; }}")
    for name, value in {"background-color": CANVAS["background"], "grid-color": CANVAS["grid"],
                        "grid-grid-color": CANVAS["grid"], "grid-axis-color": CANVAS["axis"],
                        "grid-ruler-color": CANVAS["text"], "sel-color": CANVAS["selection"],
                        "ruler-color": CANVAS["ruler"], "crosshair-cursor-color": CANVAS["cursor"],
                        "text-color": CANVAS["text"]}.items():
        mw.set_config(name, value)


def apply_keys(mw):
    if os.environ.get("OPENLAYOUT_KEYS") == "klayout":
        return
    # Free keys that Virtuoso uses for something else before assigning them.
    taken = {v for v in VIRTUOSO_KEYS.values() if v}
    current = mw.get_key_bindings()
    clear = {path: "" for path, key in current.items() if key in taken and path not in VIRTUOSO_KEYS}
    mw.set_key_bindings({**clear, **VIRTUOSO_KEYS})


# ---- cross-tool navigation (through the OpenLayout hub) --------------------------------------

def hubcmd(mw, cmd, *args):
    view = mw.current_view()
    cv = view.active_cellview() if view else None
    if cv is None or not cv.is_valid() or not cv.filename():
        pya.MessageBox.warning("OpenLayout", "Open a layout first.", pya.MessageBox.Ok)
        return
    argv = ["openlayout", "hubcmd", cmd, cv.filename(), *args, "--cell", cv.cell_name]
    try:
        res = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            pya.MessageBox.warning("OpenLayout", (res.stdout + res.stderr).strip(), pya.MessageBox.Ok)
    except Exception as e:
        pya.MessageBox.warning("OpenLayout", str(e), pya.MessageBox.Ok)


# ---- LSW: Virtuoso-style layer selection window ---------------------------------------------

class LSW:
    """Drawing layers with swatches. Click = current drawing layer, checkbox = visibility."""

    def __init__(self, mw):
        self.mw = mw
        self.iters, self.items = [], []
        self.dock = pya.QDockWidget("LSW", mw)
        self.dock.objectName = "openlayout_lsw"
        body = pya.QWidget(self.dock)
        lay = pya.QVBoxLayout(body)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.current = pya.QLabel("current: —", body)
        lay.addWidget(self.current)
        row = pya.QHBoxLayout()
        for label, slot in (("AV", lambda: self.set_all(True)), ("NV", lambda: self.set_all(False))):
            b = pya.QPushButton(label, body)
            b.toolTip = "All visible" if label == "AV" else "None visible"
            b.clicked = slot
            row.addWidget(b)
        self.used = pya.QCheckBox("Used", body)
        self.used.toolTip = "Only layers with shapes in this view"
        self.used.toggled = lambda _on: self.refresh()
        row.addWidget(self.used)
        lay.addLayout(row)
        self.list = pya.QListWidget(body)
        self.list.iconSize = pya.QSize(30, 14)
        self.list.itemClicked = self.on_click
        self.list.itemChanged = self.on_check
        lay.addWidget(self.list)
        self.dock.setWidget(body)
        mw.addDockWidget(pya.Qt.LeftDockWidgetArea, self.dock)
        mw.on_current_view_changed += self.on_view_changed
        self.hooked = set()
        self.refresh()

    def on_view_changed(self):
        view = self.mw.current_view()
        if view is not None and id(view) not in self.hooked:
            view.on_layer_list_changed += lambda _flags: self.refresh()
            view.on_active_cellview_changed += self.refresh
            self.hooked.add(id(view))
        self.refresh()

    def swatch(self, lp):
        pm = pya.QPixmap(30, 14)
        pm.fill(qcolor(UI["base"]))
        p = pya.QPainter(pm)
        fill = qcolor("#%06x" % (lp.eff_fill_color(True) & 0xFFFFFF))
        frame = qcolor("#%06x" % (lp.eff_frame_color(True) & 0xFFFFFF))
        dither = lp.eff_dither_pattern(True)
        if dither != 1:  # 1 = hollow
            style = pya.Qt.SolidPattern if dither == 0 else pya.Qt.Dense4Pattern
            p.fillRect(1, 1, 28, 12, pya.QBrush(fill, style))
        p.setPen(pya.QPen(frame))
        p.drawRect(0, 0, 29, 13)
        p.end()
        return pya.QIcon(pm)

    def refresh(self):
        view = self.mw.current_view()
        self.list.blockSignals(True)
        self.list.clear()
        self.iters, self.items = [], []
        if view is not None:
            it = view.begin_layers()
            while not it.at_end():
                lp = it.current()
                # Top-level leaf entries are the drawing layers (pins/labels/... live in groups).
                if not lp.has_children() and (not self.used.isChecked() or not lp.bbox().empty()):
                    item = pya.QListWidgetItem(self.swatch(lp), lp.name or lp.source)
                    item.flags = item.flags | pya.Qt.ItemIsUserCheckable
                    item.setCheckState(pya.Qt.Checked if lp.visible else pya.Qt.Unchecked)
                    self.list.addItem(item)
                    self.items.append(item)  # keep Python references alive alongside Qt's
                    self.iters.append(it.dup())
                it.next_sibling(1)
            cur = view.current_layer
            if not cur.is_null() and not cur.at_end():
                self.current.text = f"current: {cur.current().name}"
        self.list.blockSignals(False)

    def on_click(self, item):
        view = self.mw.current_view()
        row = self.list.row(item)
        if view is not None and 0 <= row < len(self.iters):
            view.current_layer = self.iters[row]
            self.current.text = f"current: {item.text}"

    def on_check(self, item):
        view = self.mw.current_view()
        row = self.list.row(item)
        if view is not None and 0 <= row < len(self.iters):
            lp = self.iters[row].current().dup()
            lp.visible = item.checkState == pya.Qt.Checked
            view.set_layer_properties(self.iters[row], lp)

    def set_all(self, visible):
        view = self.mw.current_view()
        if view is None:
            return
        for it in self.iters:
            lp = it.current().dup()
            lp.visible = visible
            view.set_layer_properties(it, lp)
        self.refresh()


class OpenLayoutUI:
    def __init__(self, mw):
        self.mw = mw
        self.actions = []
        for step in (apply_theme, apply_keys):
            try:
                step(mw)
            except Exception as e:
                print(f"OpenLayout: {step.__name__} failed: {e}")
        self.lsw = None
        try:
            self.lsw = LSW(mw)
        except Exception as e:
            print(f"OpenLayout: LSW failed: {e}")
        self.build_menu()

    def action(self, title, fn, shortcut=None):
        a = pya.Action()
        a.title = title
        if shortcut:
            a.shortcut = shortcut
        a.on_triggered += fn
        self.actions.append(a)
        return a

    def build_menu(self):
        menu = self.mw.menu()
        menu.insert_menu("help_menu", "openlayout_menu", "OpenLayout")
        items = [
            ("open_schematic", self.action("Open Schematic", lambda: hubcmd(self.mw, "open", "schematic"))),
            ("open_symbol", self.action("Open Symbol", lambda: hubcmd(self.mw, "open", "symbol"))),
            ("show_in_lm", self.action("Show in Library Manager", lambda: hubcmd(self.mw, "select"))),
            (None, None),
            ("lsw", self.action("Show LSW", self.show_lsw)),
            ("keys", self.action("Virtuoso Keys…", lambda: pya.MessageBox.info("OpenLayout keys", KEYS_HELP,
                                                                             pya.MessageBox.Ok))),
        ]
        for i, (name, action) in enumerate(items):
            if name is None:
                menu.insert_separator("openlayout_menu.end", f"sep{i}")
            else:
                menu.insert_item("openlayout_menu.end", name, action)

    def show_lsw(self):
        if self.lsw:
            self.lsw.dock.show()
            self.lsw.dock.raise_()


_mw = pya.Application.instance().main_window()
if _mw is not None and os.environ.get("OPENLAYOUT_UI", "1") != "0":
    openlayout_ui = OpenLayoutUI(_mw)
