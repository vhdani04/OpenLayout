"""Maestro engine: the calculator, vector files, raw files, netlist handling and full runs
(corners x sweeps, vector checks, AC / DC analyses) with ngspice."""
import json
import math
import subprocess

import numpy as np
import pytest

from openlayout.maestro import calc, rawfile, vectors
from openlayout.maestro.calc import CalcError, Context, Waveform, evaluate
from openlayout.maestro.engine import History, Run, clean_netlist, deck, design_variables
from openlayout.maestro.setup import Analysis, Corner, Output, Setup, sweep_values
from openlayout.maestro.setup import Test as MTest

INV = """* inverter testbench
Vdd vdd 0 {vdd}
N1 out in 0 0 nmos_rvt l=20n nfin=2
N2 out in vdd vdd pmos_rvt l=20n nfin=2
C1 out 0 {cload}
.control
tran 1p 1n
.endc
.end
"""
VEC = """; in toggles, out is its inverse
radix 1 1
io    i o
vname in out
tunit ps
period 100
trise 10
tfall 10
vih vdd
0 1
1 0
0 1
1 0
"""


# ---- calculator ---------------------------------------------------------------------------------
def test_si_and_fmt():
    assert calc.si("10p") == pytest.approx(1e-11)
    assert calc.si("1.5meg") == pytest.approx(1.5e6)
    assert calc.si("3G") == pytest.approx(3e9)
    assert calc.si(" 0.7 ") == 0.7
    assert calc.fmt(1.234e-11) == "12.34p"
    assert calc.fmt(2.5e6) == "2.5M"
    assert calc.prepare("delay(v('a'), v('b')) < 10p") == "delay(v('a'), v('b')) < (10*1e-12)"
    assert calc.prepare('v("n10p")') == 'v("n10p")'          # not inside strings


def ramp():
    t = np.linspace(0, 1e-9, 1001)
    a = np.clip((t - 1e-10) / 1e-10, 0, 1) * 0.7                       # rises 100..200 ps
    b = 0.7 - np.clip((t - 1.5e-10) / 2e-10, 0, 1) * 0.7               # falls 150..350 ps
    return Waveform(t, a, "a", "time"), Waveform(t, b, "b", "time")


def test_cross_delay_edges():
    a, b = ramp()
    assert calc.cross(a, 0.35) == pytest.approx(1.5e-10, rel=1e-3)
    assert calc.delay(a, b, 0.35, 0.35, "rise", "fall") == pytest.approx(1.0e-10, rel=1e-3)
    assert calc.riseTime(a) == pytest.approx(0.8e-10, rel=1e-3)        # 10..90 %
    assert calc.fallTime(b) == pytest.approx(1.6e-10, rel=1e-3)
    with pytest.raises(CalcError, match="crosses"):
        calc.cross(a, 0.35, n=2)


def test_periodic_and_stats():
    t = np.linspace(0, 1e-8, 20001)
    sq = Waveform(t, ((t * 1e9) % 1 < 0.25).astype(float), "clk", "time")      # 1 GHz, 25 % duty
    assert calc.frequency(sq) == pytest.approx(1e9, rel=1e-3)
    assert calc.dutyCycle(sq) == pytest.approx(25, abs=0.5)
    s = Waveform(t, np.sin(2 * math.pi * 1e9 * t), "s", "time")
    assert calc.rms(s) == pytest.approx(1 / math.sqrt(2), rel=1e-3)
    assert calc.average(s) == pytest.approx(0, abs=1e-3)
    assert calc.ptp(s) == pytest.approx(2, rel=1e-3)
    assert calc.value(calc.deriv(s), 0.0) == pytest.approx(2 * math.pi * 1e9, rel=1e-2)


def test_ac_functions():
    f = np.logspace(3, 12, 901)
    h = Waveform(f, 100 / (1 + 1j * f / 1e6) / (1 + 1j * f / 1e9), "h", "frequency")   # 40 dB, poles 1 MHz / 1 GHz
    assert calc.bandwidth(h) == pytest.approx(1e6, rel=0.02)
    assert calc.ugf(h) == pytest.approx(9.95e7, rel=0.02)
    assert calc.phaseMargin(h) == pytest.approx(180 - 90 - math.degrees(math.atan(0.0995)), abs=1)
    assert calc.value(calc.db20(h), 1e3) == pytest.approx(40, abs=0.01)


def test_specs():
    assert calc.check_spec(5e-12, "< 10p") is True
    assert calc.check_spec(5e-12, "> 10p") is False
    assert calc.check_spec(0.35, "range 0.3 0.4") is True
    assert calc.check_spec(0, "== 0") is True
    assert calc.check_spec(1.0, "") is None
    with pytest.raises(CalcError):
        calc.check_spec(1.0, "about 3")


def test_expressions_on_plots():
    a, b = ramp()
    plot = rawfile.Plot("Transient Analysis", ["time", "v(a)", "v(b)"], ["time", "voltage", "voltage"],
                        np.vstack([a.x, a.y, b.y]))
    ctx = Context([plot], {"vdd": "0.7"}, "tran")
    assert evaluate('delay(v("a"), VT("/b"), vdd/2, vdd/2, "rise", "fall")', ctx) == pytest.approx(1e-10, rel=1e-3)
    w = evaluate('v("a") - v("b")', ctx)
    assert isinstance(w, Waveform) and w.y[-1] == pytest.approx(0.7)
    with pytest.raises(CalcError, match="not in the tran results"):
        evaluate('v("nope")', ctx)
    with pytest.raises(CalcError, match="syntax"):
        evaluate("delay(", ctx)
    with pytest.raises(CalcError):
        evaluate("__import__('os')", ctx)                      # no builtins


# ---- vector files -------------------------------------------------------------------------------
def test_vector_parse_and_sources(tmp_path):
    f = tmp_path / "bus.vec"
    f.write_text("radix 1 4\nio i o\nvname clk q[3:0]\ntunit ns\nvih 0.9\nvoh 0.5 0 1\n"
                 "0 1 A\n1 0 X\n2.5 1 F\n")
    vf = vectors.parse(f)
    assert [b.name for b in vf.bits] == ["clk", "q[3]", "q[2]", "q[1]", "q[0]"]
    assert vf.times == pytest.approx([0, 1e-9, 2.5e-9])
    assert [b.values for b in vf.bits][1:] == [["1", "X", "1"], ["0", "X", "1"], ["1", "X", "1"], ["0", "X", "1"]]
    assert vf.bits[1].settings["voh"] == "0.5" and "voh" not in vf.bits[0].settings
    src = "\n".join(vf.sources({}))
    assert "Vvec_clk clk 0 PWL(0 0.9" in src and "q[" not in src          # outputs are not driven
    with pytest.raises(vectors.VectorError, match="fit"):
        bad = tmp_path / "bad.vec"
        bad.write_text("radix 1\nio i\nvname a\nperiod 1\n2\n")
        vectors.parse(bad)


def test_vector_check():
    vf = vectors.VectorFile("x", [vectors.Bit("out", "o", 0, values=["1", "0", "1"])], [0, 1e-10, 2e-10],
                            1e-10, {})
    t = np.linspace(0, 3e-10, 301)
    good = Waveform(t, np.where((t >= 1e-10) & (t < 2e-10), 0.0, 0.7), "out", "time")
    stuck = Waveform(t, np.full_like(t, 0.7), "out", "time")
    assert vf.check(lambda n: good, {"vdd": "0.7"}) == []
    errs = vf.check(lambda n: stuck, {"vdd": "0.7"})
    assert len(errs) == 1 and errs[0]["expected"] == "0" and errs[0]["got"] == "1"


# ---- raw files ----------------------------------------------------------------------------------
def test_raw_binary_multi_plot(tmp_path):
    (tmp_path / "t.sp").write_text("* raw\n.lib asap7.lib tt\nV1 a 0 pwl(0 0 1n 0.7) ac 1\nR1 a b 1k\nC1 b 0 1f\n"
                                   ".tran 10p 1n\n.dc V1 0 0.7 0.1\n.ac dec 5 1e6 1e12\n.end\n")
    subprocess.run(["ngspice", "-b", "-r", "t.raw", "t.sp"], cwd=tmp_path, capture_output=True, timeout=120)
    plots = rawfile.read(tmp_path / "t.raw")
    kinds = sorted(p.kind for p in plots)
    assert kinds == ["ac", "dc", "tran"]
    ac = next(p for p in plots if p.kind == "ac")
    assert ac.complex and abs(ac["v(b)"][0]) == pytest.approx(1, rel=1e-3)
    tran = next(p for p in plots if p.kind == "tran")
    assert tran.scale == "time" and tran["b"][-1] > 0.6                       # bare node names work


def test_raw_ascii(tmp_path):
    f = tmp_path / "a.raw"
    f.write_text("Title: t\nDate: x\nPlotname: Transient Analysis\nFlags: real\nNo. Variables: 2\n"
                 "No. Points: 3\nVariables:\n\t0\ttime\ttime\n\t1\tv(out)\tvoltage\nValues:\n"
                 " 0\t0.0\n\t0.1\n 1\t1e-9\n\t0.5\n 2\t2e-9\n\t0.7\n")
    p = rawfile.read(f)[0]
    assert p.kind == "tran" and list(p["v(out)"]) == [0.1, 0.5, 0.7]


# ---- netlists -----------------------------------------------------------------------------------
def test_clean_netlist_and_variables():
    body, removed = clean_netlist(INV + ".lib asap7.lib ff\n.temp 85\n.tran 1p 2n\n+ uic\n.meas tran x max v(out)\n")
    assert ".control" not in body and ".tran" not in body and "uic" not in body and ".end" not in body
    assert ".lib" not in body and ".temp" not in body and "C1 out 0 {cload}" in body
    assert any(".control" in r for r in removed)
    assert design_variables(body + ".param k=2\nR1 a b {k*rload}\n") == ["vdd", "cload", "rload"]


def test_sweeps_and_points():
    assert sweep_values("1f 2f, 4f") == ["1f", "2f", "4f"]
    assert sweep_values("0.6:0.1:0.8") == ["600m", "700m", "800m"]
    s = Setup(tests=[MTest("t", {"netlist": "x"}, [Analysis("op")])], variables={"vdd": "0.7", "c": "1f 2f"},
              corners=[Corner("ss", True, "ss", "125", {"vdd": "0.63"}), Corner("off", False)])
    pts = s.points()
    assert [(p.corner, p.section, p.temp, p.variables["vdd"], p.variables["c"]) for p in pts] == [
        ("Nominal", "tt", "27", "0.7", "1f"), ("Nominal", "tt", "27", "0.7", "2f"),
        ("ss", "ss", "125", "0.63", "1f"), ("ss", "ss", "125", "0.63", "2f")]
    assert pts[1].label == "Nominal c=2f"
    text = deck(s, pts[3], "R1 a 0 1k\n", [])
    assert ".lib asap7.lib ss" in text and ".temp 125" in text and ".param vdd=0.63 c=2f" in text and ".op" in text


# ---- full runs ----------------------------------------------------------------------------------
def inverter_setup(tmp_path, vec=VEC):
    (tmp_path / "inv.sp").write_text(INV)
    (tmp_path / "stim.vec").write_text(vec)
    s = Setup(tests=[MTest("tran", {"netlist": "inv.sp"}, [Analysis("tran", True, {"step": "0.5p", "stop": "400p"})],
                          ["stim.vec"])],
              variables={"vdd": "0.7", "cload": "0.5f 2f"},
              corners=[Corner("ss_hot", True, "ss", "125", {"vdd": "0.63"}),
                       Corner("ff_cold", True, "ff", "-40", {"vdd": "0.77"})],
              outputs=[Output("tran", "tphl", 'delay(v("in"), v("out"), vdd/2, vdd/2, "rise", "fall")', "< 8p"),
                       Output("tran", "out", 'v("out")', "", True),
                       Output("tran", "broken", 'v("nonode")')],
              jobs=4)
    s.save(tmp_path / "inv.maestro")
    return Setup.load(tmp_path / "inv.maestro")


def test_run_corners_sweeps_vectors(tmp_path):
    s = inverter_setup(tmp_path)
    seen = []
    h = Run(s, tmp_path / "results").run(lambda d, t, m: seen.append((d, t)))
    assert h.data["status"] == "done" and len(h.points) == 6 and seen[-1] == (6, 6)
    tphl = [h.result(p["index"])["tphl"] for p in h.points]
    vals = [r["value"] for r in tphl]
    assert all(2e-12 < v < 3e-11 for v in vals)
    assert vals[1] > vals[0] and vals[3] > vals[2]                      # bigger load: slower
    assert vals[4] < vals[0] < vals[2]                                  # ff cold < tt < ss hot
    assert [r["pass"] for r in tphl] == [v < 8e-12 for v in vals]
    assert all(h.result(i)["vector errors"]["value"] == 0 for i in range(6))
    assert "not in the tran results" in h.result(0)["broken"]["error"]
    assert h.result(0)["out"]["value"] == {"wave": 'v(out)'}
    # the history on disk: reload, re-evaluate a waveform, the testbench's .control block reported
    h2 = History.load(h.path)
    w = h2.wave(5, "out")
    assert isinstance(w, Waveform) and len(w.x) > 100
    assert any(".control" in n for n in h2.data["notes"])
    assert (h.path / "points" / "0" / "deck.sp").read_text().count("Vvec_in") == 1


def test_vector_mismatch_is_reported(tmp_path):
    wrong = VEC.replace("1 0\n0 1\n1 0\n", "1 1\n0 1\n1 0\n")               # expects out=1 while in=1
    s = inverter_setup(tmp_path, wrong)
    s.corners = []
    s.variables["cload"] = "1f"
    h = Run(s, tmp_path / "results").run()
    r = h.result(0)["vector errors"]
    assert r["value"] == 1 and r["pass"] is False and "expected 1 got 0" in r["first"][0]
    errs = json.loads((h.path / "points" / "0" / "vector_errors.json").read_text())
    assert errs[0]["signal"] == "out" and 1e-10 < errs[0]["time"] < 2e-10


def test_post_layout_swap(tmp_path):
    """A test with a cell "extracted": its PEX netlist replaces the schematic subcircuit."""
    import os
    from pathlib import Path
    from openlayout import pex
    gds = Path(os.environ["ASAP7_STDCELLS"]) / "GDS" / "asap7sc7p5t_28_R_220121a.gds"
    pex.extract(gds, "INVx1_ASAP7_75t_R", tmp_path / "x.spice")
    (tmp_path / "inv.pex.spice").write_text((tmp_path / "x.spice").read_text().replace("INVx1_ASAP7_75t_R", "inv"))
    (tmp_path / "tb.sp").write_text("* FO2 inverter\n.subckt inv A VDD VSS Y\nN1 Y A VSS VSS nmos_rvt l=20n nfin=3\n"
                                    "N2 Y A VDD VDD pmos_rvt l=20n nfin=3\n.ends\nVdd vdd 0 0.7\n"
                                    "Vin in 0 pwl(0 0 20p 0 30p 0.7)\nX1 in vdd 0 out inv\nX2 out vdd 0 o2 inv\n"
                                    "X3 out vdd 0 o3 inv\n")
    tran = [Analysis("tran", True, {"step": "0.1p", "stop": "100p"})]
    s = Setup(tests=[MTest("sch", {"netlist": "tb.sp"}, tran),
                     MTest("pex", {"netlist": "tb.sp"}, tran, extracted=["inv.pex.spice"])],
              outputs=[Output(t, "tphl", 'delay(v("in"), v("out"), 0.35, 0.35, "rise", "fall")') for t in ("sch", "pex")],
              jobs=2)
    s.path = str(tmp_path / "pl.maestro")
    h = Run(s, tmp_path / "res").run()
    by_test = {p["test"]: h.result(p["index"])["tphl"]["value"] for p in h.points}
    assert by_test["pex"] > 1.15 * by_test["sch"], by_test                 # the parasitics slow it down
    assert any("inv extracted (inv.pex.spice, replaced)" in n for n in h.data["notes"])
    pex_point = next(p["index"] for p in h.points if p["test"] == "pex")
    d = (h.path / "points" / str(pex_point) / "deck.sp").read_text()
    assert "* inv: extracted (PEX)" in d and d.count(".subckt inv") == 1 and "\nR1 " in d


def test_ac_and_dc_analyses(tmp_path):
    (tmp_path / "rc.sp").write_text("* RC\nV1 in 0 dc {vin} ac 1\nR1 in out {r}\nC1 out 0 1f\n")
    s = Setup(tests=[MTest("ac", {"netlist": "rc.sp"}, [Analysis("ac", True, {"start": "1meg", "stop": "1T"}),
                                                      Analysis("dc", True, {"source": "V1", "start": "0", "stop": "1",
                                                                            "step": "0.1"})])],
              variables={"vin": "0", "r": "1k 2k"},
              outputs=[Output("ac", "f3db", 'bandwidth(v("out"))'),
                       Output("ac", "gain", 'db20(v("out"))', plot=True),
                       Output("ac", "dcgain", 'value(v("out"), 0.5)', analysis="dc")], jobs=2)
    s.path = str(tmp_path / "rc.maestro")
    h = Run(s, tmp_path / "res").run()
    f3 = [h.result(i)["f3db"]["value"] for i in range(2)]
    assert f3[0] == pytest.approx(1 / (2 * math.pi * 1e3 * 1e-15), rel=0.02)
    assert f3[1] == pytest.approx(f3[0] / 2, rel=0.02)
    assert h.result(0)["dcgain"]["value"] == pytest.approx(0.5, rel=1e-3)
