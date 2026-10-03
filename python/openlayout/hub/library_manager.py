"""Library Manager: Library | Cell | View columns plus a details pane."""
import fnmatch
import html
import time

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QLabel, QLineEdit, QListWidget, QListWidgetItem, QSplitter, QTextBrowser,
                               QVBoxLayout, QWidget)

from ..workarea import Cell, Library, View, Workarea
from .theme import C, cell_icon, library_icon, view_icon

STEPS = ["netlist", "sim", "drc", "lvs"]


class Column(QWidget):
    """Titled list with a filter box (substring, or wildcards like inv* )."""
    def __init__(self, title: str, icon_size: QSize):
        super().__init__()
        self.title = QLabel(title, objectName="columnTitle")
        self.filter = QLineEdit(placeholderText="Filter")
        self.filter.setClearButtonEnabled(True)
        self.list = QListWidget()
        self.list.setIconSize(icon_size)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.filter.textChanged.connect(self.apply_filter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.title)
        lay.addWidget(self.filter)
        lay.addWidget(self.list)

    def apply_filter(self) -> None:
        pattern = self.filter.text().strip().lower()
        glob = pattern if any(ch in pattern for ch in "*?[") else f"*{pattern}*"
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(pattern) and not fnmatch.fnmatch(item.text().lower(), glob))

    def fill(self, entries, keep: str | None) -> None:
        """entries: (text, icon, data, tooltip, dim). Re-selects the entry named `keep`."""
        self.list.blockSignals(True)
        self.list.clear()
        selected = None
        for text, icon, data, tip, dim in entries:
            item = QListWidgetItem(icon, text)
            item.setData(Qt.UserRole, data)
            item.setToolTip(tip)
            if dim:
                item.setForeground(QColor(C["dim"]))
            self.list.addItem(item)
            if text == keep:
                selected = item
        self.apply_filter()
        self.list.blockSignals(False)
        if selected:
            self.list.setCurrentItem(selected)
            self.list.scrollToItem(selected)

    def current(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None


class LibraryManager(QWidget):
    selectionChanged = Signal()
    openRequested = Signal(object)          # Cell or View
    contextRequested = Signal(str, object)  # "library" | "cell" | "view", global QPoint

    def __init__(self):
        super().__init__()
        self.workarea: Workarea | None = None
        self.show_pdk = True
        self.libs = Column("Library", QSize(16, 16))
        self.cells = Column("Cell", QSize(60, 16))
        self.views = Column("View", QSize(16, 16))
        self.details = QTextBrowser(openExternalLinks=False)
        self.details.setMinimumWidth(240)

        split = QSplitter(Qt.Horizontal)
        for w in (self.libs, self.cells, self.views, self.details):
            split.addWidget(w)
        split.setSizes([220, 330, 160, 300])
        split.setChildrenCollapsible(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.addWidget(split)

        self.libs.list.currentItemChanged.connect(lambda *_: self._fill_cells())
        self.cells.list.currentItemChanged.connect(lambda *_: self._fill_views())
        self.views.list.currentItemChanged.connect(lambda *_: self._update_details())
        self.cells.list.itemDoubleClicked.connect(lambda it: self.openRequested.emit(it.data(Qt.UserRole)))
        self.views.list.itemDoubleClicked.connect(lambda it: self.openRequested.emit(it.data(Qt.UserRole)))
        for kind, col in (("library", self.libs), ("cell", self.cells), ("view", self.views)):
            col.list.customContextMenuRequested.connect(
                lambda pos, k=kind, c=col: self.contextRequested.emit(k, c.list.viewport().mapToGlobal(pos)))

    # ---- selection --------------------------------------------------------------------------
    def current_library(self) -> Library | None:
        return self.libs.current()

    def current_cell(self) -> Cell | None:
        return self.cells.current()

    def current_view(self) -> View | None:
        return self.views.current()

    def select(self, lib: str | None = None, cell: str | None = None, view: str | None = None) -> None:
        self._fill_libs(keep=lib)
        if cell:
            self._fill_cells(keep=cell)
        if view:
            self._fill_views(keep=view)

    # ---- filling ----------------------------------------------------------------------------
    def set_workarea(self, wa: Workarea | None) -> None:
        self.workarea = wa
        self.refresh()

    def refresh(self) -> None:
        lib, cell, view = self.current_library(), self.current_cell(), self.current_view()
        if self.workarea:
            self.workarea.reload()
        self._fill_libs(keep=lib.name if lib else None)
        if cell:
            self._fill_cells(keep=cell.name)
        if view:
            self._fill_views(keep=view.name)

    def _fill_libs(self, keep=None) -> None:
        libs = self.workarea.libraries() if self.workarea else []
        design = [lb for lb in libs if not lb.readonly]
        pdk = [lb for lb in libs if lb.readonly] if self.show_pdk else []
        entries = []
        for lib in design + pdk:
            tip = f"{lib.path}\n{lib.description or ('read-only' if lib.readonly else 'design library')}"
            if not lib.exists:
                tip += "\n(directory missing)"
            entries.append((lib.name, library_icon(lib.readonly), lib, tip, lib.readonly or not lib.exists))
        if keep is None and design:
            keep = design[0].name
        self.libs.fill(entries, keep)
        self._fill_cells()

    def _fill_cells(self, keep=None) -> None:
        lib = self.current_library()
        prev = self.current_cell()
        keep = keep or (prev.name if prev and lib and prev.library.name == lib.name else None)
        state = self.workarea.state() if self.workarea else {}
        entries = []
        for cell in lib.cells() if lib else []:
            views = {v.name for v in cell.views()}
            status = state.get(cell.key, {})
            entries.append((cell.name, cell_icon(views, status), cell, ", ".join(sorted(views)) or "no views", False))
        self.cells.fill(entries, keep)
        self.cells.title.setText(f"Cell  ({len(entries)})" if lib else "Cell")
        self._fill_views()

    def _fill_views(self, keep=None) -> None:
        cell = self.current_cell()
        prev = self.current_view()
        keep = keep or (prev.name if prev else None)
        entries = [(v.name, view_icon(v.name), v, str(v.path) + (f"  [{v.gds_cell}]" if v.gds_cell else ""),
                    v.readonly) for v in (cell.views() if cell else [])]
        self.views.fill(entries, keep)
        self._update_details()

    # ---- details pane -----------------------------------------------------------------------
    def _update_details(self) -> None:
        lib, cell, view = self.current_library(), self.current_cell(), self.current_view()
        h = []
        if lib:
            ro = ' <span style="color:%s">(read-only)</span>' % C["dim"] if lib.readonly else ""
            h.append(f"<h3 style='margin:0'>{html.escape(lib.name)}{ro}</h3>")
            if lib.description:
                h.append(f"<p style='color:{C['dim']};margin:2px 0'>{html.escape(lib.description)}</p>")
            h.append(f"<p style='color:{C['dim']};margin:2px 0'>{html.escape(str(lib.path))}</p>")
        if cell:
            h.append(f"<h3 style='margin:10px 0 2px 0'>{html.escape(cell.name)}</h3><table cellspacing=3>")
            for v in cell.views():
                where = html.escape(v.path.name + (f" [{v.gds_cell}]" if v.gds_cell else ""))
                h.append(f"<tr><td>{v.name}</td><td style='color:{C['dim']}'>{where}</td></tr>")
            h.append("</table>")
            if not lib.readonly and self.workarea:
                state = self.workarea.cell_state(cell)
                h.append("<h4 style='margin:10px 0 2px 0'>Checks</h4><table cellspacing=3>")
                for step in STEPS:
                    s = state.get(step)
                    if s is None:
                        mark, color, when = "—", C["dim"], ""
                    else:
                        mark, color = ("pass", C["ok"]) if s["ok"] else ("fail", C["fail"])
                        when = time.strftime("%b %d %H:%M", time.localtime(s["time"]))
                    h.append(f"<tr><td>{step.upper()}</td><td style='color:{color}'>{mark}</td>"
                             f"<td style='color:{C['dim']}'>{when}</td></tr>")
                h.append("</table>")
        if view:
            h.append(f"<p style='color:{C['dim']};margin-top:10px'>Double-click to open the {view.name} "
                     f"in {'xschem' if view.type.tool == 'xschem' else 'KLayout' if view.type.tool == 'klayout' else 'a text editor'}.</p>")
        self.details.setHtml("".join(h) or f"<p style='color:{C['dim']}'>No workarea open.</p>")
        self.selectionChanged.emit()
