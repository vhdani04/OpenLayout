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
