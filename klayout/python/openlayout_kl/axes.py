"""The x and y axes through the origin in every layout view.

KLayout only draws axes with its line-style grids; OpenLayout uses a dot grid, so the axes are two
long thin markers per view (a service created with each view). show() switches them on and off in
all views.
"""
import pya

NAME = "openlayout_axes"
EXTENT = 1.0e5            # um: far beyond any layout
_color = 0x8A93A6
_visible = True
_all = []                 # live Axes services


def show(on: bool):
    global _visible
    _visible = bool(on)
    for a in list(_all):
        if a.destroyed():         # its view was closed
            _all.remove(a)
        else:
            a.update()


def visible() -> bool:
    return _visible


class Axes(pya.Plugin):
    def __init__(self, view):
        super().__init__()
        self._view = view
        self.markers = []
        self.lines = []           # the edges shown (markers can't be read back)
        _all.append(self)
        self.update()

    def update(self):
        if not _visible:
            self.markers = []
            self.lines = []
            return
        if self.markers:
            return
        for edge in (pya.DEdge(-EXTENT, 0, EXTENT, 0), pya.DEdge(0, -EXTENT, 0, EXTENT)):
            m = pya.Marker(self._view)
            m.set(edge)
            m.color = _color
            m.line_width = 1
            m.vertex_size = 0
            m.dismissable = False
            self.markers.append(m)
            self.lines.append(edge)


class AxesFactory(pya.PluginFactory):
    def __init__(self, color: int = None):
        global _color
        super().__init__()
        if color is not None:
            _color = color
        self.has_tool_entry = False
        self.register(-1200, NAME, "")

    def create_plugin(self, manager, root, view):
        return Axes(view)
