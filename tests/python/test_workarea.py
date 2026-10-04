"""Tests for the workarea model. Run with:  openlayout test   (needs the OpenLayout environment)."""
import subprocess

import pytest

from openlayout.workarea import LAYOUT, SCHEMATIC, SYMBOL, Workarea, WorkareaError


@pytest.fixture
def wa(tmp_path):
    return Workarea.create(tmp_path / "wa", "mylib")


def gds_cells(path):
    """Top-level cell names in a layout file (via KLayout batch mode)."""
    script = path.parent / "_cells.py"
    script.write_text("import pya\nl = pya.Layout()\nl.read(f)\n"
                      "print(','.join(sorted(c.name for c in l.top_cells())))\n")
    out = subprocess.run(["klayout", "-b", "-rd", f"f={path}", "-r", str(script)],
                         capture_output=True, text=True).stdout
    script.unlink()
    return out.strip().split(",")


def test_libraries_include_pdk(wa):
    names = [lib.name for lib in wa.libraries()]
    assert names[:5] == ["asap7_devices", "asap7sc7p5t_28_R", "asap7sc7p5t_28_L",
                         "asap7sc7p5t_28_SL", "asap7sc7p5t_28_SRAM"]
    assert names[-1] == "mylib"
    assert wa.library("asap7_devices").readonly
    assert not wa.library("mylib").readonly


def test_stdcell_views_include_library_layout(wa):
    inv = wa.library("asap7sc7p5t_28_R").cell("INVx1_ASAP7_75t_R")
    views = {v.name: v for v in inv.views()}
    assert set(views) == {"symbol", "layout"}
    assert views["layout"].gds_cell == "INVx1_ASAP7_75t_R" and views["layout"].path.is_file()


def test_find_from_subdirectory(wa):
    assert Workarea.find(wa.root / "libraries" / "mylib").root == wa.root


def test_new_library_and_name_checks(wa):
    lib = wa.new_library("alu")
    assert lib.path.is_dir() and wa.library("alu")
    with pytest.raises(WorkareaError):
        wa.new_library("alu")
    with pytest.raises(WorkareaError):
        wa.new_library("9bad")


def test_create_views(wa):
    lib = wa.library("mylib")
    sch = wa.new_view(lib, "inv", SCHEMATIC)
    sym = wa.new_view(lib, "inv", SYMBOL)
    lay = wa.new_view(lib, "inv", LAYOUT)
    assert [v.name for v in lib.cell("inv").views()] == ["schematic", "symbol", "layout"]
    assert sch.path.read_text().startswith("v {xschem")
    assert "type=subcircuit" in sym.path.read_text()
    assert gds_cells(lay.path) == ["inv"]
    with pytest.raises(WorkareaError):
        wa.new_view(lib, "inv", SCHEMATIC)


def test_symbol_generated_from_schematic_pins(wa):
    import os
    import re
    import shutil
    from pathlib import Path
    lib = wa.library("mylib")
    (lib.path / "inv").mkdir()
    shutil.copy(Path(os.environ["OPENLAYOUT_HOME"]) / "tests/klayout/inv_pins.sch", lib.path / "inv" / "inv.sch")
    sym = wa.new_view(lib, "inv", SYMBOL).path.read_text()
    pins = {m[4]: (float(m[0]) + 2.5, float(m[1]) + 2.5, m[5])
            for m in re.findall(r"^B 5 (\S+) (\S+) (\S+) (\S+) \{name=(\w+) dir=(\w+)\}", sym, re.M)}
    assert set(pins) == {"A", "Y", "VDD", "VSS"}
    (ax, ay, ad), (yx, yy, yd) = pins["A"], pins["Y"]
    assert ad == "in" and yd == "out" and ax < 0 < yx           # inputs left, outputs right
    assert pins["VDD"][1] < 0 < pins["VSS"][1]                    # supplies top and bottom
    assert all(v % 10 == 0 for x, y, _ in pins.values() for v in (x, y))  # pins on the 10 grid
    sel = re.search(r"^B 7 (\S+) (\S+) (\S+) (\S+) \{fill=false hide=instance\}", sym, re.M)
    assert sel, "outline-only selection box"
    x1, y1, x2, y2 = map(float, sel.groups())
    assert all(x1 <= x <= x2 and y1 <= y <= y2 for x, y, _ in pins.values())  # encloses the pins
    assert all(v % 10 == 0 for v in (x1, y1, x2, y2))             # on the grid
    assert (x1, x2, y1, y2) == (ax, yx, pins["VDD"][1], pins["VSS"][1])  # pins sit on its edges
    assert "@symname" in sym and "@name" in sym


def test_blank_symbol_without_schematic(wa):
    sym = wa.new_view(wa.library("mylib"), "lonely", SYMBOL).path.read_text()
    assert "B 7 -80 -50 80 50 {fill=false hide=instance}" in sym and "B 5 " not in sym


def test_readonly_library_is_protected(wa):
    with pytest.raises(WorkareaError):
        wa.new_view(wa.library("asap7_devices"), "x", SCHEMATIC)


def test_copy_rename_delete(wa):
    lib = wa.library("mylib")
    wa.new_view(lib, "inv", SCHEMATIC)
    wa.new_view(lib, "inv", LAYOUT)
    copy = wa.copy_cell(lib.cell("inv"), lib, "inv2")
    assert gds_cells(copy.view("layout").path) == ["inv2"]
    renamed = wa.rename_cell(copy, "buf")
    assert not (lib.path / "inv2").exists()
    assert gds_cells(renamed.view("layout").path) == ["buf"]
    trashed = wa.delete(renamed)
    assert trashed.is_dir() and lib.cell("buf") is None


def test_copy_stdcell_layout_into_design_library(wa):
    inv = wa.library("asap7sc7p5t_28_R").cell("INVx1_ASAP7_75t_R")
    copy = wa.copy_cell(inv, wa.library("mylib"), "my_inv")
    assert {v.name for v in copy.views()} == {"symbol", "layout"}
    assert gds_cells(copy.view("layout").path) == ["my_inv"]


def test_cell_for_path(wa):
    lib = wa.library("mylib")
    sch = wa.new_view(lib, "inv", SCHEMATIC)
    assert wa.cell_for_path(sch.path).key == "mylib/inv"
    std = wa.library("asap7sc7p5t_28_R")
    assert wa.cell_for_path(std.layout_gds, "INVx1_ASAP7_75t_R").key == "asap7sc7p5t_28_R/INVx1_ASAP7_75t_R"
    assert wa.cell_for_path(std.path / "INVx1_ASAP7_75t_R" / "INVx1_ASAP7_75t_R.sym").name == "INVx1_ASAP7_75t_R"
    assert wa.cell_for_path("/tmp/elsewhere.sch") is None


def test_state_roundtrip(wa):
    wa.new_view(wa.library("mylib"), "inv", SCHEMATIC)
    cell = wa.library("mylib").cell("inv")
    wa.set_state(cell, "sim", True, "PASS")
    assert wa.cell_state(cell)["sim"]["ok"] is True
