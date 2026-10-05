"""Connectivity panel (right dock): schematic nets vs. layout, Layout XL style.

Lists every net of the linked schematic with its state - complete, open (with the unconnected
terminals and why) or shorted (with what of the other net touches it) - plus schematic pins without
a label, schematic parts missing from the layout and layout parts no longer in the schematic.
Open nets get flight lines, one vibrant colour per net (the net's name in the list has the same
colour); a selected short is outlined. The check re-runs a moment after the layout changes.
"""
import pya

from . import connectivity

POLL_MS = 1000
USER_ROLE = 256  # Qt::UserRole (the binding wants a plain int for item data roles)
# flight-line colours: vibrant, far apart, readable on the dark canvas
PALETTE = [0xFF3B30, 0x30D158, 0x0A84FF, 0xFFD60A, 0xBF5AF2, 0xFF9F0A, 0x64D2FF, 0xFF375F,
           0xA8E10C, 0x5E5CE6, 0x00E5C0, 0xFF6EC7, 0xFFB340, 0x40C8FF, 0xC77DFF, 0x7CFF6B]
SHORT_COLOR = 0xFF2D2D
HELP = ("<b>Open</b>: the net is in several pieces - the flight lines show what still needs wiring. "
        "<b>Short</b>: two schematic nets touch in the layout - click it to outline the merged shapes.")


class NetsPanel:
    def __init__(self, mw: pya.MainWindow, ui: dict, on_update=None):
        self.mw = mw
        self.ui = ui
        self.on_update = on_update   # callback(layout path) for "Update from Schematic"
        self.result = None
        self.markers = []
        self.selected = None
        self._fingerprint = None
        self._items = []

        self.dock = pya.QDockWidget("Connectivity", mw)
        self.dock.objectName = "openlayout_connectivity"
        body = pya.QWidget(self.dock)
        lay = pya.QVBoxLayout(body)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.title = pya.QLabel("No schematic link", body)
        self.title.styleSheet = "font-weight: 600; padding: 2px;"
        self.title.wordWrap = True
        lay.addWidget(self.title)
        self.summary = pya.QLabel("", body)
        self.summary.wordWrap = True
        lay.addWidget(self.summary)
        self.help = pya.QLabel(HELP, body)
        self.help.wordWrap = True
        self.help.styleSheet = "color: #8a93a3; font-size: 11px;"
        lay.addWidget(self.help)
        row = pya.QHBoxLayout()
        self.check_btn = pya.QPushButton("Check", body)
        self.check_btn.clicked = lambda: self.run_check(force=True)
        self.update_btn = pya.QPushButton("Update from Schematic", body)
        self.update_btn.clicked = self.update_from_source
        row.addWidget(self.check_btn)
        row.addWidget(self.update_btn)
        lay.addLayout(row)
        self.lines_box = pya.QCheckBox("Show flight lines", body)
        self.lines_box.checked = True
        self.lines_box.toggled = lambda _on: self.draw()
        lay.addWidget(self.lines_box)
        self.tree = pya.QTreeWidget(body)
        self.tree.setHeaderLabels(["Net", "Status"])
        self.tree.rootIsDecorated = True
        self.tree.itemClicked = self.on_click
        self.tree.itemDoubleClicked = self.on_double_click
        lay.addWidget(self.tree)
        self.dock.setWidget(body)
        mw.addDockWidget(pya.Qt.RightDockWidgetArea, self.dock)

        mw.on_current_view_changed += lambda: self.run_check(force=True)
        self.timer = pya.QTimer(self.dock)
        self.timer.interval = POLL_MS
        self.timer.timeout = lambda: self.run_check(force=False)
        self.timer.start()

    # ---- what we are looking at -------------------------------------------------------------
    def target(self):
        """(view, layout, top cell, layout path, link) for the active layout with a schematic link."""
        view = self.mw.current_view()
        cv = view.active_cellview() if view is not None else None
        if cv is None or not cv.is_valid() or not cv.filename():
            return None
        conn = connectivity.load_conn(cv.filename())
        if conn is None:
            return None
        layout = cv.layout()
        top = layout.cell(cv.cell_name) if cv.cell_name else None
        top = top if top is not None and not top.is_proxy() else layout.top_cell()
        return view, layout, top, cv.filename(), conn

    @staticmethod
    def fingerprint(layout, top):
        h = 0
        for li in layout.layer_indexes():
            for s in top.shapes(li).each():
                h = hash((h, li, str(s.bbox())))
        for inst in top.each_inst():
            h = hash((h, inst.cell_index, str(inst.dcplx_trans)))
        return h

    # ---- checking ---------------------------------------------------------------------------
    def run_check(self, force=False):
        t = self.target()
        if t is None:
            if self.result is not None or force:
                self.result = None
                self._fingerprint = None
                self.clear_markers()
                self.tree.clear()
                self.title.text = "No schematic link"
                self.summary.text = ("Generate the layout from its schematic (OpenLayout menu or hub) to "
                                     "track connectivity here.")
            return
        view, layout, top, path, conn = t
        fp = (path, self.fingerprint(layout, top))
        if not force and fp == self._fingerprint:
            return
        self._fingerprint = fp
        try:
            self.result = connectivity.check(layout, top, conn)
        except Exception as e:  # keep the panel alive and show what went wrong
            self.summary.text = f"Check failed: {e}"
            return
        self.title.text = f"{top.name}  ⟵  {conn.get('schematic', '?')}"
        self.fill()
        self.draw()

    def fill(self):
        res = self.result
        s = connectivity.summary(res)
        ok, fail, warn = self.ui["ok"], self.ui["fail"], self.ui["warn"]
        parts = [f"{s['nets']} nets"]
        parts.append(f"<span style='color:{warn if s['open'] else ok}'>{s['open']} open</span>")
        shorts = " (" + ", ".join(" - ".join(x["nets"]) for x in res.get("shorts", [])) + ")" if s["shorts"] else ""
        parts.append(f"<span style='color:{fail if s['shorts'] else ok}'>{s['shorts']} "
                     f"short{'' if s['shorts'] == 1 else 's'}{shorts}</span>")
        if s["unlabeled"]:
            parts.append(f"<span style='color:{fail}'>{s['unlabeled']} pin(s) without a label</span>")
        if s["missing"]:
            parts.append(f"<span style='color:{fail}'>{s['missing']} not placed</span>")
        if s["extra"]:
            parts.append(f"<span style='color:{warn}'>{s['extra']} not in schematic</span>")
        self.summary.text = " · ".join(parts)

        self.tree.clear()
        self._items = []

        def order(item):
            name, n = item
            return (0 if n["shorts"] else 1 if n["pieces"] > 1 else 2, name.lower())

        for name, n in sorted(res["nets"].items(), key=order):
            if n["shorts"]:
                status, color = f"short with {', '.join(n['shorts'])}", fail
            elif n["pieces"] > 1:
                status, color = f"open: {n['pieces']} pieces", warn
            else:
                status, color = "complete", ok
            item = pya.QTreeWidgetItem(self.tree)
            item.setText(0, name)
            item.setText(1, status)
            item.setForeground(0, pya.QBrush(pya.QColor(f"#{self.color(name):06x}")))
            item.setForeground(1, pya.QBrush(pya.QColor(color)))
            item.setData(0, USER_ROLE, name)
            self._items.append(item)
            for other, labels in n.get("touching", {}).items():
                child = pya.QTreeWidgetItem(item)
                child.setText(0, f"touches {other}")
                child.setText(1, ", ".join(labels[:8]) + (" ..." if len(labels) > 8 else ""))
                child.setForeground(1, pya.QBrush(pya.QColor(fail)))
                child.setData(0, USER_ROLE, name)
                self._items.append(child)
            for label in n["unconnected"][:50]:
                child = pya.QTreeWidgetItem(item)
                child.setText(0, label)
                child.setText(1, "unconnected")
                child.setData(0, USER_ROLE, name)
                self._items.append(child)
        for title, names, color in (("Pins without a label", res.get("unlabeled", []), fail),
                                    ("Not placed", res["missing"], fail), ("Not in schematic", res["extra"], warn)):
            if names:
                item = pya.QTreeWidgetItem(self.tree)
                item.setText(0, title)
                item.setText(1, ", ".join(names))
                item.setForeground(1, pya.QBrush(pya.QColor(color)))
                self._items.append(item)
        self.tree.resizeColumnToContents(0)

    # ---- flight lines -----------------------------------------------------------------------
    def clear_markers(self):
        for m in self.markers:
            m._destroy()
        self.markers = []

    def color(self, net):
        """A net's flight-line colour: stable per net name (by its place among the nets)."""
        names = sorted(self.result["nets"]) if self.result else []
        return PALETTE[names.index(net) % len(PALETTE)] if net in names else PALETTE[0]

    def draw(self):
        self.clear_markers()
        view = self.mw.current_view()
        if self.result is None or view is None:
            return
        if self.lines_box.checked:
            for name, n in self.result["nets"].items():
                hot = name == self.selected
                for a, b in n["lines"]:
                    m = pya.Marker(view)
                    m.set(pya.DEdge(a, b))
                    m.color = self.color(name)
                    m.line_width = 2 if hot else 1             # thin and solid; the selected net a little bolder
                    m.line_style = 0
                    m.vertex_size = 4 if hot else 3
                    self.markers.append(m)
        for short in self.result.get("shorts", []):            # the selected short: its merged shapes outlined
            if self.selected not in short["nets"]:
                continue
            for poly in short["shapes"]:
                m = pya.Marker(view)
                m.set(poly)
                m.color = SHORT_COLOR
                m.frame_color = SHORT_COLOR
                m.line_width = 2
                m.line_style = 0
                m.dither_pattern = 1                           # outline only
                m.vertex_size = 0
                self.markers.append(m)

    def on_click(self, item, _column):
        self.selected = item.data(0, USER_ROLE)
        self.draw()

    def on_double_click(self, item, _column):
        name = item.data(0, USER_ROLE)
        view = self.mw.current_view()
        if not name or self.result is None or view is None:
            return
        pts = self.result["nets"][name]["points"]
        box = pya.DBox()
        for p in pts:
            box += p
        view.zoom_box(box.enlarged(0.2, 0.2))

    def update_from_source(self):
        t = self.target()
        if t is None or self.on_update is None:
            return
        self.on_update(t[3])
        self.run_check(force=True)
