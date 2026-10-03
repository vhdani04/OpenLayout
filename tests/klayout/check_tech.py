# Smoke test: ASAP7 technology is registered and the std-cell libraries load under it.
import pya
tech_ok = pya.Technology.has_technology("asap7") and pya.Technology.technology_by_name("asap7").dbu == 0.00025
libs = [n for n in pya.Library.library_names() if n.startswith("asap7sc7p5t_28_")]
cells = {n: pya.Library.library_by_name(n, "asap7").layout().cells() for n in libs}
ok = tech_ok and len(libs) == 4 and all(c > 200 for c in cells.values())
print(("PASS" if ok else "FAIL") + f" klayout tech asap7={tech_ok} libraries={cells}")
