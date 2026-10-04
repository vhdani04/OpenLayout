"""ASAP7 technology constants used by the OpenLayout KLayout tools (from the ASAP7 DRM r1p7)."""

DBU = 0.00025          # um per database unit
NM = 4                 # database units per nm

# GDS layer numbers (datatype 0 = drawing).
LAYERS = {
    "well": 1, "fin": 2, "gate": 7, "dummy": 8, "gcut": 10, "active": 11, "nselect": 12, "pselect": 13,
    "lig": 16, "lisd": 17, "v0": 18, "m1": 19, "m2": 20, "v1": 21, "v2": 25, "m3": 30, "v3": 35,
    "m4": 40, "v4": 45, "m5": 50, "v5": 55, "m6": 60, "v6": 65, "m7": 70, "v7": 75, "m8": 80, "v8": 85,
    "m9": 90, "v9": 95, "sdt": 88, "slvt": 97, "lvt": 98, "sramdrc": 99, "boundary": 100, "sramvt": 110,
}
PIN, LABEL = 251, 2    # datatypes of the pin and label purposes

METALS = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9"]
# Minimum widths (nm): default path widths per layer.
MIN_WIDTH = {"gate": 20, "lig": 16, "lisd": 24, "m1": 18, "m2": 18, "m3": 18, "m4": 24, "m5": 24,
             "m6": 32, "m7": 32, "m8": 40, "m9": 40}
# Default vias (nm, centred on the origin), from the ASAP7 tech LEF (VIA12 ... VIA89) and, for V0,
# the library cells: cut box, cut spacing for arrays, and the pad on the layer below / above.
# Pads run along each metal's routing direction (M1, M3, M5, M7, M9 vertical; M2, M4, M6, M8
# horizontal), as in the LEF.
VIA_DEFS = {
    ("lisd", "m1"): {"cut": "v0", "box": (-9, -9, 9, 9), "space": 18,
                     "bottom": (-12, -9, 12, 9), "top": (-9, -11, 9, 11)},
    ("lig", "m1"): {"cut": "v0", "box": (-9, -9, 9, 9), "space": 18,
                    "bottom": (-10, -11, 10, 11), "top": (-9, -11, 9, 11)},
    ("m1", "m2"): {"cut": "v1", "box": (-9, -9, 9, 9), "space": 18,
                   "bottom": (-9, -11, 9, 11), "top": (-14, -9, 14, 9)},
    ("m2", "m3"): {"cut": "v2", "box": (-9, -9, 9, 9), "space": 18,
                   "bottom": (-14, -9, 14, 9), "top": (-9, -14, 9, 14)},
    ("m3", "m4"): {"cut": "v3", "box": (-9, -12, 9, 12), "space": 18,
                   "bottom": (-9, -17, 9, 17), "top": (-20, -12, 20, 12)},
    ("m4", "m5"): {"cut": "v4", "box": (-12, -12, 12, 12), "space": 24,
                   "bottom": (-23, -12, 23, 12), "top": (-12, -23, 12, 23)},
    ("m5", "m6"): {"cut": "v5", "box": (-12, -16, 12, 16), "space": 24,
                   "bottom": (-12, -27, 12, 27), "top": (-23, -16, 23, 16)},
    ("m6", "m7"): {"cut": "v6", "box": (-16, -16, 16, 16), "space": 32,
                   "bottom": (-27, -16, 27, 16), "top": (-16, -27, 16, 27)},
    ("m7", "m8"): {"cut": "v7", "box": (-16, -16, 16, 16), "space": 46,
                   "bottom": (-16, -27, 16, 27), "top": (-27, -20, 27, 20)},
    ("m8", "m9"): {"cut": "v8", "box": (-20, -20, 20, 20), "space": 57,
                   "bottom": (-20, -20, 20, 20), "top": (-20, -20, 20, 20)},
}
CONDUCTOR_STACK = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9"]   # above LISD / LIG

# Via between two conducting layers: (via layer, via size nm)
VIAS = {("lisd", "m1"): ("v0", 18), ("lig", "m1"): ("v0", 18), ("m1", "m2"): ("v1", 18),
        ("m2", "m3"): ("v2", 18), ("m3", "m4"): ("v3", 18), ("m4", "m5"): ("v4", 24),
        ("m5", "m6"): ("v5", 24), ("m6", "m7"): ("v6", 32), ("m7", "m8"): ("v7", 32),
        ("m8", "m9"): ("v8", 40)}
VT_LAYER = {"rvt": None, "lvt": "lvt", "slvt": "slvt", "sram": "sramvt"}

# Conductor connectivity for extraction ("sd" = ACTIVE outside GATE).
CONNECTIONS = [("gate", "lig"), ("sd", "lisd"), ("lig", "v0"), ("lisd", "v0"), ("v0", "m1"),
               ("m1", "v1"), ("v1", "m2"), ("m2", "v2"), ("v2", "m3"), ("m3", "v3"), ("v3", "m4"),
               ("m4", "v4"), ("v4", "m5"), ("m5", "v5"), ("v5", "m6"), ("m6", "v6"), ("v6", "m7"),
               ("m7", "v7"), ("v7", "m8"), ("m8", "v8"), ("v8", "m9")]

LAYER_NAME = {num: name for name, num in LAYERS.items()}
