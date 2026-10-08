"""Mirror and rotate the selection - the layout canvas's right-click menu.

Right-click in Select mode on a selection (or on any shape, path or instance, which is selected
first) for:
  Mirror over X axis      flip top to bottom   } about the selection's centre, so it stays in place
  Mirror over Y axis      flip left to right   }
  Mirror over both axes   (a 180 degree turn)  }
  About the cell origin > the same three over the cell's own axes (x = 0, y = 0)
  Rotate 90 degrees left / right (about the selection's centre)
Shapes, paths, texts and cell / PCell instances all work; each operation is one undo step. Objects
selected inside an instance are transformed in their own cell, so the result looks the same as it
would at the top.
"""
import pya

# the operation at the origin; transform() moves it to the chosen centre
OPS = {
    "mirror_x": ("Mirror over X axis (flip vertically)", pya.DCplxTrans(1, 0, True, 0, 0)),
    "mirror_y": ("Mirror over Y axis (flip horizontally)", pya.DCplxTrans(1, 180, True, 0, 0)),
    "mirror_xy": ("Mirror over both axes", pya.DCplxTrans(1, 180, False, 0, 0)),
    "rot_ccw": ("Rotate 90° left", pya.DCplxTrans(1, 90, False, 0, 0)),
    "rot_cw": ("Rotate 90° right", pya.DCplxTrans(1, 270, False, 0, 0)),
}
MIRRORS = ("mirror_x", "mirror_y", "mirror_xy")
ROTATIONS = ("rot_ccw", "rot_cw")


def centre(view):
    """The selection's centre, on the database grid."""
    box = view.selection_bbox()
    dbu = view.active_cellview().layout().dbu
    c = box.center()
    return pya.DPoint(round(c.x / dbu) * dbu, round(c.y / dbu) * dbu)


def about(t0, c):
    """t0 (at the origin) about the point c."""
    return pya.DCplxTrans(c.x, c.y) * t0 * pya.DCplxTrans(-c.x, -c.y)


def transform(view, op, origin=False):
    """Apply an operation to the selection; returns the number of objects transformed."""
    objs = list(view.each_object_selected())
    if not objs:
        return 0
    title, t0 = OPS[op]
    t = about(t0, pya.DPoint(0, 0) if origin else centre(view))
    view.transaction(title + (" (cell origin)" if origin else ""))
    try:
        for o in objs:
            layout = view.cellview(o.cv_index).layout()
            ti = t.to_itrans(layout.dbu)
            # from the object's cell to the top: every instance on its path (an instance itself
            # is placed in its parent, so its own element is left out)
            elements = list(o.path)
            if o.is_cell_inst():
                elements = elements[:-1]
            ctx = pya.ICplxTrans()
            for e in elements:
                ctx = ctx * e.specific_cplx_trans()
            local = ctx.inverted() * ti * ctx
            if o.is_cell_inst():
                o.inst().transform(local)
            else:
                o.shape.transform(local)
    finally:
        view.commit()
    return len(objs)


def build_menu(view, parent=None):
    """The right-click menu for the selection."""
    menu = pya.QMenu(parent)

    def add(target, op, origin=False):
        a = target.addAction(OPS[op][0])
        a.triggered = lambda *_args: transform(view, op, origin)
        return a

    for op in MIRRORS:
        add(menu, op)
    sub = menu.addMenu("About the cell origin")
    for op in MIRRORS:
        add(sub, op, origin=True)
    menu.addSeparator()
    for op in ROTATIONS:
        add(menu, op)
    return menu


def cursor_pos():
    """The mouse position on screen (KLayout's Qt binding exposes QCursor.pos as a property)."""
    pos = pya.QCursor.pos
    return pos() if callable(pos) else pos


def show_menu(view):
    """Pop the menu up at the mouse."""
    menu = build_menu(view)
    menu.exec_(cursor_pos())
