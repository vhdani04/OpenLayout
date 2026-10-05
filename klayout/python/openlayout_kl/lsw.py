"""LSW: the layer selection window - the only layer panel in OpenLayout's KLayout.

Two tabs: All layers / Used layers (layers with shapes in the current cell). Click a layer to make
it the current drawing layer, tick/untick to show/hide it. AV shows all layers, NV hides all
layers except the current one.
"""
import pya

ALL, USED = 0, 1


def _hex(color: int) -> str:
    return "#%06x" % (color & 0xFFFFFF)


class LSW:
    def __init__(self, mw: pya.MainWindow, ui: dict):
        self.mw = mw
        self.ui = ui
        self.rows = []      # per list row: LayerPropertiesIterator, or None for a group header
        self.items = []     # Python references to the QListWidgetItems
        self._used_key = None
        self._current_key = None

        self.dock = pya.QDockWidget("LSW", mw)
        self.dock.objectName = "openlayout_lsw"
        body = pya.QWidget(self.dock)
        lay = pya.QVBoxLayout(body)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        self.current = pya.QLabel("Current layer: —", body)
        self.current.styleSheet = "font-weight: 600; padding: 2px;"
        lay.addWidget(self.current)

        self.tabs = pya.QTabBar(body)
        self.tabs.addTab("All layers")
        self.tabs.addTab("Used layers")
        self.tabs.expanding = True
        self.tabs.currentChanged = lambda _i: self.refresh()
        lay.addWidget(self.tabs)

        row = pya.QHBoxLayout()
        for label, tip, slot in (("AV", "All layers visible", self.all_visible),
                                 ("NV", "Hide every layer except the current one", self.none_visible)):
            b = pya.QPushButton(label, body)
            b.toolTip = tip
            b.clicked = slot
            row.addWidget(b)
        lay.addLayout(row)

        self.list = pya.QListWidget(body)
        self.list.iconSize = pya.QSize(30, 14)
        self.list.itemClicked = self.on_click
        self.list.itemChanged = self.on_check
        lay.addWidget(self.list)
        self.dock.setWidget(body)
        mw.addDockWidget(pya.Qt.RightDockWidgetArea, self.dock)

        mw.on_current_view_changed += self.refresh
        # Poll: follows current-layer changes made elsewhere and keeps the Used tab up to date.
        self.timer = pya.QTimer(self.dock)
        self.timer.interval = 1000
        self.timer.timeout = self.poll
        self.timer.start()
        self.refresh()

    # ---- model ------------------------------------------------------------------------------
    def view(self):
        return self.mw.current_view()

    def entries(self):
        """(header name or None, iterator) in tree order: top-level drawing layers, then groups."""
        view = self.view()
        out = []
        if view is None:
            return out
        it = view.begin_layers()
        while not it.at_end():
            lp = it.current()
            if lp.has_children():
                out.append((lp.name, None))
            else:
                out.append((None, it.dup()))
            it.next()
        return out

    @staticmethod
    def key(it):
        lp = it.current()
        return (lp.source, lp.name)

    def used_keys(self):
        return tuple(self.key(it) for header, it in self.entries() if it is not None
                     and not it.current().bbox().empty())

    def current_key(self):
        view = self.view()
        if view is None:
            return None
        cur = view.current_layer
        if cur.is_null() or cur.at_end() or cur.current().has_children():
            return None
        return self.key(cur)

    # ---- rendering --------------------------------------------------------------------------
    def swatch(self, lp):
        pm = pya.QPixmap(30, 14)
        pm.fill(pya.QColor(self.ui["base"]))
        p = pya.QPainter(pm)
        fill = pya.QColor(_hex(lp.eff_fill_color(True)))
        frame = pya.QColor(_hex(lp.eff_frame_color(True)))
        dither = lp.eff_dither_pattern(True)
        if dither != 1:  # 1 = hollow
            style = pya.Qt.SolidPattern if dither == 0 else pya.Qt.Dense4Pattern
            p.fillRect(1, 1, 28, 12, pya.QBrush(fill, style))
        pen = pya.QPen(frame)
        if lp.line_style not in (0, -1):
            pen.style = pya.Qt.DashLine
        p.setPen(pen)
        p.drawRect(0, 0, 29, 13)
        if lp.xfill:
            p.drawLine(0, 0, 29, 13)
            p.drawLine(0, 13, 29, 0)
        p.end()
        return pya.QIcon(pm)

    def refresh(self):
        used_only = self.tabs.currentIndex == USED
        used = set(self.used_keys()) if used_only else None
        self._used_key = tuple(sorted(used)) if used is not None else None
        cur = self.current_key()
        self.list.blockSignals(True)
        self.list.clear()
        self.rows, self.items = [], []
        pending_header = None
        for header, it in self.entries():
            if header is not None:
                pending_header = header
                continue
            lp = it.current()
            if used is not None and self.key(it) not in used:
                continue
            if pending_header is not None:  # only show a group header if it has visible members
                h = pya.QListWidgetItem(pending_header)
                h.flags = pya.Qt.ItemIsEnabled
                h.foreground = pya.QBrush(pya.QColor(self.ui["dim"]))
                self.list.addItem(h)
                self.items.append(h)
                self.rows.append(None)
                pending_header = None
            item = pya.QListWidgetItem(self.swatch(lp), lp.name or lp.source)
            item.flags = pya.Qt.ItemIsEnabled | pya.Qt.ItemIsSelectable | pya.Qt.ItemIsUserCheckable
            item.setCheckState(pya.Qt.Checked if lp.visible else pya.Qt.Unchecked)
            self.list.addItem(item)
            self.items.append(item)
            self.rows.append(it)
        self.list.blockSignals(False)
        self.show_current(cur)

    def show_current(self, cur):
        self._current_key = cur
        name = cur[1] if cur else "—"
        self.current.text = f"Current layer: {name}"
        self.list.blockSignals(True)
        for row, it in enumerate(self.rows):
            if it is not None and self.key(it) == cur:
                self.list.setCurrentRow(row)
                self.list.scrollToItem(self.items[row])
                break
        else:
            self.list.clearSelection()
        self.list.blockSignals(False)

    def poll(self):
        if self.view() is None:
            return
        cur = self.current_key()
        if self.tabs.currentIndex == USED and tuple(sorted(self.used_keys())) != self._used_key:
            self.refresh()
        elif cur != self._current_key:
            self.show_current(cur)

    # ---- actions ----------------------------------------------------------------------------
    def on_click(self, item):
        row = self.list.row(item)
        view = self.view()
        if view is None or not (0 <= row < len(self.rows)) or self.rows[row] is None:
            return
        view.current_layer = self.rows[row]
        self.show_current(self.key(self.rows[row]))

    def on_check(self, item):
        row = self.list.row(item)
        view = self.view()
        if view is None or not (0 <= row < len(self.rows)) or self.rows[row] is None:
            return
        self.set_visible(self.rows[row], item.checkState == pya.Qt.Checked)

    def set_visible(self, it, visible):
        lp = it.current().dup()
        if lp.visible != visible:
            lp.visible = visible
            self.view().set_layer_properties(it, lp)

    def _all_leaves(self):
        return [it for header, it in self.entries() if it is not None]

    def _show_groups(self):
        view = self.view()
        it = view.begin_layers()
        while not it.at_end():
            if it.current().has_children():
                self.set_visible(it, True)
            it.next()

    def all_visible(self):
        if self.view() is None:
            return
        self._show_groups()
        for it in self._all_leaves():
            self.set_visible(it, True)
        self.refresh()

    def none_visible(self):
        """Hide everything except the current layer (NV keeps the entry layer)."""
        if self.view() is None:
            return
        cur = self.current_key()
        self._show_groups()
        for it in self._all_leaves():
            self.set_visible(it, self.key(it) == cur)
        self.refresh()
