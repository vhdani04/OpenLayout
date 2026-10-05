"""Generate asap7_kpex_tech.pb.json: the ASAP7 technology description for KLayout-PEX (kpex), used by
OpenLayout's parasitic extraction (klayout/python/openlayout_kl/pex.py) for its FasterCap 3D model.

    python3 gen_kpex_tech.py            (writes asap7_kpex_tech.pb.json next to this file)

Where the numbers come from (docs/PEX.md has the full story):

Vertical stack (z in um, 0 = top of the shallow-trench oxide, fins 32 nm above it)
  - thicknesses of the gate (56 nm), LIG (48 nm), LISD (27 nm), M1 / M2 (36 nm) and the 1 nm
    source / drain sliver: the library's reference extraction (Calibre xACT 3D netlists,
    $ASAP7_STDCELLS/CDL/xAct3D_extracted, "$layer=... $thickness=...")
  - V0 20 nm, V1-V3 36, V4 / V5 48, V6-V8 64 nm: the plate capacitances between neighbouring layers
    in the library's QRC technology file (qrcTechFile_typ03_unscaledV02, readable cap coefficients),
    with one dielectric constant k = 3.23 that fits all of them
  - M3-M9 thickness 2 x minimum width (ASAP7 paper: metal and via aspect ratio 2:1)
Resistance (kpex units: mOhm / square, mOhm per via)
  - M1-M9 and V1-V8: OpenROAD-flow-scripts platforms/asap7/setRC.tcl (per-um values times the
    minimum width), which are derived from the same QRC file
  - gate, LIG, LISD, V0 and the gate / source-drain contacts: medians of the reference extraction
"""
import json
from pathlib import Path

K_ILD = 3.23          # fits the QRC plate capacitances (e.g. M2-M1: 7.937e-16 F/um2 across 36 nm)
NM = 0.001

# name, gds (layer, datatype), z bottom (nm), thickness (nm), contact above: (name, gds, thickness nm, metal above)
METALS = [
    ("gate", (7, 0), 0, 56, None),                                # LIG sits on the gate (same net, touching)
    # the source / drain node: a 1 nm sliver on the fins, 0.5 nm off the gate (LVS layer sdx), as in the
    # library's reference extraction
    ("sdx", (11, 100), 32, 1, ("sdt", (88, 0), 44, "lisd")),
    ("lig", (16, 0), 56, 48, None),
    ("lisd", (17, 0), 77, 27, ("v0", (18, 0), 20, "m1")),         # V0 lands on LISD and LIG
    ("m1", (19, 0), 124, 36, ("v1", (21, 0), 36, "m2")),
    ("m2", (20, 0), 196, 36, ("v2", (25, 0), 36, "m3")),
    ("m3", (30, 0), 268, 36, ("v3", (35, 0), 36, "m4")),
    ("m4", (40, 0), 340, 48, ("v4", (45, 0), 48, "m5")),
    ("m5", (50, 0), 436, 48, ("v5", (55, 0), 48, "m6")),
    ("m6", (60, 0), 532, 64, ("v6", (65, 0), 64, "m7")),
    ("m7", (70, 0), 660, 64, ("v7", (75, 0), 64, "m8")),
    ("m8", (80, 0), 788, 80, ("v8", (85, 0), 64, "m9")),
    ("m9", (90, 0), 932, 80, None),
]
# mOhm / square
SHEET = {"gate": 7143, "sdx": 1000, "lig": 8334, "lisd": 11243,
         "m1": 1267.5, "m2": 534.8, "m3": 563.2, "m4": 432.9, "m5": 455.8, "m6": 380.1, "m7": 400.3,
         "m8": 337.9, "m9": 355.8}
# mOhm per via
VIA = {"gcon": 10427, "sdt": 10381, "v0": 19380, "v1": 17200, "v2": 17200, "v3": 17200, "v4": 11800,
       "v5": 11800, "v6": 8200, "v7": 8200, "v8": 6300}
DEVICES = [f"{t}_{vt}" for t in ("nmos", "pmos") for vt in ("rvt", "lvt", "slvt", "sram")]


def layer(name, gds, purpose, description):
    return {"purpose": purpose, "name": name, "description": description,
            "drw_gds_pair": {"layer": gds[0], "datatype": gds[1]}}


def build():
    layers, computed, stack = [], [], []
    stack.append({"name": "subs", "layer_type": "LAYER_TYPE_SUBSTRATE",
                  "substrate_layer": {"height": 0.0, "thickness": 0.1, "reference": "sti"}})
    stack.append({"name": "sti", "layer_type": "LAYER_TYPE_FIELD_OXIDE", "field_oxide_layer": {"dielectric_k": 3.9}})
    for name, gds, z, t, contact in METALS:
        layers.append(layer(name, gds, "PURPOSE_METAL", f"ASAP7 {name.upper()}"))
        computed.append({"kind": "KIND_REGULAR", "layer_info": layer(name, gds, "PURPOSE_METAL", name),
                         "original_layer_name": name})
        metal = {"z": round(z * NM, 6), "thickness": round(t * NM, 6)}
        if contact:
            cname, cgds, ct, above = contact
            layers.append(layer(cname, cgds, "PURPOSE_VIA", f"ASAP7 {cname.upper()}"))
            computed.append({"kind": "KIND_REGULAR", "layer_info": layer(cname, cgds, "PURPOSE_VIA", cname),
                             "original_layer_name": cname})
            metal["contact_above"] = {"name": cname, "layer_below": name, "metal_above": above,
                                      "thickness": round(ct * NM, 6), "width": 0.018, "spacing": 0.018}
        stack.append({"name": name, "layer_type": "LAYER_TYPE_METAL", "metal_layer": metal})
        # the dielectric from this layer's bottom up to the next conductor's (kpex stacks them so)
        stack.append({"name": f"ild_{name}", "layer_type": "LAYER_TYPE_SIMPLE_DIELECTRIC",
                      "simple_dielectric_layer": {"dielectric_k": K_ILD, "reference": name}})
    parasitics = {
        "side_halo": 0.2,
        "resistance": {"layers": [{"layer_name": n, "resistance": r} for n, r in SHEET.items()],
                       "vias": [{"via_name": n, "resistance": r} for n, r in VIA.items()],
                       "contacts": []},
        "capacitance": {"substrates": [], "overlaps": [], "sidewalls": [], "sideoverlaps": []},
    }
    devices = {"device_model_mappings": [
        {"lvs_device_class_name": d, "spice_prefix": "N", "terminal_names": ["D", "G", "S"],
         "parameters": [{"name": "l", "lvs_parameter_name": "L"}, {"name": "w", "lvs_parameter_name": "W"}]}
        for d in DEVICES]}
    return {"name": "asap7", "layers": layers, "lvs_computed_layers": computed,
            "process_stack": {"layers": stack}, "process_parasitics": parasitics,
            "device_models": devices,
            "substrate": {"net_names": ["VSS"], "lvs_layer_names": [], "well_lvs_layer_names": []}}


if __name__ == "__main__":
    out = Path(__file__).with_name("asap7_kpex_tech.pb.json")
    out.write_text(json.dumps(build(), indent=1) + "\n")
    print(f"wrote {out}")
