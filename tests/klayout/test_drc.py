# The ASAP7 DRC deck, rule by rule: one small layout per rule that breaks it (the rule must fire
# there), plus clean layouts (no markers at all). All cases go into one layout, a few microns
# apart, checked in one run of the deck. KLayout batch mode:
#   klayout -b -r tests/klayout/test_drc.py
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HOME = Path(os.environ["OPENLAYOUT_HOME"])
sys.path.insert(0, str(HOME / "klayout" / "python"))

import pya  # noqa: E402

from openlayout_kl.asap7 import LAYERS  # noqa: E402
from openlayout_kl.pcells import LIBRARY, register_library  # noqa: E402

DECK = HOME / "pdk/asap7/klayout/drc/asap7.drc"
GDS = Path(os.environ.get("ASAP7_STDCELLS", HOME.parent / "pdk/asap7/asap7sc7p5t_28")) / "GDS"
PITCH = 8640                        # nm between cases: a multiple of the gate and fin grids, two rows
                                    # and the M4-M7 routing tracks
PER_ROW = 20
EXTRA = {"sramdrc": 99, "pad": 96}
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def B(layer, x1, y1, x2, y2):
    return ("box", layer, x1, y1, x2, y2)


def P(layer, *pts):
    return ("poly", layer, pts)


def ERASE(layer, x1, y1, x2, y2):
    return ("erase", layer, x1, y1, x2, y2)


def PIN(layer, x1, y1, x2, y2):
    return ("pin", layer, x1, y1, x2, y2)


INV = ("inv",)                      # the library's INVx1, flattened, at the case origin


def gates(*ks, y1=-50, y2=300):
    """gates on the 54 nm pitch (centre 27 + 54 k)"""
    return [B("gate", 17 + 54 * k, y1, 37 + 54 * k, y2) for k in ks]


SRAM = B("sramdrc", -300, -300, 700, 700)
cases = []   # (rule(s) that must fire, shapes, rules that must not fire); expect None = clean


def bad(rules, *shapes, forbid=()):
    cases.append((set(rules.split()), [s for x in shapes for s in (x if isinstance(x, list) else [x])], set(forbid)))


def clean(name, *shapes):
    cases.append((None, [s for x in shapes for s in (x if isinstance(x, list) else [x])], name))


# ---- clean references ----------------------------------------------------------------------------
clean("INVx1 from the library", INV)
clean("two gates on the pitch", gates(0, 1))
clean("a minimum M4 wire on a track", B("m4", 0, 0, 200, 24))
clean("a V4 between on-track M4 / M5", B("m4", -11, 0, 35, 24), B("m5", 0, -11, 24, 35), B("v4", 0, 0, 24, 24))

# ---- 3.1 / 3.2 ---------------------------------------------------------------------------------------
bad("GEOMETRY.NONORTHOGONAL", P("m1", (0, 0), (100, 0), (100, 100), (50, 100), (0, 50)))
bad("WELL.W.1", B("well", 0, 0, 100, 300))
bad("WELL.W.2", B("well", 0, 0, 300, 50))
bad("WELL.S.1", B("well", 0, 0, 300, 200), B("well", 0, 300, 300, 500))
bad("WELL.S.2", B("well", 0, 0, 300, 200), B("well", 350, 0, 650, 200))
bad("WELL.A.1A", B("well", 0, 0, 100, 50))
bad("WELL.A.1B", B("well", 0, 0, 500, 500), ERASE("well", 200, 200, 250, 250))
bad("WELL.GATE.EX.1", gates(0, 1), B("well", 12, -100, 400, 400))
bad("WELL.GATE.EX.2", gates(0, 1, y1=0, y2=300), B("well", -100, -100, 400, 303))

# ---- 3.3 FIN -------------------------------------------------------------------------------------
bad("FIN.W.1", B("fin", 0, 10, 300, 18))
bad("FIN.W.2", B("fin", 0, 10, 100, 17))
bad("FIN.S.1", B("fin", 0, 12, 300, 19))
bad("FIN.AUX.1", P("fin", (0, 10), (300, 10), (300, 44), (293, 44), (293, 17), (0, 17)))

# ---- 3.4 GATE ------------------------------------------------------------------------------------
bad("GATE.W.1", B("gate", 17, 0, 39, 300), gates(1))
bad("GATE.W.2", B("gate", 17, 0, 37, 30), gates(1))
bad("GATE.S.1", B("gate", 20, 0, 40, 300), gates(1))
bad("GATE.S.2", gates(0), B("gate", 67, 0, 87, 300))
bad("GATE.S.3", gates(0), forbid=["GATE.S.1"])
bad("GATE.AUX.1", P("gate", (17, 0), (37, 0), (37, 200), (80, 200), (80, 220), (17, 220)), gates(2))
bad("GATE.AUX.2", gates(0, y1=0, y2=100), gates(0, y1=140, y2=240), gates(1, y1=0, y2=240))
bad("GATE.ACTIVE.AUX.3", gates(0, 1, 2), B("active", 25, 27, 200, 108))
bad("GATE.ACTIVE.EX.1", gates(0, 2), gates(1, y1=-50, y2=110), B("active", 46, 27, 116, 108))
bad("GATE.ACTIVE.EX.2", gates(0, 1, 2), B("active", 51, 27, 116, 108))
bad("GATE.ACTIVE.S.4", gates(0, 1, 2), B("active", 42, 27, 116, 108))

# ---- 3.5 ACTIVE ----------------------------------------------------------------------------------
bad("ACTIVE.FIN.EX.1", B("fin", 0, 37, 300, 44), B("active", 46, 32, 116, 108))
bad("ACTIVE.W.1", B("active", 0, 0, 200, 20))
bad("ACTIVE.W.2", B("active", 0, 0, 200, 40))
bad("ACTIVE.W.3", B("active", 0, 0, 10, 81))
bad("ACTIVE.S.1", B("active", 0, 0, 200, 27), B("active", 0, 47, 200, 74))
bad("ACTIVE.S.2B", B("active", 0, 0, 100, 81), B("active", 130, 0, 230, 81))
bad("ACTIVE.S.2A", B("active", 0, 0, 100, 81), B("active", 150, 0, 250, 81))
bad("ACTIVE.AUX.1", B("active", 0, 0, 100, 81),                       # same diffusion net: no S.2A
    B("active", 150, 0, 250, 81), B("sdt", 76, 0, 100, 81), B("sdt", 150, 0, 174, 81), B("lisd", 76, 0, 174, 81),
    forbid=["ACTIVE.S.2A"])
bad("ACTIVE.WELL.S.4", B("well", 0, 0, 300, 300), B("active", 0, 320, 200, 401))
bad("ACTIVE.WELL.EN.1", B("well", 0, 0, 300, 300), B("active", 20, 100, 200, 181))
bad("ACTIVE.A.1A", B("active", 0, 0, 30, 27))
bad("ACTIVE.A.1B", B("active", 0, 0, 300, 162), ERASE("active", 100, 54, 130, 81))
bad("ACTIVE.AUX.1", B("active", 0, 0, 200, 81), B("nselect", 0, -27, 300, 108))
bad("ACTIVE.AUX.3", P("active", (0, 0), (200, 0), (200, 27), (100, 27), (100, 54), (200, 54), (200, 81), (0, 81)))
bad("SRAM.ACTIVE.WELL.S.5", SRAM, B("well", 0, 0, 300, 300), B("active", 0, 310, 200, 391))
bad("SRAM.ACTIVE.A.2A", SRAM, B("active", 0, 0, 16, 20))
bad("SRAM.ACTIVE.AUX.2", B("sramdrc", 0, 0, 100, 100), B("active", 100, 0, 200, 81))

# ---- 3.6 GCUT ------------------------------------------------------------------------------------
bad("GCUT.W.1", gates(0, 1, 2), B("gcut", 0, 100, 160, 110))
bad("GCUT.ACTIVE.S.1", gates(0, 1, 2), B("active", 46, 27, 116, 108), B("gcut", 0, 110, 160, 150))
bad("GCUT.GATE.EX.1", gates(0, 1, 2), B("gcut", 7, 200, 47, 240))
bad("GCUT.GATE.S.2", gates(0, 1, 2), B("gcut", 0, 200, 60, 240))
bad("GCUT.S.3", gates(0, 1, 2), B("gcut", 0, 100, 160, 140), B("gcut", 0, 160, 160, 200))
bad("GCUT.AUX.1", B("gcut", 0, 0, 100, 40))
bad("GCUT.AUX.2", gates(0, 1, 2), B("gcut", 20, 100, 54, 140))
bad("GCUT.AUX.3", gates(0, 1, 2), B("active", 46, 27, 116, 108), B("gcut", 54, 60, 108, 80))

# ---- 3.7 implants / VT ---------------------------------------------------------------------------
bad("NSELECT.W.1", B("nselect", 0, 0, 100, 200))
bad("NSELECT.W.2", B("nselect", 0, 0, 300, 50))
bad("PSELECT.W.1", B("pselect", 0, 0, 100, 200))
bad("LVT.W.1", B("lvt", 0, 0, 100, 200))
bad("SLVT.W.2", B("slvt", 0, 0, 300, 50))
bad("SRAMVT.W.1", B("sramvt", 0, 0, 100, 200))
bad("NSELECT.ACTIVE.EN.1", B("nselect", 0, 0, 300, 162), B("active", 40, 27, 200, 108))
bad("NSELECT.ACTIVE.EN.2", B("nselect", 0, 0, 300, 162), B("active", 60, 20, 200, 101))
bad("PSELECT.ACTIVE.EN.1", B("pselect", 0, 0, 300, 162), B("active", 40, 27, 200, 108))
bad("SRAM.NSELECT.ACTIVE.EN.3", SRAM, B("nselect", 0, 0, 300, 162), B("active", 10, 27, 200, 108))
bad("NSELECT.GATE.EX.1", gates(0, 1), B("nselect", 12, -100, 300, 400))
bad("NSELECT.GATE.EX.2", gates(0, 1, y1=0, y2=200), B("nselect", -100, -100, 300, 203))
bad("NSELECT.PSELECT.AUX.1", B("nselect", 0, 0, 200, 200), B("pselect", 100, 0, 300, 200))
bad("VT.AUX.2", B("lvt", 0, 0, 200, 200), B("slvt", 100, 0, 300, 200))

# ---- 3.8 SDT -------------------------------------------------------------------------------------
bad("SDT.W.1", B("active", 0, 0, 300, 81), B("sdt", 100, 0, 120, 81), B("lisd", 98, 0, 122, 81))
bad("SDT.W.2", B("sdt", 100, 0, 124, 20))
bad("SDT.W.3", B("sdt", 100, 0, 124, 40))
bad("SRAM.SDT.W.4", SRAM, B("sdt", 100, 0, 124, 15))
bad("SDT.S.1", B("sdt", 0, 0, 24, 81), B("sdt", 49, 0, 73, 81))
bad("SDT.GATE.S.2", gates(0, 1, 2), B("sdt", 44, 0, 68, 81))
bad("SDT.ACTIVE.OV.1", B("active", 0, 0, 300, 81), B("sdt", 100, 60, 124, 141), B("lisd", 100, 0, 124, 200))
bad("SDT.LISD.OV.2", B("active", 0, 0, 300, 81), B("sdt", 100, 0, 124, 81), B("lisd", 90, 0, 130, 20))
bad("SRAM.SDT.ACTIVE.OV.3", SRAM, B("active", 0, 0, 300, 81), B("sdt", 100, 70, 124, 97), B("lisd", 100, 0, 124, 200))
bad("SDT.GATE.AUX.1", gates(0, 1, 2), B("sdt", 91, 0, 115, 81))
bad("SDT.ACTIVE.AUX.2", B("active", 0, 0, 300, 81), B("sdt", 100, 27, 124, 108), B("lisd", 100, 0, 124, 200))
bad("SDT.ACTIVE.AUX.3", B("sdt", 100, 0, 124, 81), B("lisd", 100, 0, 124, 81))
bad("SDT.LISD.AUX.4", B("active", 0, 0, 300, 81), B("sdt", 100, 0, 124, 81))

# ---- 3.9 LISD ------------------------------------------------------------------------------------
bad("LISD.W.1", B("lisd", 0, 0, 20, 100))
bad("LISD.S.1", B("lisd", 0, 0, 24, 100), B("lisd", 39, 0, 63, 100))
bad("LISD.S.2", B("lisd", 0, 0, 24, 100), B("lisd", 0, 120, 200, 144))
bad("LISD.S.3", B("lisd", 0, 0, 24, 100), B("lisd", 0, 125, 24, 225))
bad("LISD.A.1", B("lisd", 0, 0, 24, 24))
bad("SRAM.LISD.S.4", SRAM, B("lisd", 0, 0, 24, 100), B("lisd", 0, 120, 24, 220))
bad("SRAM.LISD.AUX.1", B("sramdrc", 0, 0, 100, 100), B("lisd", 100, 0, 124, 100))

# ---- 3.10 LIG ------------------------------------------------------------------------------------
bad("LIG.W.1", B("lig", 0, 0, 14, 100))
bad("LIG.S.1", B("lig", 0, 0, 16, 100), B("lig", 31, 0, 47, 100))
bad("LIG.S.2", B("lig", 0, 0, 16, 100), B("lig", 0, 120, 200, 136))
bad("LIG.S.3", B("lig", 0, 0, 30, 100), B("lig", 0, 125, 30, 225))
bad("LIG.S.4", B("lig", 0, 0, 16, 100), B("lig", 0, 128, 16, 228))
bad("LIG.S.5", B("lig", 0, 0, 16, 100), B("lig", 0, 128, 30, 228))
bad("LIG.LISD.S.6", B("lig", 0, 0, 16, 100), B("lisd", 26, 0, 50, 100))
bad("LIG.LISD.OV.1", B("lig", 0, 0, 16, 100), B("lisd", 26, 0, 50, 100), B("lisd", 0, 94, 50, 118),   # same net
    forbid=["LIG.LISD.S.6"])
bad("LIG.LISD.S.7", B("lig", 0, 0, 16, 100), B("lisd", 26, 110, 50, 210))
bad("LIG.SDT.S.8", B("lig", 0, 0, 16, 100), B("sdt", 26, 0, 50, 81), B("lisd", 26, 0, 50, 81), B("active", 26, 0, 300, 81))
bad("LIG.GATE.S.9A", gates(0, 1, 2, y1=0, y2=200), B("lig", 0, 210, 160, 226))
bad("LIG.GATE.S.9B", gates(0, 1, 2), B("lig", 52, 50, 68, 150))
bad("LIG.GATE.S.10", gates(0, 1, 2), B("active", 46, 27, 116, 108), B("lig", 95, 150, 140, 166))
bad("LIG.GCUT.S.11", gates(0, 1, 2), B("gcut", 0, 100, 160, 140), B("lig", 60, 143, 100, 159))
bad("LIG.A.1", B("lig", 0, 0, 16, 18))
bad("LIG.LISD.A.2", B("lig", 0, 0, 16, 100), B("lisd", 8, 90, 32, 190))
bad("LIG.GATE.A.3 LIG.GATE.AUX.1", gates(0, 1, 2), B("lig", 80, 100, 120, 120))
bad("LIG.GATE.EX.1", gates(0, 1, 2), B("lig", 60, 100, 91, 120))
bad("LIG.LISD.OV.1", B("lig", 0, 0, 100, 16), B("lisd", 40, 10, 64, 100))
bad("SRAM.LIG.AUX.2", B("sramdrc", 0, 0, 100, 100), B("lig", 100, 0, 116, 100))

# ---- 3.11 V0 -------------------------------------------------------------------------------------
bad("V0.W.1", B("m1", 0, 0, 16, 100), B("lisd", -4, 0, 20, 100), B("v0", 0, 40, 16, 56))
bad("V0.S.1", B("m1", 0, 0, 18, 200), B("lisd", -3, 0, 21, 200), B("v0", 0, 40, 18, 58), B("v0", 0, 73, 18, 91))
bad("V0.S.2", B("m1", 0, 0, 18, 100), B("v0", 0, 40, 18, 58), B("m1", 36, 0, 54, 200), B("v0", 36, 68, 54, 86),
    B("lisd", -3, 0, 21, 100), B("lisd", 33, 0, 57, 200))
bad("V0.S.3", B("m1", 0, 0, 18, 58), B("v0", 0, 40, 18, 58), B("m1", 36, 80, 54, 200), B("v0", 36, 80, 54, 98),
    B("lisd", -3, 0, 21, 100), B("lisd", 33, 0, 57, 200), forbid=["V0.S.4"])
bad("V0.S.4", B("m1", 0, 0, 18, 100), B("v0", 0, 40, 18, 58), B("m1", 36, 78, 54, 200), B("v0", 36, 78, 54, 96),
    B("lisd", -3, 0, 21, 100), B("lisd", 33, 0, 57, 200))
bad("V0.M1.EN.1", B("m1", 0, 0, 18, 18), B("v0", 0, 0, 18, 18), B("lisd", -3, -10, 21, 30))
bad("V0.LISD.EN.2", B("m1", 0, 0, 18, 100), B("v0", 0, 40, 18, 58), B("lisd", 2, 0, 26, 100))
bad("V0.LISD.EN.3", B("m1", -50, -9, 100, 9), B("v0", 0, -9, 18, 9), B("lig", -50, -8, 100, 8), B("lisd", 2, 0, 20, 100))
bad("V0.LIG.EN.4", B("m1", -50, -8.5, 100, 9.5), B("v0", 0, -8.5, 18, 9.5), B("lig", -50, -8, 100, 8))
bad("V0.LIG.A.1", B("m1", -50, -9, 100, 9), B("v0", 0, -9, 18, 9), B("lig", -50, -7, 100, 7))
bad("V0.AUX.1", B("v0", 0, 0, 18, 18))
bad("V0.LIG.AUX.2", B("m1", -50, 0, 100, 18), B("v0", 0, 0, 18, 18), B("lig", -50, -8, 100, 8))
bad("V0.M1.AUX.3", B("m1", 0, 0, 30, 100), B("v0", 6, 40, 24, 58), B("lisd", 3, 0, 27, 100))

# ---- 3.12 M1-M3 ----------------------------------------------------------------------------------
bad("M1.W.1", B("m1", 0, 0, 16, 100))
bad("M1.S.1", B("m1", 0, 0, 18, 100), B("m1", 33, 0, 51, 100))
bad("M1.S.2", B("m1", 0, 0, 18, 100), B("m1", 0, 120, 200, 138))
bad("M1.S.3", B("m1", 0, 0, 30, 100), B("m1", 0, 125, 30, 225))
bad("M1.S.4", B("m1", 0, 0, 18, 100), B("m1", 0, 128, 18, 228))
bad("M1.S.5", B("m1", 0, 0, 18, 100), B("m1", 0, 128, 30, 228))
bad("M1.S.6", B("m1", 0, 0, 40, 40), B("m1", 50, 50, 90, 90))
bad("M1.A.1", B("m1", 0, 0, 18, 25))
bad("M2.W.1", B("m2", 0, 0, 100, 16))
bad("M3.S.1", B("m3", 0, 0, 18, 100), B("m3", 33, 0, 51, 100))

# ---- 3.13 V1-V3 ----------------------------------------------------------------------------------
M1PAD = B("m1", 0, -20, 18, 38)
M2BAR = B("m2", -50, 0, 100, 18)
bad("V1.W.1", B("m1", 0, -30, 16, 46), B("m2", -30, 0, 46, 16), B("v1", 0, 0, 16, 16))
bad("V1.S.1", M2BAR, B("v1", 0, 0, 18, 18), B("v1", 33, 0, 51, 18), M1PAD, B("m1", 33, -20, 51, 38))
bad("V1.S.2", B("m2", -50, 0, 50, 18), B("v1", 0, 0, 18, 18), M1PAD,
    B("m2", -30, 36, 100, 54), B("v1", 28, 36, 46, 54), B("m1", 28, 16, 46, 74))
bad("V1.M1.EN.1", B("m1", 0, -3, 18, 21), M2BAR, B("v1", 0, 0, 18, 18))
bad("V1.M2.AUX.2", B("m1", 0, -5, 18, 20), B("m2", -50, -5, 50, 23), B("v1", 0, 0, 18, 18), forbid=["V1.M1.EN.1"])
bad("V1.M2.EN.2", M1PAD, B("m2", 0, 0, 18, 18), B("v1", 0, 0, 18, 18))
bad("V1.AUX.1", M1PAD, B("v1", 0, 0, 18, 18))
bad("V2.M2.EN.1", B("m2", -3, 0, 21, 18), B("m3", 0, -30, 18, 48), B("v2", 0, 0, 18, 18))
bad("V3.M4.EN.2", B("m3", 0, -30, 18, 54), B("m4", -5, 0, 23, 24), B("v3", 0, 0, 18, 24))

# ---- 3.14 / 3.16 M4-M7 ---------------------------------------------------------------------------
bad("M4.W.1", B("m4", 0, 0, 200, 20))
bad("M4.W.2", B("m4", 0, 0, 200, 504))
bad("M4.W.3", B("m4", 0, 0, 200, 48))
bad("M4.W.4", B("m4", 0, 0, 200, 72), forbid=["M4.W.3"])
bad("M4.W.5", B("m4", 0, 0, 40, 24))
bad("M4.S.1", B("m4", 0, 0, 200, 24), B("m4", 0, 44, 200, 68))
bad("M4.S.2", B("m4", 0, 0, 100, 24), B("m4", 130, 0, 230, 24))
bad("M4.S.3", B("m4", 0, 0, 100, 24), B("m4", 120, 48, 220, 72))
bad("M4.S.5", B("m4", 0, 0, 100, 24), B("m4", 70, 48, 170, 72))
bad("M4.AUX.1", B("m4", 0, 10, 200, 34))
bad("M4.AUX.2", B("m4", 0, 24, 200, 48), forbid=["M4.AUX.1"])
bad("M4.AUX.3", P("m4", (0, 0), (200, 0), (200, 120), (176, 120), (176, 24), (0, 24)))
bad("M5.W.1", B("m5", 0, 0, 20, 200))
bad("M5.AUX.2", B("m5", 24, 0, 48, 200))
bad("M6.W.1", B("m6", 0, 0, 200, 30))
bad("M7.W.1", B("m7", 0, 0, 30, 200))

# ---- 3.15 / 3.17 V4-V7 ---------------------------------------------------------------------------
M4V = B("m4", -11, 0, 35, 24)
M5V = B("m5", 0, -11, 24, 35)
bad("V4.W.1", B("m4", -11, 0, 35, 24), B("m5", 0, -11, 24, 41), B("v4", 0, 0, 24, 30))
bad("V4.S.1", B("m4", -11, 0, 300, 24), B("v4", 0, 0, 24, 24), B("v4", 54, 0, 78, 24),
    B("m5", 0, -11, 24, 35), B("m5", 54, -11, 78, 35))
bad("V4.M4.EN.1", B("m4", -5, 0, 49, 24), M5V, B("v4", 0, 0, 24, 24))
bad("V4.AUX.1", M4V, B("v4", 0, 0, 24, 24))
bad("V4.M5.AUX.2", M4V, B("m5", -24, -11, 48, 35), B("v4", 0, 0, 24, 24))
bad("V5.W.1", B("v5", 0, 0, 30, 32))
bad("V6.W.1", B("v6", 0, 0, 32, 40))
bad("V7.W.1", B("v7", 0, 0, 40, 32))

# ---- 3.18 M8-M9 / 3.19 V8-V9 ---------------------------------------------------------------------
bad("M8.W.1", B("m8", 0, 0, 30, 300))
bad("M8.W.2", B("m8", 0, 0, 50, 500))
bad("M8.W.5", B("m8", 0, 0, 2100, 2100))
bad("M8.S.1", B("m8", 0, 0, 100, 300), B("m8", 130, 0, 230, 300))
bad("M8.S.3", B("m8", 0, 0, 50, 200), B("m8", 0, 240, 50, 440))
bad("M8.S.5", B("m8", 0, 0, 100, 300), B("m8", 170, 0, 270, 300))
bad("M8.A.1", B("m8", 0, 0, 50, 100))
bad("M8.L.1", P("m8", (0, 0), (300, 0), (300, 120), (200, 120), (200, 100), (0, 100)))
bad("M9.W.1", B("m9", 0, 0, 30, 300))
bad("V8.W.1", B("m8", -20, -20, 100, 100), B("m9", -20, -20, 100, 100), B("v8", 0, 0, 50, 50))
bad("V8.S.1", B("m8", -20, -20, 200, 60), B("m9", -20, -20, 200, 60), B("v8", 0, 0, 40, 40), B("v8", 90, 0, 130, 40))
bad("V8.M8.EN.1", B("m8", -10, -10, 50, 50), B("m9", -20, -20, 60, 60), B("v8", 0, 0, 40, 40))
bad("V8.AUX.1", B("v8", 0, 0, 40, 40))
bad("V9.W.1", B("v9", 0, 0, 50, 50))

# ---- OpenLayout ----------------------------------------------------------------------------------
bad("OL.PIN.M1", PIN("m1", 0, 0, 18, 18))
clean("a pin on its metal", B("m1", 0, 0, 18, 100), PIN("m1", 0, 40, 18, 58))

# ---- rules that run through code of their own (directions, SRAM variants, wide metal) -------------
bad("SRAM.ACTIVE.A.2B", SRAM, B("active", 0, 0, 300, 162), ERASE("active", 100, 54, 115, 81))
bad("SRAM.ACTIVE.WELL.EN.2", SRAM, B("well", 0, 0, 300, 300), B("active", 10, 100, 200, 181))
bad("SRAM.LIG.GATE.A.4 SRAM.LIG.GATE.OV.2", SRAM, gates(0, 1, 2), B("lig", 80, 100, 120, 120))
bad("SRAM.SDT.LISD.OV.4", SRAM, B("active", 0, 0, 300, 81), B("sdt", 100, 0, 124, 81), B("lisd", 90, 0, 130, 10))
bad("SRAM.NSELECT.ACTIVE.EN.4", SRAM, B("nselect", 0, 0, 300, 162), B("active", 60, 10, 200, 91))
bad("M5.S.1", B("m5", 0, 0, 24, 200), B("m5", 44, 0, 68, 200))
bad("M5.S.3", B("m5", 0, 0, 24, 100), B("m5", 48, 120, 72, 220))
bad("M5.S.5", B("m5", 0, 0, 24, 100), B("m5", 48, 70, 72, 170))
bad("M5.AUX.1", B("m5", 10, 0, 34, 200))
bad("M5.W.5", B("m5", 0, 0, 24, 40))
bad("M6.S.1", B("m6", 0, 0, 200, 32), B("m6", 0, 60, 200, 92))
bad("M8.S.2", B("m8", 0, 0, 300, 100), B("m8", 100, 140, 150, 400))
bad("M8.S.4", B("m8", 0, 0, 70, 300), B("m8", 120, 0, 190, 300), forbid=["M8.S.1"])
bad("M8.S.6", B("m8", 0, 0, 150, 300), B("m8", 250, 0, 400, 300))
bad("M8.W.3", B("m8", 0, 0, 70, 1300))
bad("V2.M3.EN.2", B("m2", -30, 0, 48, 18), B("m3", 0, 0, 18, 18), B("v2", 0, 0, 18, 18))
bad("V3.M3.EN.1", B("m3", -3, -3, 21, 27), B("m4", -30, 0, 54, 24), B("v3", 0, 0, 18, 24))
bad("V4.S.3", B("v4", 0, 0, 24, 24), B("v4", 44, 44, 68, 68))
bad("V8.S.2", B("v8", 0, 0, 40, 40), B("v8", 80, 80, 120, 120))
bad("V8.M9.EN.2", B("m8", -20, -20, 60, 60), B("m9", -10, -10, 50, 50), B("v8", 0, 0, 40, 40))


# ---- OpenLayout's own generators: frame, transistor PCells, vias -----------------------------------
def frame_inv(ly):
    """INVx1 from the standard-cell frame and the row-mode nMOS / pMOS (as tests/klayout/test_stdcell.py)"""
    from openlayout_kl import stdcell
    c = ly.create_cell("INV")
    stdcell.draw_frame(c, 3)
    for kind in ("nmos", "pmos"):
        pc = ly.create_cell(kind, LIBRARY, {"row": True, "nfin": 3, "nf": 1})
        c.insert(pya.CellInstArray(pc.cell_index(), pya.Trans()))
    return c


def via(layers, x=0, y=0):
    def make(ly):
        c = ly.create_cell("VIA")
        pc = ly.create_cell("via", LIBRARY, {"layers": layers})
        c.insert(pya.CellInstArray(pc.cell_index(), pya.Trans(round(x * 4), round(y * 4))))
        return c
    return ("cell", make)


clean("INVx1 from the frame + transistor PCells", ("cell", frame_inv))
# vias centred on the routing tracks where the metals have them (M4 / M6 horizontal, M5 / M7 vertical)
for layers, x, y in (("m1-m2", 0, 0), ("m2-m3", 0, 0), ("m3-m4", 0, 12), ("m4-m5", 12, 12), ("m5-m6", 12, 16),
                     ("m6-m7", 16, 16), ("m7-m8", 16, 0), ("m8-m9", 0, 0)):
    cases.append((None, [via(layers, x, y)], f"via {layers} (a lone pad may be under the minimum area)"))


# ---- build, run, compare -------------------------------------------------------------------------
def build(path):
    ly = pya.Layout()
    ly.dbu = 0.00025
    top = ly.create_cell("TOP")
    lib = pya.Layout()
    lib.read(str(GDS / "asap7sc7p5t_28_R_220121a.gds"))
    inv = lib.cell("INVx1_ASAP7_75t_R")
    register_library()
    scratch = pya.Layout()
    scratch.dbu = 0.00025
    scratch.technology_name = "asap7"
    regions = defaultdict(pya.Region)
    origins = []
    for i, (_, shapes, _) in enumerate(cases):
        ox, oy = (i % PER_ROW) * PITCH, (i // PER_ROW) * PITCH
        origins.append((ox, oy))
        local = defaultdict(pya.Region)

        def box(x1, y1, x2, y2):
            return pya.Box(round((ox + x1) * 4), round((oy + y1) * 4), round((ox + x2) * 4), round((oy + y2) * 4))
        for s in shapes:
            if s[0] == "inv":
                for li in lib.layer_indexes():
                    info = lib.get_info(li)
                    if info.datatype == 0:
                        r = pya.Region(inv.begin_shapes_rec(li)).moved(ox * 4, oy * 4)
                        local[(info.layer, 0)] += r
            elif s[0] in ("box", "pin"):
                num = LAYERS.get(s[1], EXTRA.get(s[1]))
                local[(num, 251 if s[0] == "pin" else 0)].insert(box(*s[2:]))
            elif s[0] == "poly":
                num = LAYERS[s[1]]
                local[(num, 0)].insert(pya.Polygon([pya.Point(round((ox + x) * 4), round((oy + y) * 4)) for x, y in s[2]]))
            elif s[0] == "cell":
                c = s[1](scratch)
                for li in scratch.layer_indexes():
                    info = scratch.get_info(li)
                    local[(info.layer, info.datatype)] += pya.Region(c.begin_shapes_rec(li)).moved(ox * 4, oy * 4)
            elif s[0] == "erase":
                num = LAYERS[s[1]]
                local[(num, 0)] -= pya.Region(box(*s[2:]))
        for k, r in local.items():
            regions[k] += r
    for (num, dt), r in regions.items():
        top.shapes(ly.layer(num, dt)).insert(r)
    ly.write(path)
    return origins


tmp = Path(tempfile.mkdtemp())
gds = tmp / "cases.gds"
origins = build(str(gds))
rep = tmp / "cases.lyrdb"
run = subprocess.run(["klayout", "-b", "-r", str(DECK), "-rd", f"input={gds}", "-rd", "topcell=TOP",
                      "-rd", f"report={rep}"], capture_output=True, text=True)
check("the deck runs", run.returncode == 0 and rep.exists(), (run.stdout + run.stderr)[-600:])

found = defaultdict(set)          # case index -> rules with markers there
rdb = pya.ReportDatabase("drc")
rdb.load(str(rep))
for item in rdb.each_item():
    rule = rdb.category_by_id(item.category_id()).name()
    for v in item.each_value():
        if v.is_box():
            b = v.box()
        elif v.is_edge_pair():
            b = v.edge_pair().bbox()
        elif v.is_edge():
            b = v.edge().bbox()
        elif v.is_polygon():
            b = v.polygon().bbox()
        else:
            continue
        cx, cy = b.center().x * 1000, b.center().y * 1000      # nm
        col, row = int((cx + 1000) // PITCH), int((cy + 1000) // PITCH)
        found[row * PER_ROW + col].add(rule)

for i, (expect, _, extra) in enumerate(cases):
    got = found.get(i, set())
    if expect is None:
        if "minimum area" in extra:
            got = {r for r in got if not r.endswith(".A.1")}
        check(f"clean: {extra}", not got, sorted(got))
    else:
        name = " ".join(sorted(expect))
        missing = expect - got
        wrong = extra & got
        check(f"{name} fires" + (f" (and not {' '.join(sorted(extra))})" if extra else ""), not missing and not wrong,
              f"missing {sorted(missing)}" if missing else f"also {sorted(wrong)}" if wrong else "")

# every rule of the deck is exercised by a case (or listed as checked only on the library)
deck_rules = {rdb.category_by_id(c.rdb_id()).name() for c in rdb.each_category()}
tested = set().union(*(e for e, _, _ in cases if e))
print(f"rules with seeded cases: {len(tested)} of {len(deck_rules)} in the deck")
print("without a case of their own:", " ".join(sorted(deck_rules - tested)))
print("PASS drc" if not failures else f"FAIL drc: {', '.join(failures)}")
