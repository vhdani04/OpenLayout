# Generate KLayout layer properties (asap7.lyp) for ASAP7 from the PDK's Virtuoso files:
#   cdslib/asap7_TechLib_10/asap7_TechLib.layermap   (layer/purpose -> GDS layer/datatype)
#   cdslib/setup/display.drf                          (colors, stipples, line styles, packets)
# so layers look the way they do in Virtuoso.
#
# Run:  klayout -b -r gen_asap7_lyp.py -rd pdk=$ASAP7_PDK -rd out=tech/asap7/asap7.lyp
import re
import pya

LAYERMAP = f"{pdk}/cdslib/asap7_TechLib_10/asap7_TechLib.layermap"
DRF = f"{pdk}/cdslib/setup/display.drf"

# Layer-map names whose display packet uses a different (techfile) name.
ALIASES = {"well": "NW", "fin": "FIN", "gate": "PO", "dummy": "PODMY", "active": "ACT",
           "slvt": "SLVTN", "lvt": "LVTN", "boundary": "BOUND", "text": "TXT", "p_sub": "PSUB"}
PURPOSE_ABBR = {"drawing": "drg", "pin": "pin", "label": "lbl", "net": "net", "blockage": "blk"}
# Layers with no packet in display.drf: (fill, outline, stipple, fillStyle)
FALLBACK = {"gcut": ("red", "red", "dots", "outlineStipple")}
# Display order, bottom of the stack first (like the Virtuoso LSW).
STACK = ["well", "p_sub", "fin", "active", "nselect", "pselect", "slvt", "lvt", "sramvt",
         "gate", "dummy", "gcut", "sdt", "lisd", "lig", "v0", "m1", "v1", "m2", "v2", "m3", "v3",
         "m4", "v4", "m5", "v5", "m6", "v6", "m7", "v7", "m8", "v8", "m9", "v9",
         "sramdrc", "boundary", "text"]
GROUPS = [("drawing", None), ("pin", "Pins"), ("label", "Labels"), ("net", "Nets"),
          ("blockage", "Blockages")]


def sexpr(text):
    """Parse SKILL-ish s-expressions into nested lists (comments start with ';')."""
    tokens = re.findall(r"\(|\)|[^\s()]+", re.sub(r";[^\n]*", "", text))
    stack = [[]]
    for t in tokens:
        if t == "(":
            stack.append([])
        elif t == ")":
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(t)
    return stack[0]


def drf_sections(path):
    items = sexpr(open(path).read())
    sections = {}
    for i, it in enumerate(items):
        if isinstance(it, str) and it.startswith("drDefine") and i + 1 < len(items):
            sections[it] = items[i + 1]
    return sections


sec = drf_sections(DRF)
colors = {e[1]: (int(e[2]) << 16) | (int(e[3]) << 8) | int(e[4]) for e in sec["drDefineColor"]}
stipples = {e[1]: e[2] for e in sec["drDefineStipple"]}
linestyles = {e[1]: (int(e[2]), e[3]) for e in sec["drDefineLineStyle"]}
packets = {e[1].lower(): e[2:] for e in sec["drDefinePacket"]}  # stipple, line, fill, outline, fillStyle

view = pya.LayoutView()
view.clear_stipples()
view.clear_line_styles()
stipple_idx, line_idx = {}, {}


def stipple(name):
    if name in ("blank", "none") or name not in stipples:
        return 1  # hollow
    if name not in stipple_idx:
        rows = stipples[name]
        bits = len(rows[0])
        data = [sum(int(b) << i for i, b in enumerate(r)) for r in rows]
        stipple_idx[name] = view.add_stipple(name, data, bits)
    return stipple_idx[name]


def line_style(name):
    size, pattern = linestyles.get(name, (1, ["1"]))
    if all(b == "1" for b in pattern):
        return 0, size  # solid
    if name not in line_idx:
        line_idx[name] = view.add_line_style(name, sum(int(b) << i for i, b in enumerate(pattern)),
                                             len(pattern))
    return line_idx[name], size


def packet(layer, purpose):
    """(stipple, line style, fill color, outline color, fill style) from display.drf (or fallback)."""
    key = f"{ALIASES.get(layer.lower(), layer)}_{PURPOSE_ABBR[purpose]}".lower()
    if key in packets:
        st, ls, fill, outline, *rest = packets[key]
        return st, ls, fill, outline, rest[0] if rest else "outlineStipple"
    fill, outline, st, fill_style = FALLBACK.get(layer.lower(), ("gray", "gray", "blank", "outline"))
    return st, "solid", fill, outline, fill_style


# OpenLayout display classes on top of the Virtuoso packets (ASAP7 DRM layer tables):
#   cut / marker layers -> dashed outline   (gate cut, dummy-gate/diffusion-break marker, boundaries)
#   implant / VT masks  -> solid outline    (they mark regions, they are not material)
#   well                -> keeps its sparse dot stipple (like gpdk045 NWELL)
#   vias                -> solid fill
#   pins                -> the drawing layer's color, hollow with an X spanning the shape
#   everything else (fin, active, gate, SDT, LIG, LISD, metals) keeps its stippled fill.
OUTLINE_DASHED = {"gcut", "dummy", "boundary", "sramdrc"}
OUTLINE_SOLID = {"nselect", "pselect", "slvt", "lvt", "sramvt", "text"}
SOLID_FILL = {f"v{i}" for i in range(10)}


def make_props(layer, purpose, gds_l, gds_d):
    lp = pya.LayerPropertiesNode()
    lp.name = f"{layer} {purpose}"
    lp.source = f"{gds_l}/{gds_d}"
    st, ls, fill, outline, fill_style = packet(layer, purpose)
    lp.fill_color = colors.get(fill, 0x808080)
    lp.frame_color = colors.get(outline, 0x808080)
    lp.dither_pattern = {"solid": 0, "outline": 1, "X": 1}.get(fill_style, stipple(st))
    lp.xfill = fill_style == "X"
    lp.line_style, lp.width = line_style(ls)
    lp.transparent = False
    name = layer.lower()
    if purpose == "drawing" and name in OUTLINE_DASHED | OUTLINE_SOLID:
        lp.dither_pattern = 1
        lp.xfill = False
        lp.line_style, _ = line_style("dashed" if name in OUTLINE_DASHED else "solid")
        lp.width = 2 if name in OUTLINE_DASHED else 1
    elif purpose == "drawing" and name in SOLID_FILL:
        lp.dither_pattern = 0
        lp.fill_color = lp.frame_color
        lp.xfill = False
    elif purpose == "pin":
        has_drawing = f"{ALIASES.get(name, layer)}_drg".lower() in packets
        if has_drawing:
            _, _, dfill, doutline, _ = packet(layer, "drawing")
            lp.fill_color = colors.get(dfill, lp.fill_color)
            lp.frame_color = colors.get(dfill, lp.frame_color)
        lp.dither_pattern = 1
        lp.xfill = True
        lp.line_style, lp.width = 0, 1
    return lp


entries = []
for line in open(LAYERMAP):
    f = line.split()
    if len(f) == 4 and not f[0].startswith("#") and f[1] in PURPOSE_ABBR:
        entries.append((f[0], f[1], int(f[2]), int(f[3])))
order = {n: i for i, n in enumerate(STACK)}
entries.sort(key=lambda e: order.get(e[0].lower(), len(STACK)))

view.clear_layers()
for purpose, group_name in GROUPS:
    members = [make_props(*e) for e in entries if e[1] == purpose]
    if group_name is None:
        for lp in members:
            view.insert_layer(view.end_layers(), lp)
    elif members:
        group = pya.LayerPropertiesNode()
        group.name = group_name
        for lp in members:
            group.add_child(lp)
        view.insert_layer(view.end_layers(), group)

view.save_layer_props(out)
print(f"wrote {out}: {len(entries)} layers, {len(stipple_idx)} stipples, {len(line_idx)} line styles")
