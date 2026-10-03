# Generate the KLayout technology file (asap7.lyt) for ASAP7.
# Run:  klayout -b -r gen_asap7_lyt.py -rd out=tech/asap7/asap7.lyt
import pya

METALS = {f"M{i}": n for i, n in enumerate([19, 20, 30, 40, 50, 60, 70, 80, 90], start=1)}
VIAS = {f"V{i}": n for i, n in enumerate([21, 25, 35, 45, 55, 65, 75, 85], start=1)}

tech = pya.Technology()
tech.name = "asap7"
tech.description = "ASAP7 7nm FinFET predictive PDK (OpenLayout)"
tech.dbu = 0.00025
tech.layer_properties_file = "asap7.lyp"
tech.add_other_layers = True

stack = pya.NetTracerConnectivity()
stack.name = "asap7"
stack.description = "Front end through M9"
# Drawn shapes and pin shapes conduct together; source/drain is active outside the gate.
stack.symbol("GATE", "7/0+7/251")
stack.symbol("SD", "11/0-7/0")
stack.symbol("LIG", "16/0+16/251")
stack.symbol("LISD", "17/0+17/251")
for name, n in METALS.items():
    stack.symbol(name, f"{n}/0+{n}/251")
stack.connection("GATE", "LIG")
stack.connection("SD", "LISD")
stack.connection("LIG", "18/0", "M1")
stack.connection("LISD", "18/0", "M1")
for i in range(1, 9):
    stack.connection(f"M{i}", f"{VIAS[f'V{i}']}/0", f"M{i + 1}")
tech.component("connectivity").add(stack)

open(out, "w").write(tech.to_xml())
print(f"wrote {out}")
