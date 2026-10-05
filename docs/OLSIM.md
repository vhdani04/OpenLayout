# OLSim and the waveform viewer

OLSim (OpenLayoutSim) is OpenLayout's simulation environment for setting up, running and checking
simulations across corners and sweeps, together with its waveform viewer.

- **OLSim** holds a cell's simulation setup:
  - tests (a testbench, analyses, vector files);
  - design variables, which can sweep;
  - corners (model section, temperature, variables);
  - outputs (signals and calculator expressions) with specs.

  It runs every point with ngspice in parallel and shows the results as a table of outputs ×
  points, coloured pass / fail.
- **The waveform viewer** plots the results:
  - stacked strips, overlays across corners and sweeps;
  - A / B cursors with a readout, markers, a calculator;
  - digital lanes and buses, vector-check plots, parametric plots;
  - log / dB / phase, PNG / CSV export.

Plotting uses [pyqtgraph](https://www.pyqtgraph.org) (MIT), which is fast with millions of points.

```
openlayout olsim <lib> <cell>               the OLSim window of a testbench cell (or a .olsim file)
openlayout olsim run <lib> <cell> [--jobs N] batch run: progress, the results table, RESULT line
openlayout olsim new <lib> <cell>           create the cell's olsim view
openlayout waves [file.raw ... | history dir]  the waveform viewer
```

From the hub:

- **Tools > OLSim (F9)** on a testbench cell creates its `olsim` view the first time. It shows
  as the O chip in the Library Manager; double-click it to open it.
- **Tools > Waveform Viewer** opens the viewer.
- **CIW:** `ol.olsim(lib, cell)` and `ol.waves()` do the same.
- **xschem:** the OpenLayout menu has OLSim and Waveform Viewer entries for the schematic being
  edited.

## The testbench

A testbench is an ordinary xschem schematic: the design, supply and input sources, loads.

**New Testbench** makes one for a cell. It is in OLSim's toolbar, and the hub offers it when you
open OLSim on a cell with pins (a circuit, not a testbench). It creates `tb_<cell>` containing:

- the cell's symbol;
- the supply, a source `VDD = {vdd}` (the cell's own `vdd` / `gnd` labels are global nets, so they
  connect to it);
- a label on every pin, and a load `{cload}` on every output;
- a vector file `tb_<cell>.vec` that steps the inputs through every combination, one input changing
  at a time. The outputs are `X` (not checked) until you write the expected 0 / 1 in their column;
- the OLSim setup `tb_<cell>.olsim`, with `vdd = 0.7` and `cload = 1f` and no outputs: pick them
  with Select on Schematic.

If `tb_<cell>` already exists, OLSim on the cell opens it.

- **Design variables:** write `{vdd}`, `{cload}`, … in source and component values. Variables >
  Copy from Cellview finds them.
- **OLSim decides the rest:** the analyses, the model corner (`.lib asap7.lib <section>`) and the
  temperature. Analysis statements, `.control` blocks, `.meas`, `.lib asap7.lib` and `.temp` in
  the testbench are dropped, with a note in the Log tab. An existing testbench with its own
  `.control` block still works under OLSim.
- **Other files:** a test can also point at a schematic file or a SPICE netlist (`.sp`), with no
  workarea needed.

## Setup

The **Setup** tab edits the test selected in the Data View on the left. Right-click there to add,
copy or delete tests.

| | |
|---|---|
| Design | library / cell of the testbench, or a `.sch` / `.sp` file |
| Analyses | `tran` (step, stop, start), `dc` (source, start, stop, step), `ac` (variation, points, start, stop), `op`, `noise` - edit the parameters as `key=value` |
| Vector files | digital stimulus and expected outputs (below) |
| Simulation | model section (tt ff ss fs sf), temperature, saved signals (`all` or a list) |
| Options | extra SPICE lines, `;` separated (`.options reltol=1e-4`) |
| Post-layout | cells simulated with their **extracted** netlist instead of their schematic; **Hierarchy…** chooses per cell (below) |

- **Design variables:** a value, or a sweep.
  - `1f 2f 4f` (or `1f, 2f, 4f`) lists the values.
  - `0.6:0.05:0.8` means start : step : stop.
  - Every combination of swept variables is a point.
- **Corners:**
  - Each corner has a name, a model section, a temperature, and variable overrides
    (`vdd=0.63 cload=2f`). An override may sweep too.
  - **Nominal** runs the test's own section and temperature.
  - **Add PVT Set** adds ss / 125 °C / −10 % supply, ff / −40 °C / +10 %, tt / 125 °C and
    ss / −40 °C, scaled from `vdd`.
- **Outputs:** what each run saves. Each has a test, a name, an expression, a spec and a Plot flag.
  - **Select on Schematic…** opens the test's testbench in xschem: the hub's xschem when a hub runs
    for the workarea, else one of its own. Every net, label, pin or voltage source you select
    there is added as a plotted output (for a source, its current). The dialog lists each pick,
    "added" or "(already an output)". Shift adds to the selection; Done stops.
  - **Delete** (or Backspace, or right-click → Remove) removes the selected rows; the same works in
    the analyses, variables and corners tables.
  - A plain signal (`v("out")`) or any waveform expression is saved as a waveform. Outputs marked
    Plot are plotted after every run, across all points.
  - An expression that gives a number goes into the results table.
  - Specs: `< 10p`, `<= 1n`, `> 1G`, `>= 0`, `== 0`, `range 0.3 0.4`.

The setup is the cell's `<cell>.olsim` file (JSON). It is saved with every run, and also by
Save (Ctrl+S).

## The calculator

Output expressions and the viewer's calculator are Python syntax over waveforms and numbers.
Numbers may carry SPICE suffixes (`10p`, `1.5meg`, `3G`), and design variables are available by
name (`vdd/2`).

| | |
|---|---|
| signals | `v("out")`, `i("vdd")` (the test's first analysis); `VT VS VF IT IS` for tran / dc / ac; `v("out", "dc")`; Cadence's `"/out"` works too; `op("out")` the operating point |
| time | `value(w, x)`, `cross(w, level, n=1, edge="either"\|"rise"\|"fall")`, `delay(w1, w2, th1, th2, edge1, edge2, n1, n2)`, `propDelay(in, out, th_in, th_out, edge="fall")` (to an output edge from the input edge that caused it, whatever the polarity) |
| edges | `riseTime(w, lo=10, hi=90)`, `fallTime(w, hi=90, lo=10)`, `slewRate(w)`, `overshoot(w)`, `settlingTime(w, tol=2)` |
| periodic | `frequency(w)`, `period(w)`, `dutyCycle(w)` (level: mid-range unless given) |
| statistics | `ymax ymin xmax xmin ptp`, `average(w, x0, x1)`, `rms(w, x0, x1)`, `integ(w, x0, x1)`, `deriv(w)`, `clip(w, x0, x1)` |
| AC | `db20 db10 mag phase real imag`, `bandwidth(w, db=3)`, `ugf(w)`, `phaseMargin(w)`, `gainMargin(w)` |
| math | `+ - * / **` on waveforms and numbers; `sqrt log10 exp abs min max …` |

Examples:

```
delay(v("in"), v("out"), vdd/2, vdd/2, "rise", "fall")      propagation delay (high-to-low output)
riseTime(v("out")) ; frequency(v("osc")) ; average(i("vdd")) * vdd
cross(v("out") - v("in"), 0)                                 switching threshold of a dc sweep
bandwidth(v("out") / v("in")) ; phaseMargin(v("out"))        AC (open-loop gain for the margin)
```

## Vector files

Vector files use the HSPICE / Spectre `.vec` format. A test can list several.

- **Inputs** become PWL sources on the nodes they name.
- **Outputs** are checked against the simulation. The count of mismatches is the **vector
  errors** output, with spec `== 0`; the first mismatches show in its tooltip, all of them in
  `vector_errors.json`.

```
; a 4-bit inverter bank: d in, q = ~d expected
radix  4 4            ; bits per column: 1 (binary digit) to 4 (hex digit)
io     i o            ; i input, o output (checked), b bidirectional (driven)
vname  d[3:0] q[3:0]  ; node names; a bus names a multi-bit column's bits, MSB first
tunit  ps             ; fs ps ns us ms (default ns)
period 100            ; one vector per period - without it, each line starts with its time
trise 10              ; also tfall, slope
vih vdd               ; input high level: a number or a design variable (default vdd); vil 0
voh 0.5               ; output thresholds (default 80 % / 20 % of vih); vol 0.2
idelay 0              ; input delay; odelay: check time after each vector (default: just before the next)
0 F
5 A
A 5
F 0
```

- **Values:** `0`-`1` for bits, `0`-`F` for hex columns.
  - `X` is don't care on outputs and holds the level on inputs. `Z` holds the level.
  - A line may also be written compact: `0110`.
- **Masks:** a statement may end with a mask that limits it to some columns, one digit per column:
  `vih 0.9 1 1 0`.
- **Plotting a check:** double-click a **vector errors** cell, or use Plot Vector Check in its
  menu. The viewer shows:
  - the inputs and the outputs as simulated, buses in hex;
  - the expected outputs dashed;
  - a red ✕ at every mismatch.

## Running and results

- **Run (F5):** runs every enabled test at every corner and sweep point, `Parallel jobs` at a time.
  - Each ngspice gets one thread when they run in parallel. Several processes with 8 OpenMP
    threads each on an 8-core machine slow down a thousandfold.
  - **Stop** kills the running simulations.
- **Results** tab: one row per output, one column per point, plus a status row.
  - Values are coloured pass / fail against the spec; the min / max column spans all points.
  - Errors have a tooltip with the reason.
  - Double-click:
    - a waveform plots it at that point (the output name: at all points);
    - a scalar output name plots it against the first swept variable;
    - a status cell shows the point's deck and log.
  - Right-click: Plot Across All Points, Plot vs ‹variable›, Plot Vector Check, Open Point in Viewer,
    Show Deck and Log.
- **Histories:** every run is a history (`Interactive.1`, `.2`, …) in `sim/<lib>/<cell>/olsim/`
  (in the workarea; standalone: next to the setup file). Pick one in the Results tab's list.

```
Interactive.3/setup.json                 the setup as run
             netlist/<test>.spice        the testbench as simulated (cleaned, extracted cells swapped in)
             points/<n>/deck.sp          the ngspice deck of point n
                        ngspice.log  sim.raw  results.json  vector_errors.json
             history.json                points, values, pass / fail, notes
```

`openlayout olsim run` prints the same table on the terminal and ends with
`RESULT OLSIM <history> points=N pass=P fail=F errors=E`. It exits non-zero on failures, so it can
gate scripts.

## Post-layout simulation

**Post-layout** in a test lists cells to simulate extracted. The test then uses the cell's latest
PEX netlist instead of its schematic subcircuit.

**Hierarchy…** is the config view. It lists every cell the testbench instantiates and lets you
choose its view: schematic, or extracted. Extracted is available once the cell has a PEX netlist;
the dialog shows the netlist's path and date, or why there is none (run PEX on its layout).

- **Where the netlist comes from:** the hub's PEX button writes `verify/<lib>/<cell>/<cell>.pex.spice`,
  and KLayout's Run PEX writes `<cell>.pex.spice` next to the layout. The newer one wins.
- **Names:** `cpu8/inv` or just `inv`, or a `.pex.spice` file.
- **Stale extractions:** the Log notes when the layout changed after the extraction.
- **Pre vs post:** a copy of the test without the entry gives pre- and post-layout side by side in
  one run (Data View: Copy Test).

## The waveform viewer

The **Results** dock browses OLSim histories (point → analysis → signals) and raw files (Open, or
`openlayout waves file.raw`).

- **Browsing:**
  - The filter takes substrings or wildcards (`out*`, `i(*)`).
  - Internal BSIM-CMG device nodes (`n1#di`) are hidden unless asked for.
- **Plotting:**
  - Every signal has a checkbox: ticked means visible. Double-click or tick a signal to plot it; it
    is never plotted twice. Untick it to hide it; tick it again to bring it back.
  - The Cursors table has the same checkbox for every curve, including overlays and calculator
    results.
  - Ctrl + double-click plots a signal in a new strip.
  - Right-click for Plot in New Strip, Plot Across All Points (a OLSim history: every corner /
    sweep point overlaid), and Plot as Digital.
- **Strips:** each strip is a plot; strips with the same x quantity share their x axis.
  - AC signals plot as dB magnitude on a log axis, with the phase in a strip below.
  - Units are automatic (ps, mV, GHz, …).
- **Mouse:** the wheel zooms; left drag pans, or draws a box in **Zoom Box** mode; right drag zooms
  one axis.
  - **Merging strips:** drag a curve (press on the trace, or on its legend entry) onto another
    strip to move it there. A strip left empty is removed, so dragging one of two single-signal
    plots onto the other gives one plot with both. Curves only move between strips with the same x
    quantity (not time onto frequency), and not onto digital lanes.
- **Keys:**
  - **F** fits; **A** / **B** put a cursor at the mouse; **H** adds a horizontal cursor.
  - **M** puts a marker on the nearest curve point.
  - Click a curve to select it, then **Delete** removes it. **Ctrl+N** opens a new strip.
- **Cursors** dock: every curve's value at A and B, the difference and the slope, plus
  B − A and 1 / (B − A). On digital lanes it shows the logic level; on buses, the value.
- **Calculator:** an expression evaluated on the chosen point. A number is logged; a waveform is
  plotted.
- **Digital:** logic lanes thresholded at mid-range, buses (`q[3:0]`) as hex bands.
- **Export:** PNG (the plots) and CSV (every curve's x / y).

## Tests

- `tests/python/test_olsim.py`:
  - the calculator against analytic waveforms (delays, edges, periodic, statistics, AC: bandwidth,
    UGF, phase margin);
  - specs, vector files (buses, masks, compact lines, errors), raw files (binary multi-plot from
    ngspice, ASCII), netlist cleaning, design-variable detection, sweeps / corners;
  - full runs: 6 points with vectors, a deliberate vector mismatch, AC and DC, and post-layout
    with the PEX netlist swapped in.
- `tests/python/test_olsim_gui.py`:
  - OLSim in the hub on an xschem testbench: olsim view created, variables copied, PVT corners,
    run, results table, auto-plot, setup saved;
  - the viewer: overlays, cursors and the readout, the calculator, PNG / CSV export, curve and
    strip editing, merging strips by drag and drop;
  - vector-check and parametric plots, and an AC raw file as dB and phase.
- Both run in `openlayout test` and `openlayout doctor`.
