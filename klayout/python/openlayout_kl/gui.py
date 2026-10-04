"""OpenLayout inside KLayout: theme and preferences, Virtuoso keys, drag-and-drop and align, the path tool,
the ASAP7 PCell library, the LSW and Connectivity panels, and the OpenLayout menu (incl.
schematic-driven layout)."""
import json
import os
import re
import subprocess
from pathlib import Path

import pya

from . import generate as gen
from . import align_tool, axes, drc, drd, generate_form, lvs, stdcell, vias
from .drag_move import DragMoveFactory, after_move_hooks, move_under_mouse, stretch_under_mouse
from .lsw import LSW
from .nets_panel import NetsPanel
from .path_tool import TOOL_NAME, PathToolFactory
from .pcells import register_library

FLOW = Path(os.environ.get("OPENLAYOUT_HOME", Path.home() / "openlayout/flow"))
THEME = json.loads((FLOW / "share" / "theme" / "openlayout.json").read_text())
UI, CANVAS = THEME["ui"], THEME["canvas"]

# KLayout menu path -> Virtuoso key. Interactive copy is KLayout's "secret" action that works like
# Virtuoso's c; m / s are OpenLayout's move / stretch of what is under the mouse (see drag_move),
# a is align (align_tool), o is Create Via (vias). P is bound to OpenLayout's path tool once it is
# registered (see bind_path_tool).
VIRTUOSO_KEYS = {
    "edit_menu.mode_menu.box": "R",
    "edit_menu.mode_menu.polygon": "Shift+P",
    "edit_menu.mode_menu.instance": "I",
    "edit_menu.mode_menu.text": "L",
    "edit_menu.mode_menu.ruler": "K",
    "openlayout_menu.stretch": "S",
    "edit_menu.clear_all_rulers": "Shift+K",
    "openlayout_menu.move": "M",
    "openlayout_menu.align": "A",
    "openlayout_menu.via": "O",
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

PREFS = {
    # Dotted grid at every zoom level (no grid lines).
    "grid-style1": "dots",
    "grid-style2": "dots",
    # Manhattan editing: path/polygon segments and move/stretch only along the axes.
    "edit-connect-angle-mode": "ortho",
    "edit-move-angle-mode": "ortho",
    # Like Virtuoso: clicking on a transistor/instance selects the instance, not a shape inside it.
    "edit-top-level-selection": "true",
    # The LSW replaces KLayout's layer panel and layer toolbox (one layer panel only).
    "show-layer-panel": "false",
    "show-layer-toolbox": "false",
    # Rulers: a dark halo around line and text keeps the (vivid orange) ruler readable over any layer.
    "ruler-halo": "true",
}


def apply_theme(mw):
    pal = pya.QPalette()
    roles = [("Window", "window"), ("Base", "base"), ("AlternateBase", "alt"), ("Button", "panel"),
             ("ToolTipBase", "panel"), ("Text", "text"), ("WindowText", "text"), ("ButtonText", "text"),
             ("ToolTipText", "text"), ("Highlight", "select"), ("Link", "accent")]
    for role, key in roles:
        pal.setColor(getattr(pya.QPalette, role), pya.QColor(UI[key]))
    pal.setColor(pya.QPalette.HighlightedText, pya.QColor("#ffffff"))
    for role in ("Text", "WindowText", "ButtonText"):
        pal.setColor(pya.QPalette.Disabled, getattr(pya.QPalette, role), pya.QColor(UI["dim"]))
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


# KLayout's default ruler templates (0.30), used when the profile has none stored yet.
DEFAULT_RULER_TEMPLATES = (
    "mode=normal,title=Ruler,category=_ruler,version=1,fmt=$D,fmt_x=$X,fmt_y=$Y,position=auto,xalign=auto,"
    "yalign=auto,xlabel_xalign=auto,xlabel_yalign=auto,ylabel_xalign=auto,ylabel_yalign=auto,style=ruler,"
    "outline=diag,snap=true,angle_constraint=global;"
    "mode=multi_segment,title='Multi-ruler',category=_multi_ruler,version=1,fmt=$D,fmt_x=$X,fmt_y=$Y,"
    "position=auto,xalign=auto,yalign=auto,xlabel_xalign=auto,xlabel_yalign=auto,ylabel_xalign=auto,"
    "ylabel_yalign=auto,style=ruler,outline=diag,snap=true,angle_constraint=global;"
    "mode=single_click,title=Cross,category=_cross,version=1,fmt='$U,$V',fmt_x='',fmt_y='',position=auto,"
    "xalign=auto,yalign=auto,xlabel_xalign=auto,xlabel_yalign=auto,ylabel_xalign=auto,ylabel_yalign=auto,"
    "style=cross_both,outline=diag,snap=true,angle_constraint=global;"
    "mode=auto_metric,title=Measure,category=_measure,version=1,fmt=$D,fmt_x=$X,fmt_y=$Y,position=auto,"
    "xalign=auto,yalign=auto,xlabel_xalign=auto,xlabel_yalign=auto,ylabel_xalign=auto,ylabel_yalign=auto,"
    "style=ruler,outline=diag,snap=true,angle_constraint=global;"
    "mode=auto_metric_edge,title='Measure edge',category=_measure_edge,version=1,fmt=$D,fmt_x=$X,fmt_y=$Y,"
    "position=auto,xalign=auto,yalign=auto,xlabel_xalign=auto,xlabel_yalign=auto,ylabel_xalign=auto,"
    "ylabel_yalign=auto,style=ruler,outline=diag,snap=true,angle_constraint=global"
)


def apply_prefs(mw):
    for name, value in PREFS.items():
        mw.set_config(name, value)
    # Rulers: distance-type rulers only along the axes (angle/radius/ellipse tools stay free).
    templates = mw.get_config("ruler-templates-v2") or DEFAULT_RULER_TEMPLATES
    fixed = re.sub(r"(mode=(?:normal|multi_segment|auto_metric|auto_metric_edge),title=(?:Ruler|'Multi-ruler'|"
                   r"Measure|'Measure edge')[^;]*?)angle_constraint=global", r"\1angle_constraint=ortho", templates)
    mw.set_config("ruler-templates-v2", fixed)


def apply_keys(mw):
    if os.environ.get("OPENLAYOUT_KEYS") == "klayout":
        return
    taken = {v for v in VIRTUOSO_KEYS.values() if v}
    current = mw.get_key_bindings()
    clear = {path: "" for path, key in current.items() if key in taken and path not in VIRTUOSO_KEYS}
    mw.set_key_bindings({**clear, **VIRTUOSO_KEYS})


def bind_path_tool(mw):
    """Give P to OpenLayout's path tool and hide KLayout's own path mode (one Path in the toolbar)."""
    menu = mw.menu()
    ours = f"edit_menu.mode_menu.{TOOL_NAME}"
    if ours not in menu.items("edit_menu.mode_menu"):
        return
    for builtin in ("edit_menu.mode_menu.path", "@toolbar.path"):
        if menu.is_valid(builtin):
            menu.action(builtin).visible = False
    if os.environ.get("OPENLAYOUT_KEYS") != "klayout":
        current = mw.get_key_bindings()
        clear = {p: "" for p, k in current.items() if k == "P" and p != ours}
        mw.set_key_bindings({**clear, ours: "P"})


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


class OpenLayoutUI:
    def __init__(self, mw):
        self.mw = mw
        self.actions = []
        register_library()
        for step in (apply_theme, apply_prefs, apply_keys):
            try:
                step(mw)
            except Exception as e:
                print(f"OpenLayout: {step.__name__} failed: {e}")
        self.path_factory = PathToolFactory()
        if os.environ.get("OPENLAYOUT_KEYS") != "klayout":
            self.drag_factory = DragMoveFactory()   # Virtuoso drag and drop in Select mode
        self.align_factory = align_tool.AlignToolFactory()
        self.via_factory = vias.ViaPlacerFactory()
        self.axes_factory = axes.AxesFactory(int(CANVAS["axis"].lstrip("#"), 16))
        after_move_hooks.append(self.after_move)
        try:
            bind_path_tool(mw)
        except Exception as e:
            print(f"OpenLayout: path tool binding failed: {e}")
        self.lsw = LSW(mw, UI)
        self.nets = NetsPanel(mw, UI, on_update=self.update_layout_file)
        mw.splitDockWidget(self.lsw.dock, self.nets.dock, pya.Qt.Vertical)
        self.build_menu()
        try:
            apply_keys(mw)    # again: the OpenLayout menu entries (m) exist now
        except Exception as e:
            print(f"OpenLayout: key binding failed: {e}")

    # ---- schematic-driven layout ------------------------------------------------------------
    def open_views(self):
        out = {}
        for i in range(self.mw.views()):
            view = self.mw.view(i)
            for ci in range(view.cellviews()):
                cv = view.cellview(ci)
                if cv.filename():
                    out[os.path.realpath(cv.filename())] = (i, cv)
        return out

    def generate_for(self, schematic, ask=False):
        """Generate/update the layout of a schematic's cell inside this session and show it. With
        ask, the Generate Layout form chooses the pins (and their layers) and the frame first;
        returns None if it is cancelled."""
        sch = Path(schematic).resolve()
        gds = sch.with_suffix(".gds")
        opened = self.open_views().get(os.path.realpath(gds))
        options = {}
        if ask:
            info = gen.read_schematic(sch)
            table = gen.pin_table(info, opened[1].layout() if opened is not None else None)
            choice = generate_form.ask_generate(self.mw, info["cell"].name, table)
            if choice is None:
                return None
            options = {"pins": choice["pins"], "frame": choice["frame"], "info": info}
        if opened is not None:
            index, cv = opened
            self.mw.select_view(index)
            view = self.mw.current_view()
            view.transaction("Update layout from schematic")
            try:
                report = gen.generate(sch, layout=cv.layout(), **options)
            finally:
                view.commit()
        else:
            report = gen.generate(sch, **options)
            self.mw.load_layout(str(gds), "asap7", 1)
        view = self.mw.current_view()
        cv = view.active_cellview()
        top = cv.layout().cell(report["cell"])
        if top is not None:
            view.select_cell(top.cell_index(), cv.index())
        view.max_hier()
        view.zoom_fit()
        self.nets.run_check(force=True)
        self.mw.message(self.describe(report), 10000)
        return report

    @staticmethod
    def describe(report):
        parts = [f"{len(report['added'])} added", f"{len(report['updated'])} updated"]
        if report["pins_added"]:
            parts.append(f"{len(report['pins_added'])} pins")
        if report["extra"]:
            parts.append(f"not in schematic: {', '.join(report['extra'])}")
        if report["skipped"]:
            parts.append(f"skipped: {', '.join(report['skipped'])}")
        if report.get("warnings"):
            parts.append("; ".join(report["warnings"]))
        return f"{report['cell']}: " + ", ".join(parts)

    def update_layout_file(self, layout_path):
        sch = Path(layout_path).with_suffix(".sch")
        if not sch.is_file():
            pya.MessageBox.warning("OpenLayout", f"No schematic {sch.name} next to this layout.", pya.MessageBox.Ok)
            return
        try:
            self.generate_for(sch, ask=True)
        except Exception as e:
            pya.MessageBox.warning("OpenLayout", f"Update from schematic failed:\n{e}", pya.MessageBox.Ok)

    def update_current(self):
        view = self.mw.current_view()
        cv = view.active_cellview() if view else None
        if cv is None or not cv.is_valid() or not cv.filename():
            pya.MessageBox.info("OpenLayout", "Open the cell's layout first, or use Generate Layout in the hub "
                                "or in xschem's OpenLayout menu.", pya.MessageBox.Ok)
            return
        self.update_layout_file(cv.filename())

    # ---- menu --------------------------------------------------------------------------------
    def action(self, title, fn, shortcut=None):
        a = pya.Action()
        a.title = title
        if shortcut:
            a.shortcut = shortcut
        a.on_triggered += lambda: self.run(title, fn)
        self.actions.append(a)
        return a

    @staticmethod
    def run(title, fn):
        """Menu commands report failures (KLayout would only log them)."""
        try:
            fn()
        except Exception as e:
            print(f"OpenLayout: {title} failed: {e}")
            pya.MessageBox.warning("OpenLayout", f"{title.rstrip('…')} failed:\n{type(e).__name__}: {e}",
                                   pya.MessageBox.Ok)

    def build_menu(self):
        menu = self.mw.menu()
        menu.insert_menu("help_menu", "openlayout_menu", "OpenLayout")
        items = [
            ("update_from_schematic", self.action("Generate / Update Layout from Schematic", self.update_current)),
            ("check_connectivity", self.action("Check Connectivity", lambda: self.nets.run_check(force=True))),
            ("run_drc", self.action("Run DRC", lambda: drc.run_current(self.mw))),
            ("run_lvs", self.action("Run LVS", lambda: lvs.run_current(self.mw))),
            (None, None),
            ("open_schematic", self.action("Open Schematic", lambda: hubcmd(self.mw, "open", "schematic"))),
            ("open_symbol", self.action("Open Symbol", lambda: hubcmd(self.mw, "open", "symbol"))),
            ("show_in_lm", self.action("Show in Library Manager", lambda: hubcmd(self.mw, "select"))),
            (None, None),
            ("lsw", self.action("Show LSW", lambda: (self.lsw.dock.show(), self.lsw.dock.raise_()))),
            ("connectivity", self.action("Show Connectivity", lambda: (self.nets.dock.show(), self.nets.dock.raise_()))),
            ("keys", self.action("Virtuoso Keys…", self.show_keys)),
            ("axes", self.axes_action()),
            ("drd", self.drd_action()),
            (None, None),
            ("move", self.action("Move (object under the mouse)", move_under_mouse)),
            ("stretch", self.action("Stretch (edge under the mouse)", stretch_under_mouse)),
            ("align", self.action("Align (edge to edge)", align_tool.start)),
            ("via", self.action("Create Via…", vias.create_via)),
            (None, None),
            ("stdcell_frame", self.action("Standard-Cell Frame…", self.frame_dialog)),
            ("chain", self.action("Chain Selected Transistors", self.chain_selected)),
        ]
        for i, (name, action) in enumerate(items):
            if name is None:
                menu.insert_separator("openlayout_menu.end", f"sep{i}")
            else:
                menu.insert_item("openlayout_menu.end", name, action)

    def axes_action(self):
        a = self.action("Show Axes", lambda: axes.show(a.is_checked()))
        a.checkable = True
        a.checked = axes.visible()
        return a

    def drd_action(self):
        a = self.action("DRD Spacing Hints (while drawing / moving)", lambda: drd.set_enabled(a.is_checked()))
        a.checkable = True
        a.checked = drd.enabled
        return a

    # ---- custom standard cells ------------------------------------------------------------------
    def frame_dialog(self):
        view = self.mw.current_view()
        cv = view.active_cellview() if view else None
        if cv is None or not cv.is_valid() or cv.cell is None or not view.is_editable():
            pya.MessageBox.info("OpenLayout", "Open the (editable) layout of the cell first.", pya.MessageBox.Ok)
            return
        cur = stdcell.frame_params(cv.cell) or {}
        cpp = pya.InputDialog.ask_int_ex("Standard-cell frame",
                                      "Width in gate pitches (54 nm each; 7.5-track cell, 270 nm high):",
                                      int(cur.get("cpp") or stdcell.default_width(cv.cell)), 1, 400, 1)
        if cpp is None:
            return
        vts = ["rvt", "lvt", "slvt"]
        vt = pya.InputDialog.ask_item("Standard-cell frame", "Threshold voltage:", vts,
                                      vts.index(cur.get("vt", "rvt")) if cur.get("vt") in vts else 0)
        if vt is None:
            return
        stdcell.insert_frame(view, cpp, vt)
        self.mw.message(f"Standard-cell frame: {cpp} gate pitches ({cpp * 54} nm) x 270 nm, {vt.upper()} - "
                        "place transistors with 'Standard-cell row' on, at y = 0", 10000)

    def chain_selected(self):
        view = self.mw.current_view()
        if view is None or not view.is_editable():
            return
        messages = stdcell.chain_selected(view)
        self.mw.message("; ".join(messages) if messages else "Transistors chained", 10000)

    def after_move(self, view):
        messages = stdcell.after_move(view)
        if messages:
            self.mw.message("; ".join(messages), 10000)

    def show_keys(self):
        keys = FLOW / "docs" / "KEYS.md"
        pya.MessageBox.info("OpenLayout keys", keys.read_text() if keys.is_file() else "docs/KEYS.md missing",
                            pya.MessageBox.Ok)


instance = None


def start(mw):
    global instance
    if instance is None and mw is not None:
        instance = OpenLayoutUI(mw)
    return instance
