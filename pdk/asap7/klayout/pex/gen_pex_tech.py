"""Generate asap7_pex.json: the ASAP7 process description of OpenLayout's parasitic extraction
(python/openlayout/pex.py) - conductor heights and dielectrics for the FasterCap 3D model, sheet
and via resistances for the resistor networks.

    python3 gen_pex_tech.py            (writes asap7_pex.json next to this file)

docs/PEX.md has the full story. In short, z = 0 is the top of the fins (the source / drain
surface):

- Metal stack (M1 up): one dielectric, k = 3.23, which fits every plate capacitance between
  neighbouring layers in the library's QRC technology file (qrcTechFile_typ03_unscaledV02);
  thicknesses from the library's Calibre xACT 3D netlists ($thickness of every resistor) for
  LIG 48, LISD 27, M1 / M2 36 nm, via heights from the QRC plate capacitances (V0 20, V1-V3 36,
  V4 / V5 48, V6-V8 64 nm), M3-M9 at 2 x the minimum width (ASAP7 paper: aspect ratio 2:1).
- Front end (below the middle of V0): calibrated against the xACT 3D netlists of the standard
  cells (pin and coupling capacitances of a set of cells; tests/pex) - gate height, substrate
  depth, the gap between gate and source / drain node and the front-end dielectric constant
  (spacers and liners: denser than the oxide above). See CALIBRATED below.
- Resistance, "reference": what the xACT 3D netlists use - M1 / M2 3.03 Ohm/sq on a width 2.5 nm
  narrower per side than drawn (about 230 Ohm/um for a minimum wire), the same resistivity for
  M3-M9, gate 7.14 Ohm/sq on a 0.5 nm wider gate, LISD 11.9 Ohm/sq on a 1.9 nm narrower one,
  LIG 8.33 Ohm/sq, V0 / V1 19.4 / 19.5 Ohm per 18 x 18 nm cut (the same specific resistance for
  V2-V8), the LIG-to-gate contact 10.4 Ohm per 20 x 18 nm; no resistance between the source /
  drain and LISD (xACT has none). The sheet resistances below refer to the drawn width (the
  width correction folded in at the minimum width: exact for minimum wires, a little high for
  wide ones), so that vias keep their full landing.
- Resistance, "openroad": OpenROAD-flow-scripts platforms/asap7/setRC.tcl (per-um values x the
  minimum width; vias per cut) for M1-M9 / V1-V8 - some 3-8x below the reference for M1 / M2.
"""
import json
from pathlib import Path

NM = 0.001

# ---- front end, calibrated (tests/pex/calibrate.py against the xACT 3D cell netlists) -----------
CALIBRATED = {
    "gate_top": 0.024,       # um above the fin top (the gate starts on the trench oxide, 32 nm below)
    "sti_depth": 0.015,      # um from the trench-oxide top down to the substrate
    "sd_gap": 0.001,         # um between the gate and the source / drain node
    "mol_top": 0.064,        # um: top of LIG / LISD (V0 on it, then M1)
    "k_feol": 4.6,           # below the middle of V0
}
K_BEOL = 3.23
FIN = 0.032                  # um: fin height above the trench oxide

# minimum widths (um) of the metals, for the OpenROAD per-um values
MIN_W = {"m1": 0.018, "m2": 0.018, "m3": 0.018, "m4": 0.024, "m5": 0.024, "m6": 0.032, "m7": 0.032,
         "m8": 0.040, "m9": 0.040}
ORFS_KOHM_PER_UM = {"m1": 0.0704175, "m2": 0.0297127, "m3": 0.031287, "m4": 0.0180365, "m5": 0.0189935,
                    "m6": 0.0118796, "m7": 0.0125096, "m8": 0.00844765, "m9": 0.00889556}
ORFS_VIA_KOHM = {"v1": 0.0172, "v2": 0.0172, "v3": 0.0172, "v4": 0.0118, "v5": 0.0118, "v6": 0.0082,
                 "v7": 0.0082, "v8": 0.0063}
CUT = {"v0": 0.018, "v1": 0.018, "v2": 0.018, "v3": 0.018, "v4": 0.024, "v5": 0.024, "v6": 0.032,
       "v7": 0.032, "v8": 0.040}
RHO_SHEET_36 = 3.031         # Ohm/sq of a 36 nm thick M1 / M2 (xACT 3D), on the width 5 nm under drawn
BIAS = 0.005                 # um narrower than drawn (both sides together), M1-M9
VIA_RAREA = 19.535 * 0.018 ** 2   # Ohm um^2 (xACT V1)


def build(c=CALIBRATED):
    gate_top, mol = c["gate_top"], c["mol_top"]
    conductors, cuts = {}, {}
    conductors["gate"] = {"z0": -FIN, "z1": gate_top, "sheet": round(7.143 * 20 / 21, 4)}   # 21 nm in xACT
    conductors["sdx"] = {"z0": 0.0, "z1": 0.0, "sheet": 1.0}                             # a plate on the fins
    conductors["lig"] = {"z0": gate_top, "z1": mol, "sheet": 8.334}
    conductors["lisd"] = {"z0": mol - 27 * NM, "z1": mol, "sheet": round(11.906 * 20.2 / 24, 4)}  # 20.2 nm
    cuts["gcon"] = {"z0": gate_top, "z1": gate_top, "bottom": "gate", "top": "lig", "rarea": 10.427 * 0.020 * 0.018}
    cuts["sdt"] = {"z0": 0.0, "z1": mol - 27 * NM, "bottom": "sdx", "top": "lisd", "rarea": 1e-7}
    cuts["v0"] = {"z0": mol, "z1": mol + 20 * NM, "bottom": "lisd", "top": "m1", "also_bottom": "lig",
                  "rarea": 19.38 * 0.018 ** 2}
    z = mol + 20 * NM
    stack = [("m1", 36, "v1", 36), ("m2", 36, "v2", 36), ("m3", 36, "v3", 36), ("m4", 48, "v4", 48),
             ("m5", 48, "v5", 48), ("m6", 64, "v6", 64), ("m7", 64, "v7", 64), ("m8", 80, "v8", 64),
             ("m9", 80, None, 0)]
    for i, (m, t, v, vt) in enumerate(stack):
        sheet = RHO_SHEET_36 * 36 / t * MIN_W[m] / (MIN_W[m] - BIAS)
        conductors[m] = {"z0": round(z, 6), "z1": round(z + t * NM, 6), "sheet": round(sheet, 4),
                         "openroad_sheet": round(ORFS_KOHM_PER_UM[m] * 1000 * MIN_W[m], 4)}
        z += t * NM
        if v:
            cuts[v] = {"z0": round(z, 6), "z1": round(z + vt * NM, 6), "bottom": m, "top": stack[i + 1][0],
                       "rarea": VIA_RAREA, "openroad_rarea": ORFS_VIA_KOHM[v] * 1000 * CUT[v] ** 2}
            z += vt * NM
    return {
        "name": "asap7",
        "units": "um, Ohm/sq, Ohm*um^2",
        "z_reference": "fin top (source / drain surface)",
        "substrate_z": round(-FIN - c["sti_depth"], 6),
        "dielectric": {"k": c["k_feol"], "interfaces": [{"z": round(mol + 10 * NM, 6), "k_above": K_BEOL}]},
        "sd_gap": c["sd_gap"],
        "conductors": conductors,
        "cuts": cuts,
    }


if __name__ == "__main__":
    out = Path(__file__).with_name("asap7_pex.json")
    out.write_text(json.dumps(build(), indent=1) + "\n", newline="\n")
    print(f"wrote {out}")
