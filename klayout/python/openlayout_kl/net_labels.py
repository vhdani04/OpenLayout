"""Net names drawn on the layout's shapes, like a custom-layout editor's net display: every piece of
gate, LIG, LISD and metal carries the name of the net it belongs to.

The names come from the connectivity extraction (connectivity.net_shapes): the schematic link's
nets where the layout has one, else the top cell's pin labels. A piece of metal that carries several
schematic nets (a short) shows all of them, in red.

The labels are polygons (KLayout's text generator) drawn as markers, so they behave like geometry:
they scale with the zoom, run along vertical wires and fit inside their shape. A label is only drawn
once it is readable - its text at least MIN_PX pixels high - and only on visible layers, so zooming
in reveals the names of smaller shapes. The extraction re-runs a moment after the layout changes;
the labels are redrawn when the view moves.
"""
import pya

from . import connectivity
from .asap7 import LAYERS

POLL_MS = 1000
REDRAW_MS = 120
MIN_PX = 7               # smallest text height drawn, in screen pixels
MAX_PX = 22              # largest
MAX_LABELS = 400         # per redraw (the largest shapes win)
FILL = 0.6               # text height as a fraction of the shape's narrow side
REPEAT_PX = 420          # a long wire repeats its name about this often on screen
SAME_NAME_PX = 60        # one label per net within this distance
COLOR, SHORT_COLOR = 0xFFFFFF, 0xFF4D4D
# where labels would overlap, the upper layer's wins
LAYER_RANK = {name: i for i, name in enumerate(["gate", "lisd", "lig"] + [f"m{k}" for k in range(1, 10)])}

_enabled = True
_listeners = []          # callbacks(on) - the menu entry and the panel's checkbox follow
_instances = []


def enabled() -> bool:
    return _enabled


def set_enabled(on: bool):
    global _enabled
    _enabled = bool(on)
    for inst in _instances:
        inst.refresh(force=True)
    for fn in list(_listeners):
        try:
            fn(_enabled)
        except RuntimeError:                 # its widget is gone
            _listeners.remove(fn)


def on_change(fn):
    _listeners.append(fn)


class Glyphs:
    """Text as polygons, one unit high and centred on the origin (cached per string)."""

    def __init__(self):
        self.cache = {}

    def get(self, text):
        if text not in self.cache:
            # fetched each time: KLayout reloads its fonts after start-up, and a generator kept from
            # before that is a dangling object (it crashes in glyph())
            gen = pya.TextGenerator.default_generator()
            unit = gen.dheight() / 1000.0
            region = gen.text(text, unit)
            polys = [p.to_dtype(0.001) for p in region.each()]
            box = pya.DBox()
            for p in polys:
                box += p.bbox()
            c = box.center()
            polys = [p.moved(-c.x, -c.y) for p in polys]
            self.cache[text] = (polys, box.width() / max(box.height(), 1e-9))
        return self.cache[text]


def slabs(poly, dbu):
    """The rectangles a (Manhattan) polygon decomposes into - a label goes in each."""
    region = pya.Region(poly.to_itype(dbu))
    return [t.bbox().to_dtype(dbu) for t in region.decompose_trapezoids_to_region(pya.Polygon.TD_htrapezoids).each()]


def placements(box, aspect, mag, view_box):
    """[(DCplxTrans for the unit glyphs)] of one label in a rectangle, or [] when it would be
    unreadable or off screen. mag: screen pixels per micron."""
    if not box.overlaps(view_box):
        return []
    vertical = box.height() > 1.3 * box.width()
    long_side, short_side = (box.height(), box.width()) if vertical else (box.width(), box.height())
    h = min(FILL * short_side, 0.85 * long_side / aspect)
    if h * mag < MIN_PX:
        return []
    h = min(h, MAX_PX / mag)
    n = max(1, min(8, int(long_side * mag / REPEAT_PX)))
    out = []
    for k in range(n):
        f = (k + 0.5) / n
        if vertical:
            x, y, rot = box.center().x, box.bottom + f * box.height(), 90
        else:
            x, y, rot = box.left + f * box.width(), box.center().y, 0
        if view_box.contains(pya.DPoint(x, y)):
            out.append(pya.DCplxTrans(h, rot, False, x, y))
    return out


class NetLabels:
    def __init__(self, mw):
        self.mw = mw
        self.glyphs = Glyphs()
        self.markers = []
        self.shapes = []                 # [(name, short, layer, [DPolygon])]
        self.dbu = 0.001
        self._fingerprint = None
        self._views = set()
        _instances.append(self)
        self.redraw_timer = pya.QTimer(mw)
        self.redraw_timer.singleShot = True
        self.redraw_timer.interval = REDRAW_MS
        self.redraw_timer.timeout = self.draw
        self.poll = pya.QTimer(mw)
        self.poll.interval = POLL_MS
        self.poll.timeout = lambda: self.refresh(force=False)
        self.poll.start()
        mw.on_current_view_changed += lambda: self.refresh(force=True)

    # ---- what we are looking at -----------------------------------------------------------------
    def target(self):
        view = self.mw.current_view()
        cv = view.active_cellview() if view is not None else None
        if cv is None or not cv.is_valid():
            return None
        layout = cv.layout()
        top = layout.cell(cv.cell_name) if cv.cell_name else None
        top = top if top is not None and not top.is_proxy() else layout.top_cell()
        conn = connectivity.load_conn(cv.filename()) if cv.filename() else None
        return view, layout, top, conn

    def _watch(self, view):
        key = id(view)
        if key not in self._views:
            self._views.add(key)
            view.on_viewport_changed += self.schedule
            view.on_layer_list_changed += lambda _flags: self.schedule()

    def schedule(self):
        self.redraw_timer.start()

    # ---- extraction -----------------------------------------------------------------------------
    def refresh(self, force=False):
        if not _enabled:
            self._fingerprint = None
            self.shapes = []
            self.clear()
            return
        t = self.target()
        if t is None:
            self._fingerprint = None
            self.shapes = []
            self.clear()
            return
        view, layout, top, conn = t
        self._watch(view)
        fp = (id(layout), top.cell_index(), connectivity.fingerprint(layout, top), bool(conn))
        if force or fp != self._fingerprint:
            self._fingerprint = fp
            try:
                self.shapes = connectivity.net_shapes(layout, top, conn)
            except Exception as e:           # keep the editor usable whatever the layout holds
                print(f"OpenLayout net names: {e}")
                self.shapes = []
            self.dbu = layout.dbu
            self.draw()

    # ---- drawing --------------------------------------------------------------------------------
    def clear(self):
        for m in self.markers:
            m._destroy()
        self.markers = []

    def visible_layers(self, view):
        names = {(num, 0): name for name, num in LAYERS.items()}
        out = set()
        it = view.begin_layers()
        while not it.at_end():
            lp = it.current()
            if lp.visible_(True):                    # visible here and in every parent group
                name = names.get((lp.source_layer, lp.source_datatype))
                if name:
                    out.add(name)
            it.next()
        return out

    def labels(self, view):
        """[(text, short, DCplxTrans)] to draw in the current view: no two overlap; where they
        would, the upper layer's label wins (metal over contacts over gate), then the larger."""
        mag = view.viewport_trans().mag
        view_box = view.box()
        shown = self.visible_layers(view)
        cands = []
        for name, short, layer, polys in self.shapes:
            if layer not in shown:
                continue
            _, aspect = self.glyphs.get(name)
            for poly in polys:
                if not poly.bbox().overlaps(view_box):
                    continue
                for box in slabs(poly, self.dbu):
                    for tr in placements(box, aspect, mag, view_box):
                        extent = pya.DBox(-aspect / 2, -0.5, aspect / 2, 0.5).transformed(tr)
                        cands.append((LAYER_RANK.get(layer, 0), tr.mag, name, short, tr, extent))
        cands.sort(key=lambda c: (-c[0], -c[1]))
        placed, out, near = [], [], {}
        gap = 3.0 / mag                                   # 3 px between labels
        for _, _, name, short, tr, extent in cands:
            grown = extent.enlarged(gap, gap)
            if any(grown.overlaps(p) for p in placed):
                continue
            # the same name close by already (a pad over its contact over its gate): once is enough
            c, r = extent.center(), max(SAME_NAME_PX / mag, 4 * tr.mag)
            if any(c.distance(o) < r for o in near.get(name, ())):
                continue
            placed.append(extent)
            near.setdefault(name, []).append(c)
            out.append((name, short, tr))
            if len(out) >= MAX_LABELS:
                break
        return out

    def draw(self):
        self.clear()
        view = self.mw.current_view()
        if not _enabled or view is None or not self.shapes:
            return
        for text, short, tr in self.labels(view):
            color = SHORT_COLOR if short else COLOR
            for glyph in self.glyphs.get(text)[0]:
                m = pya.Marker(view)
                m.set_polygon(glyph.transformed(tr))
                m.color = color
                m.frame_color = color
                m.dither_pattern = 0                 # solid
                m.line_width = 1
                m.vertex_size = 0
                m.halo = 1                           # a dark outline keeps it readable on any layer
                self.markers.append(m)
