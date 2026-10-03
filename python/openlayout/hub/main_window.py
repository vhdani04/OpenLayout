"""OpenLayout hub main window: Library Manager on top, CIW below."""
import json
import os
import re
import threading
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu,
                               QMessageBox, QSplitter, QStyle, QTextBrowser, QVBoxLayout, QWidget)

from .. import __version__
from ..tools import KLayoutBridge, XschemBridge, netlist_command, simulate_command
from ..workarea import Cell, View, Workarea, WorkareaError, view_type
from . import theme
from .ciw import CIW
from .dialogs import CopyCellDialog, NewCellViewDialog
from .library_manager import LibraryManager

SIM_FAIL_RE = re.compile(r"^(Error\b|.*\bFAIL\b)", re.M)
SIM_RESULT_RE = re.compile(r"^(PASS|FAIL)\b.*$", re.M)


class HubAPI:
    """OpenLayout commands for the CIW, available as `ol`:

    ol.libs()                         library names
    ol.cells(lib)                     cell names in a library
    ol.views(lib, cell)               view names of a cell
    ol.select(lib, cell=None, view=None)
    ol.open(lib, cell, view=None)     open a view (default: schematic, else layout, else symbol)
    ol.new_lib(name)
    ol.new_view(lib, cell, view="schematic")   view: schematic | symbol | layout
    ol.netlist(lib, cell)             netlist the schematic into sim/netlist/
    ol.sim(lib, cell)                 netlist + ngspice batch run in sim/<lib>/<cell>/
    ol.generate(lib, cell)            generate/update the cell's layout from its schematic (KLayout)
    ol.xschem(tcl)                    send a Tcl command to the running xschem
    ol.klayout(cmd, **args)           send a request to the running KLayout bridge
    ol.wa                             the Workarea object (full Python API)
    """

    def __init__(self, win: "MainWindow"):
        self._win = win

    @property
    def wa(self) -> Workarea:
        if not self._win.workarea:
            raise WorkareaError("no workarea open")
        return self._win.workarea

    def _cell(self, lib: str, cell: str) -> Cell:
        library = self.wa.library(lib)
        c = library.cell(cell) if library else None
        if c is None:
            raise WorkareaError(f"no cell {lib}/{cell}")
        return c

    def libs(self): return [lb.name for lb in self.wa.libraries()]
    def cells(self, lib): return [c.name for c in self.wa.library(lib).cells()]
    def views(self, lib, cell): return [v.name for v in self._cell(lib, cell).views()]
    def select(self, lib, cell=None, view=None): self._win.lm.select(lib, cell, view)

    def open(self, lib, cell, view=None):
        c = self._cell(lib, cell)
        self._win.open_target(c.view(view) if view else c)

    def new_lib(self, name):
        self.wa.new_library(name)
        self._win.lm.refresh()
        self._win.lm.select(name)

    def new_view(self, lib, cell, view="schematic"):
        v = self.wa.new_view(self.wa.library(lib), cell, view_type(view))
        self._win.lm.refresh()
        self._win.lm.select(lib, cell, view)
        return v

    def netlist(self, lib, cell): self._win.netlist(self._cell(lib, cell))
    def sim(self, lib, cell): self._win.simulate(self._cell(lib, cell))
    def generate(self, lib, cell): self._win.generate_layout(self._cell(lib, cell))
    def xschem(self, tcl): return self._win.xschem.send(tcl)
    def klayout(self, cmd, **args): return self._win.klayout.request({"cmd": cmd, **args})

    def __repr__(self):
        return "OpenLayout command API: help(ol)"


class MainWindow(QMainWindow):
    logged = Signal(str, str)  # level, message (thread-safe logging)
    refresh_requested = Signal()  # from worker threads

    def __init__(self, workarea: Workarea | None):
        super().__init__()
        self.settings = QSettings("OpenLayout", "hub")
        self.workarea: Workarea | None = None
        self.xschem: XschemBridge | None = None
        self.klayout: KLayoutBridge | None = None
        self._tool_locks = {"xschem": threading.Lock(), "klayout": threading.Lock()}
        self._proc: QProcess | None = None
        self.api = HubAPI(self)

        self.lm = LibraryManager()
        self.lm.show_pdk = self.settings.value("show_pdk", True, type=bool)
        self.ciw = CIW({"ol": self.api, "hub": self})
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.lm)
        split.addWidget(self.ciw)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.splitter = split
        self.setCentralWidget(split)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self.logged.connect(self.ciw.write)
        self.refresh_requested.connect(self.lm.refresh)
        self.lm.openRequested.connect(self.open_target)
        self.lm.contextRequested.connect(self._context_menu)
        self.lm.selectionChanged.connect(self._update_actions)

        self.resize(1280, 820)
        if self.settings.contains("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
            split.restoreState(self.settings.value("splitter"))
        self.ciw.info(f"OpenLayout {__version__} — Virtuoso-style custom IC design on KLayout, xschem and ngspice")
        self._start_server()
        self.set_workarea(workarea)

    # ---- construction -----------------------------------------------------------------------
    def _act(self, text, slot, shortcut=None, icon=None, tip=None, enabled=True, checkable=False):
        a = QAction(text, self)
        if icon is not None:
            a.setIcon(self.style().standardIcon(icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setStatusTip(tip or text)
        a.setToolTip(tip or text)
        a.setEnabled(enabled)
        a.setCheckable(checkable)
        if slot:
            a.triggered.connect(slot)
        return a

    def _build_actions(self):
        S = QStyle.StandardPixmap
        self.a_new_wa = self._act("New Workarea…", self.new_workarea)
        self.a_open_wa = self._act("Open Workarea…", self.open_workarea, "Ctrl+Shift+O", S.SP_DirOpenIcon)
        self.a_new_lib = self._act("New Library…", self.new_library, "Ctrl+Shift+N", S.SP_FileDialogNewFolder)
        self.a_new_view = self._act("New Cell View…", self.new_cell_view, "Ctrl+N", S.SP_FileIcon,
                                    "Create a schematic, symbol or layout view")
        self.a_refresh = self._act("Refresh", self.lm.refresh, "F5", S.SP_BrowserReload)
        self.a_quit = self._act("Quit", self.close, "Ctrl+Q")
        self.a_open = self._act("Open", self.open_selected, "Ctrl+O", S.SP_DialogOpenButton,
                                "Open the selected view (or the cell's main view)")
        self.a_copy = self._act("Copy Cell…", self.copy_cell, "Ctrl+Shift+C")
        self.a_rename = self._act("Rename Cell…", self.rename_cell, "F2")
        self.a_delete = self._act("Delete…", self.delete_selected, "Del", S.SP_TrashIcon,
                                  "Move the selected view or cell to the workarea trash")
        self.a_netlist = self._act("Netlist", lambda: self.netlist(self.lm.current_cell()), "F7",
                                   S.SP_FileDialogDetailedView, "Netlist the cell's schematic (xschem)")
        self.a_sim = self._act("Simulate", lambda: self.simulate(self.lm.current_cell()), "F8",
                               S.SP_MediaPlay, "Netlist and simulate the cell in ngspice")
        self.a_generate = self._act("Generate Layout", lambda: self.generate_layout(self.lm.current_cell()),
                                    "F9", S.SP_ArrowForward,
                                    "Generate or update the cell's layout from its schematic (Layout XL style)")
        self.a_gensym = self._act("Generate Symbol", lambda: self.generate_symbol(self.lm.current_cell()),
                                  None, None, "Create the cell's symbol from its schematic pins (Virtuoso style)")
        self.a_drc =self._act("DRC", None, None, S.SP_DialogApplyButton, "Design rule check — coming in Phase 5",
                               enabled=False)
        self.a_lvs = self._act("LVS", None, None, S.SP_DialogYesButton,
                               "Layout vs. schematic — coming in Phase 6", enabled=False)
        self.a_pex = self._act("PEX", None, None, None, "Parasitic extraction — coming in Phase 6", enabled=False)
        self.a_start_xs = self._act("Start xschem", lambda: self._start_tool("xschem"))
        self.a_start_kl = self._act("Start KLayout", lambda: self._start_tool("klayout"))
        self.a_show_pdk = self._act("Show PDK Libraries", self._toggle_pdk, checkable=True)
        self.a_show_pdk.setChecked(self.lm.show_pdk)
        self.a_help_cmds = self._act("CIW Commands", lambda: self._run_ciw("help(ol)"))
        self.a_keys = self._act("Virtuoso Keys", self.show_keys, "F1")
        self.a_about = self._act("About OpenLayout", self.about)

    def _build_menus(self):
        mb = self.menuBar()
        for title, actions in [
            ("&File", [self.a_new_wa, self.a_open_wa, None, self.a_new_lib, self.a_new_view, None,
                       self.a_refresh, None, self.a_quit]),
            ("&Edit", [self.a_open, None, self.a_copy, self.a_rename, self.a_delete]),
            ("&Tools", [self.a_netlist, self.a_sim, self.a_generate, self.a_gensym, None, self.a_drc, self.a_lvs, self.a_pex, None,
                        self.a_start_xs, self.a_start_kl]),
            ("&View", [self.a_show_pdk]),
            ("&Help", [self.a_keys, self.a_help_cmds, self.a_about]),
        ]:
            m = mb.addMenu(title)
            for a in actions:
                m.addSeparator() if a is None else m.addAction(a)

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        for a in [self.a_new_view, self.a_open, None, self.a_netlist, self.a_sim, self.a_generate, None, self.a_drc, self.a_lvs,
                  None, self.a_refresh]:
            tb.addSeparator() if a is None else tb.addAction(a)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.wa_label = QLabel()
        sb.addWidget(self.wa_label, 1)
        self.tool_dots = {}
        for name, label in (("xschem", "xschem"), ("klayout", "KLayout")):
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(8, 0, 8, 0)
            lay.setSpacing(5)
            dot = QLabel()
            lay.addWidget(dot)
            lay.addWidget(QLabel(label))
            sb.addPermanentWidget(w)
            self.tool_dots[name] = dot
        self._tool_timer = QTimer(self, interval=1500, timeout=self._update_tool_status)
        self._tool_timer.start()
        self._update_tool_status()

    # ---- command server: lets xschem/KLayout menus (openlayout hubcmd) drive the hub ------------
    def _start_server(self):
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._on_connection)
        if not self.server.listen(QHostAddress.LocalHost, 0):
            self.ciw.warn("cannot start the hub command server; cross-tool menus will not work")

    def _on_connection(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._on_request(s))
            sock.disconnected.connect(sock.deleteLater)

    def _on_request(self, sock):
        if not sock.canReadLine():
            return
        try:
            reply = self.handle_request(json.loads(bytes(sock.readLine()).decode()))
        except Exception as e:  # reply with the error instead of dropping the connection
            reply = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        sock.write((json.dumps(reply) + "\n").encode())
        sock.flush()
        sock.disconnectFromHost()

    def handle_request(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "ping":
            return {"ok": True, "message": f"OpenLayout hub {__version__}"}
        if not self.workarea:
            return {"ok": False, "error": "the hub has no workarea open"}
        cell = self.workarea.cell_for_path(req.get("path") or "", req.get("cell"))
        if cell is None:
            return {"ok": False, "error": f"{req.get('path')} is not part of workarea {self.workarea.root}"}
        if cmd == "open":
            view = cell.view(req.get("view") or "schematic")
            if view is None:
                return {"ok": False, "error": f"{cell.key} has no {req.get('view')} view"}
            self.ciw.info(f"open {cell.key} {view.name} (requested by a tool)")
            self.open_target(view)
            return {"ok": True, "message": f"opening {cell.key} {view.name}"}
        if cmd == "generate":
            self.lm.select(cell.library.name, cell.name)
            self.generate_layout(cell)
            return {"ok": True, "message": f"generating layout of {cell.key}"}
        if cmd in ("select", "netlist", "simulate"):
            self.lm.select(cell.library.name, cell.name)
            self.raise_hub()
            if cmd == "netlist":
                self.netlist(cell)
            elif cmd == "simulate":
                self.simulate(cell)
            return {"ok": True, "message": f"{cmd} {cell.key}"}
        return {"ok": False, "error": f"unknown command {cmd!r}"}

    def raise_hub(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _write_session(self):
        if self.workarea and self.server.isListening():
            f = self.workarea.session_file
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"hub_port": self.server.serverPort(), "pid": os.getpid()}))

    def _clear_session(self):
        if self.workarea and self.workarea.session().get("pid") == os.getpid():
            self.workarea.session_file.unlink(missing_ok=True)

    # ---- workarea ---------------------------------------------------------------------------
    def set_workarea(self, wa: Workarea | None):
        self._clear_session()
        self.workarea = wa
        self.xschem = XschemBridge(wa) if wa else None
        self.klayout = KLayoutBridge(wa) if wa else None
        for bridge in (self.xschem, self.klayout):
            if bridge and self.server.isListening():
                bridge.extra_env["OPENLAYOUT_HUB_PORT"] = str(self.server.serverPort())
        self.lm.set_workarea(wa)
        if wa:
            self._write_session()
            self.settings.setValue("workarea", str(wa.root))
            libs = wa.libraries()
            n_design = sum(1 for lb in libs if not lb.readonly)
            self.ciw.info(f"workarea {wa.root}: {n_design} design and {len(libs) - n_design} PDK libraries")
            self.setWindowTitle(f"OpenLayout — {wa.root.name}")
            self.wa_label.setText(f"  {wa.root}")
        else:
            self.ciw.warn("no workarea open — use File → Open Workarea or New Workarea")
            self.setWindowTitle("OpenLayout")
            self.wa_label.setText("  no workarea")
        self._update_actions()

    def new_workarea(self):
        path = QFileDialog.getExistingDirectory(self, "Choose or create an empty folder for the new workarea",
                                                str(Path.home() / "designs"))
        if not path:
            return
        name, ok = QInputDialog.getText(self, "New Workarea", "First library name:", text=Path(path).name)
        if ok:
            self._guard(lambda: self.set_workarea(Workarea.create(path, name)))

    def open_workarea(self):
        path = QFileDialog.getExistingDirectory(self, "Open Workarea (folder containing libs.def)",
                                                str(self.workarea.root if self.workarea else Path.home()))
        if path:
            self._guard(lambda: self.set_workarea(Workarea(path)))

    # ---- library / cell / view operations -----------------------------------------------------
    def _guard(self, fn):
        try:
            return fn()
        except (WorkareaError, OSError) as e:
            self.ciw.error(str(e))
            QMessageBox.warning(self, "OpenLayout", str(e))

    def new_library(self):
        if not self.workarea:
            return
        name, ok = QInputDialog.getText(self, "New Library", "Library name:")
        if ok and name:
            if self._guard(lambda: self.workarea.new_library(name)):
                self.ciw.ok(f"created library {name}")
                self.lm.refresh()
                self.lm.select(name)

    def new_cell_view(self):
        if not self.workarea:
            return
        dlg = NewCellViewDialog(self, self.workarea, self.lm.current_library(), self.lm.current_cell())
        if not dlg.exec():
            return
        lib, cell, vt, open_after = dlg.values()
        view = self._guard(lambda: self.workarea.new_view(lib, cell, vt))
        if view:
            self.ciw.ok(f"created {lib.name}/{cell} {vt.name}")
            self.lm.refresh()
            self.lm.select(lib.name, cell, vt.name)
            if open_after:
                self.open_target(view)

    def copy_cell(self):
        cell = self.lm.current_cell()
        if not cell:
            return
        dlg = CopyCellDialog(self, self.workarea, cell)
        if dlg.exec():
            lib, name = dlg.values()
            new = self._guard(lambda: self.workarea.copy_cell(cell, lib, name))
            if new:
                self.ciw.ok(f"copied {cell.key} to {new.key}")
                self.lm.refresh()
                self.lm.select(lib.name, name)

    def rename_cell(self):
        cell = self.lm.current_cell()
        if not cell or cell.library.readonly:
            return
        name, ok = QInputDialog.getText(self, "Rename Cell", f"New name for {cell.key}:", text=cell.name)
        if ok and name and name != cell.name:
            new = self._guard(lambda: self.workarea.rename_cell(cell, name))
            if new:
                self.ciw.ok(f"renamed {cell.key} to {new.key}")
                self.lm.refresh()
                self.lm.select(cell.library.name, name)

    def delete_selected(self):
        view, cell = self.lm.current_view(), self.lm.current_cell()
        target = view if self.lm.views.list.hasFocus() and view else cell
        if not target or target_readonly(target):
            return
        what = f"{target.cell.key} {target.name} view" if isinstance(target, View) else f"cell {target.key}"
        if QMessageBox.question(self, "Delete", f"Move {what} to the workarea trash (.trash/)?") \
                != QMessageBox.Yes:
            return
        dst = self._guard(lambda: self.workarea.delete(target))
        if dst:
            self.ciw.ok(f"moved {what} to {dst}")
            self.lm.refresh()

    # ---- opening views ------------------------------------------------------------------------
    def open_selected(self):
        target = self.lm.current_view() if self.lm.views.list.hasFocus() else None
        self.open_target(target or self.lm.current_cell())

    def open_target(self, target):
        if isinstance(target, Cell):
            views = {v.name: v for v in target.views()}
            target = next((views[n] for n in ("schematic", "layout", "symbol", "netlist") if n in views), None)
            if target is None:
                self.ciw.warn("cell has no views yet — use New Cell View")
                return
        if target is None:
            return
        if target.type.tool == "text":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.path)))
            return
        bridge = self.xschem if target.type.tool == "xschem" else self.klayout
        if not bridge.running:
            self.ciw.info(f"starting {bridge.name}…")
        self._in_thread(bridge, lambda: bridge.open(target))

    def _start_tool(self, name):
        bridge = self.xschem if name == "xschem" else self.klayout
        if bridge is None:
            return
        self._in_thread(bridge, lambda: (bridge.ensure_started(), f"{bridge.name} running")[1])

    def _in_thread(self, bridge, fn):
        def work():
            with self._tool_locks[bridge.name]:
                try:
                    self.logged.emit("ok", fn())
                except Exception as e:  # surface every bridge failure in the CIW
                    self.logged.emit("error", f"{bridge.name}: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _update_tool_status(self):
        for name, dot in self.tool_dots.items():
            bridge = self.xschem if name == "xschem" else self.klayout
            up = bool(bridge and bridge.running)
            dot.setPixmap(theme.dot_pixmap(theme.C["ok"] if up else theme.C["border"]))
            dot.setToolTip(f"{name} {'running (port %d)' % bridge.port if up else 'not running'}")

    # ---- netlist / simulate -------------------------------------------------------------------
    def _run(self, argv, cwd, label, done):
        if self._proc is not None:
            self.ciw.warn("another job is running")
            return
        self.ciw.info(f"{label}: {' '.join(argv)}")
        proc = QProcess(self)
        proc.setWorkingDirectory(str(cwd))
        proc.setProcessChannelMode(QProcess.MergedChannels)
        output = []

        def read():
            text = bytes(proc.readAllStandardOutput()).decode(errors="replace")
            output.append(text)
            if text.strip():
                self.ciw.output(text)

        def finished(code, _status):
            read()
            self._proc = None
            self._update_actions()
            done(code, "".join(output))

        proc.readyReadStandardOutput.connect(read)
        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda err: self.ciw.error(f"{label}: cannot run {argv[0]} ({err.name})"))
        self._proc = proc
        self._update_actions()
        proc.start(argv[0], argv[1:])

    def netlist(self, cell, then=None):
        if not cell:
            return
        try:
            argv, cwd, out = netlist_command(self.workarea, cell)
        except WorkareaError as e:
            self.ciw.error(str(e))
            return
        before = out.stat().st_mtime if out.exists() else 0

        def done(code, text):
            ok = code == 0 and out.exists() and out.stat().st_mtime > before
            self.workarea.set_state(cell, "netlist", ok, str(out))
            (self.ciw.ok if ok else self.ciw.error)(f"netlist {cell.key}: {'wrote ' + str(out) if ok else 'failed'}")
            self.lm.refresh()
            if ok and then:
                then(out)

        self._run(argv, cwd, f"netlist {cell.key}", done)

    def simulate(self, cell):
        if not cell:
            return

        def sim(netlist):
            argv, cwd = simulate_command(self.workarea, cell, netlist)

            def done(code, text):
                results = SIM_RESULT_RE.findall(text)
                ok = code == 0 and not SIM_FAIL_RE.search(text)
                detail = SIM_RESULT_RE.search(text)
                self.workarea.set_state(cell, "sim", ok, detail.group(0) if detail else f"exit {code}")
                (self.ciw.ok if ok else self.ciw.error)(
                    f"simulate {cell.key}: {'finished' if ok else 'failed'}"
                    + (f" ({len(results)} check(s))" if results else "") + f" — results in {cwd}")
                self.lm.refresh()

            self._run(argv, cwd, f"simulate {cell.key}", done)

        self.netlist(cell, then=sim)

    # ---- symbol from schematic ------------------------------------------------------------------
    def generate_symbol(self, cell):
        """Virtuoso "from cellview": build <cell>.sym from the schematic's pins and open it."""
        if not cell or cell.library.readonly or cell.view("schematic") is None:
            return
        from ..symbolgen import make_symbol
        sch = cell.view("schematic").path
        force = False
        if cell.view("symbol") is not None:
            if QMessageBox.question(self, "Generate Symbol",
                                    f"{cell.key} already has a symbol. Replace it?") != QMessageBox.Yes:
                return
            force = True
        sym = self._guard(lambda: make_symbol(sch, force))
        if sym:
            self.ciw.ok(f"generated symbol {cell.key} from {sch.name}")
            self.lm.refresh()
            self.lm.select(cell.library.name, cell.name, "symbol")
            self.open_target(cell.view("symbol"))

    # ---- schematic-driven layout ----------------------------------------------------------------
    def generate_layout(self, cell):
        """Layout XL style: create/update <cell>.gds from the schematic inside the KLayout session."""
        if not cell:
            return
        sch = cell.view("schematic")
        if sch is None or cell.library.readonly:
            self.ciw.error(f"{cell.key}: needs a schematic in a writable library")
            return
        bridge = self.klayout
        self.ciw.info(f"generate layout {cell.key} from {sch.path.name}" +
                      ("" if bridge.running else " (starting KLayout…)"))

        def work():
            bridge.ensure_started()
            reply = bridge.request({"cmd": "generate", "schematic": str(sch.path)}, timeout=300)
            self.refresh_requested.emit()
            return f"generated layout {reply['message']}"

        self._in_thread(bridge, work)

    # ---- misc -------------------------------------------------------------------------------
    def _update_actions(self):
        lib, cell, view = self.lm.current_library(), self.lm.current_cell(), self.lm.current_view()
        has_wa = self.workarea is not None
        writable_cell = bool(cell and not cell.library.readonly)
        has_sch = bool(cell and cell.view("schematic"))
        idle = self._proc is None
        self.a_new_lib.setEnabled(has_wa)
        self.a_new_view.setEnabled(has_wa)
        self.a_open.setEnabled(bool(cell))
        self.a_copy.setEnabled(bool(cell))
        self.a_rename.setEnabled(writable_cell)
        self.a_delete.setEnabled(writable_cell)
        self.a_netlist.setEnabled(has_sch and idle)
        self.a_sim.setEnabled(has_sch and idle)
        self.a_generate.setEnabled(has_sch and writable_cell)
        self.a_gensym.setEnabled(has_sch and writable_cell)
        self.a_start_xs.setEnabled(has_wa)
        self.a_start_kl.setEnabled(has_wa)

    def _context_menu(self, kind, pos):
        m = QMenu(self)
        if kind == "library":
            m.addActions([self.a_new_view, self.a_new_lib, self.a_refresh])
        elif kind == "cell" and self.lm.current_cell():
            m.addActions([self.a_open, self.a_new_view])
            m.addSeparator()
            m.addActions([self.a_copy, self.a_rename, self.a_delete])
            m.addSeparator()
            m.addActions([self.a_netlist, self.a_sim, self.a_generate, self.a_gensym, self.a_drc, self.a_lvs])
        elif kind == "view" and self.lm.current_view():
            m.addActions([self.a_open, self.a_delete])
        if not m.isEmpty():
            m.exec(pos)

    def _toggle_pdk(self, on):
        self.lm.show_pdk = on
        self.settings.setValue("show_pdk", on)
        self.lm.refresh()

    def _run_ciw(self, text):
        self.ciw.input.setText(text)
        self.ciw._submit()

    def about(self):
        QMessageBox.about(self, "About OpenLayout",
                          f"<h3>OpenLayout {__version__}</h3><p>A Virtuoso-style open-source custom IC design "
                          "environment for the ASAP7 7nm FinFET PDK.</p><p>xschem · ngspice · KLayout</p>")

    def show_keys(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Virtuoso Keys")
        dlg.resize(720, 640)
        view = QTextBrowser(dlg)
        keys = Path(__file__).resolve().parents[3] / "docs" / "KEYS.md"
        view.setMarkdown(keys.read_text() if keys.is_file() else "docs/KEYS.md not found")
        QVBoxLayout(dlg).addWidget(view)
        dlg.show()

    def closeEvent(self, e):
        self._clear_session()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        running = [b.name for b in (self.xschem, self.klayout) if b and b.running]
        if running:
            self.ciw.info(f"leaving {', '.join(running)} running")
        super().closeEvent(e)


def target_readonly(target) -> bool:
    cell = target.cell if isinstance(target, View) else target
    return cell.library.readonly
