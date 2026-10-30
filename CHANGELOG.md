# Changelog

## Unreleased

### Schematic (xschem)
- **Caps Lock no longer changes the keys**: with Caps Lock on, `c` reached xschem as `C` (place arc),
  so copy drew arcs/circles, and the other lowercase keys (`x`, `p`, `l`, `r`, `i` ...) did nothing.
  A key pressed with Caps Lock is now re-issued as if it were off (the letter's case follows Shift).
- **Add Instance** (`i`, `Insert`, *Tools ▸ Add Instance…*, the toolbar's symbol button, the
  right-click menu): a symbol browser laid out like the hub's Library Manager - the workarea's
  libraries and a *Basic* library of xschem's devices, a filter, and a preview with the symbol's
  type and pins - instead of xschem's file chooser.
- **The theme reaches every window**: xschem's own grey palette used to win over OpenLayout's, so
  its dialogs, file chooser and property forms came up light grey. Menus are padded and grouped and
  show OpenLayout's keys where they differ from xschem's; the right-click menu, tabs, toolbar
  icons, status fields and Netlist / Simulate buttons follow the theme.
- **Symbol pins stay on the wire grid**: the symbol editor's fine 2.5 snap let pins be moved off
  the 10 grid that schematic wires and instances snap to, so wires could not reach them. Moves of
  selected pins (or a pin dragged directly) now snap at 10, and saving a symbol moves any pin still
  off the grid onto it - its stub moves along and stays straight, one undo step.
- **Copy / move several objects**: with a selection of several, `c` or `m` followed by a click on
  one of the selected objects (the reference point) dropped the others - xschem's Virtuoso-style
  "click selects just this one" also ran for a command's clicks. A plain click on one of the
  selected still selects just that one (setup/patches/xschem-command-click-keeps-selection.patch;
  setup/patches/xschem-tcl-api.patch: line coordinates for scripts, and scripted moves no longer
  dropped after such a click). Rerun `setup/install.sh` to rebuild xschem.
- **Pins from the pin dialog** (`p`): a pin on the mouse also stayed drawn where it was made until
  it was put down - with a bus expanded into one pin per bit, the next bit showed up on top of the
  pin just placed, as if two pins were being placed at once. Only the pin on the mouse is drawn
  now. In the symbol editor a pin's name and stub stayed behind where it was made (only the pin
  square followed the mouse); they move with it now, and the pin lands on the 10 grid. Right after
  drawing a wire, the click meant to put a pin down started another wire instead.
- **No junctions where nobody clicked**: with orthogonal wiring a click put down only the first leg
  of the L, ending at its corner - when that corner lay on another wire, or the click was on a
  wire at the other end of the L, the wires were joined there by a solder dot, shorting two nets.
  A click now puts down the whole L up to the click, and the corner keeps off other nets (the L
  turns the other way; the rubber shows the route that will be placed). Wires that only cross stay
  apart; a wire joins another where it ends on it by a click
  (setup/patches/xschem-wire-corner-off-nets.patch; rerun `setup/install.sh`).

### Layout (KLayout)
- **Generate Layout: Instances and Pins tabs**: the form now lists the instances too, one row per
  kind with its count (*b2SRAMsbc x32*); untick a kind to leave it out, or double-click it to pick
  single instances. Left-out instances are not placed. Both tabs have *Select All* / *Deselect All*,
  so a 96-pin array no longer means unticking pins one by one.
- **The LSW is on the left**: the layer panel docks on the left side; Select and Connectivity stay on
  the right.
- **Layer grid** (*OpenLayout ▸ Show Layer Grid…*, also on the toolbar): tick layers in a window
  and their legal tracks are drawn over the layout - fins (27 nm), gates (54 nm), the M1-M3 router
  tracks, the M4-M7 DRC track grid - as light lines, one colour per layer, that follow zoom and pan
  and never become shapes; *Clear* removes them. The grids are read from the DRC deck and the ASAP7
  tech / library LEF, not typed in; M8 / M9, whose track positions no source defines, are listed
  but not drawn. See docs/KEYS.md, *Layer grid*.
- **Moving many cells stays smooth**: dragging a selection of cells - an array of SRAM bit cells,
  say - redrew each step only after the DRD spacing hints had been worked out again for every
  shape in it, up to seconds per mouse move (the 4x8 b2SRAMsbc array: 3.7 s; one bit cell inside it:
  1 s). The hints now pass over shapes farther apart than the rule, keep the shapes that stay put
  for the whole move, and merge the moved ones once; and hints that still take longer than a frame
  appear when the mouse rests instead of at every step. A moved instance also shows only its first
  100 shapes (KLayout's *edit-max-shapes-of-instances*, set by OpenLayout; KLayout's default is
  1000) instead of every shape of every cell. The array now takes 9 ms per mouse move and one cell
  6 ms. The hints themselves are unchanged.
- **Selecting what lies underneath**: click the same spot again for the next object under the
  mouse, down to the frame's GCUT, fins and rails (they could not be clicked under a transistor).
  A **Select** window sets which object types can be selected (instances, vias, shapes, pins,
  labels, boundary, the frame), and the LSW locks layers as in Virtuoso (right-click; AS / NS -
  NS leaves instances and vias out too); box selections follow both.
- **Standard-Cell Frame window**: any stack of N and P regions, each with its own width in gate
  pitches (Add row, Remove, Move up / down, All gate pitches equal), rails placed so that every
  region reaches its supply (or set per boundary), with a live preview.
- **Chaining is less eager**: a transistor chains only when dropped onto its neighbour's last
  source / drain (or overlapping it); dropped beside it - dummy gates side by side or shared - it
  stays apart.
- **More rows**: a frame stretched over more rows (e.g. an N/P/N cell) covers them; row
  transistors snap to the nearest half-row line (fins on the fin grid), a transistor dropped above
  the first row stays in that row, and transistors flipped top to bottom take part in chaining.
  Mirroring or rotating transistors refreshes their dummy gates.
- **LISD over a gate is no short**: the connectivity check joined LISD to any diffusion under it, so
  a LISD strap across a gate (as in the ASAP7 flip-flops) showed its source and drain shorted. LISD
  now reaches the diffusion only through SDT, as in LVS.
- **Place Pins…** (OpenLayout menu): the pins of whole buses in one go instead of one by one -
  the window lists the schematic's buses (BL[7:0] as one row) with how many bits the layout has
  already. Pins go on each net's own terminal (the sub-cell pin nearest the chosen side: on drawn
  metal of the net, so they connect and DRC is clean with no wiring), on the ends of the nets'
  wires, or along a side of the cell - aligned with the terminals (a bit line's pin right above
  it) or evenly spaced at a pitch, in port order. On M4 - M7 edge pins snap onto the SADP routing
  tracks. Pins already there are moved, one undo step; pins too close together, or not yet on
  drawn metal (OL.PIN), are reported. Batch: `pin_place.place_pins_file(gds, ["BL", "WL"], ...)`.

### Verification
- **PEX no longer hangs on large windows**: with its automatic two-level preconditioner (`-ap`),
  FasterCap's GMRES solve stopped converging on the large conductors of some windows (6 of the 12
  kinds in a 4 x 8 array of 2-bit SRAM cells: residual 0.3-2.7 after 1000 iterations), and its
  refinement loop then ran for 16 h without an answer. Windowed solves now use the Jacobi
  preconditioner (`-pj`) first - about 6 min there, totals within 0.9 % of a larger two-level
  preconditioner; on a window where `-ap` works, `-pj` agrees within 0.7 % - and a solve whose GMRES
  fails is stopped and run again with the other preconditioner instead of looping. Flat solves keep
  `-ap`, as calibrated.
- **Run PEX shows its progress**: OpenLayout > Run PEX runs in the background with a log window -
  each step and each window as its solve finishes, timed - with *Stop* (ends FasterCap too) and
  *Close*. KLayout no longer freezes for the whole run, and large blocks are solved up to 6 windows
  at a time.
- **Windows the size of the array's cell, not of its vias**: the window grid followed the cell placed
  most often, so an array with a via per cell (INT8_ARRAY: 64 V3 cells, 32 bit cells) was cut into
  via-sized windows - 1 564 windows of 1 560 kinds instead of 32 of 12. It now follows the cell that
  covers the most area.
- **`openlayout pex` passes `--cap`, `--window`, `--halo`, `--jobs` and `--no-cache` on**: the command
  rejected them ("unknown option"); only `python -m openlayout.pex` took them.
- **PEX of large blocks, window by window**: a single FasterCap solve takes time roughly
  proportional to the square of the net count, so arrays of more than a few cells could not be
  extracted. Above 48 nets, `openlayout pex` now solves the capacitances window by window. Each
  window is the size of the array's cell and is solved with 0.1-0.15 µm of context. Alike windows
  are solved once (`--jobs N` at a time) and cached in `~/.cache/openlayout/pex`: an array of any
  size with mirrored rows needs 12 solves. On a 10T SRAM bit cell, single-threaded, a row of 8
  takes 37 s instead of 5.4 min, and two rows 2.8 min instead of 16 min (54 s with `--jobs 6`).
  Total capacitances per signal net are within 2 % of the flat solve. A 64 × 80 array (51 200
  transistors) is extracted in about 15 min. Each window's capacitors go on the R-network nodes
  inside it, and couplings under 0.5 % of the nets' totals go to ground, so large netlists stay
  sparse. New options: `--cap auto|flat|window`, `--window`, `--halo`, `--jobs`, `--no-cache`;
  see docs/PEX.md and `tests/pex/bench/windows.py`.
- **PEX of large layouts no longer slows down quadratically**: device terminals and source /
  drain diffusions are no longer looked up across the whole layout for every device. Before the
  field solve, a 512-cell array took 4 min and now takes well under a minute.
- **LVS of mixed-case nets**: KLayout upper-cases a `.subckt`'s pins, but the ASAP7 reader passed
  the schematic's transistor nets as written, so a net such as `X_bar` or `BL_Bar` became two nets
  and `purge` dropped the pin. The reader now upper-cases the transistors' nets too.
- **Connectivity check**: row transistors' gates are probed over their channel - a gate cut at
  mid-cell no longer reports "nothing drawn at its gate".
- **LVS / PEX outside a workarea**: the schematic is netlisted with the ASAP7 libraries; a symbol
  xschem cannot find, or a schematic netlist with nothing in it, is an error with the reason (it
  used to fail inside the comparison). The hub shows why a DRC / LVS / PEX run failed.

### Simulation (OLSim)
- **Waveform viewer: arranging and zooming**
  - Drag a strip by its y axis to move the whole strip to another row (above or below the strip
    it is dropped on); dragging a curve still merges it into the strip it lands on.
  - Ctrl + left drag draws a zoom box in any mode, and a zoom box now fills the strip exactly.
  - An overview under the strips with one range for all of them: drag it to set every strip's x
    range, and it follows when any strip is zoomed or panned.
  - The legends sit in a margin right of the plots instead of over the curves; a long legend (a
    sweep overlaid) does not push the other strips out of the window.
  - A net plotted across sweep points gets one legend row (`Q ▾ 41`) whose dropdown lists the
    points, each with a tick to show or hide it; a net the same at every point (the clock) is
    plotted once.
- **Vector-file timing from design variables**: `trise`, `tfall`, `slope`, `idelay`, `odelay` and
  `tdelay` take a design variable or an expression (in seconds: `tdata = 30p`), so they can be
  swept - with a mask, one column at a time (`idelay tdata 0 1 0`: D's arrival against the clock
  for setup / hold). A value without its unit (30 s) is reported.
- **Post-layout simulation of cells with bus pins**: PEX writes a bus pin such as `A[1]` as `A_1_`
  in the extracted netlist, and the config view matched the PEX pins to the schematic's by their
  raw names - so an extracted cell with any bus pin stopped the run with "the layout has pin(s)
  A_1_ ... that its schematic does not". Pins now match the way PEX names them.

## 0.4.0-alpha.2 - 2026-10-09

Editing improvements in xschem and KLayout, found by designing a custom cell with OpenLayout,
and an LVS fix.

**Upgrading:** re-run `setup/install.sh`. It rebuilds xschem with a new OpenLayout patch that
keeps pin labels horizontal. Without the rebuild everything still works; pin labels just rotate
with their pin as before.

### Layout (KLayout)
- **Net names on shapes** (Shift+N, or the checkbox in the Connectivity panel): every net's name
  is drawn on its metal, LIG, LISD and gate shapes, scaled to the zoom and decluttered.
- **Right-click mirror / rotate:** mirror the selection over the X or Y axis, or rotate it, about
  its centre or the cell origin. Works on any selection (PCells, shapes, cells).
- **Pins and their labels move together:** selecting a pin shape selects its label, so drag,
  `m`, Move, copy, delete and mirror take it along. A label selected on its own still moves alone.
- **Fin grid:** a standalone transistor dropped into the standard-cell frame becomes a row
  transistor on the frame's fins; outside the frame, transistors snap to the gate and fin pitch.
- **Picking:** a click selects what the hover highlight shows. Over the standard-cell frame, the
  topmost non-frame shape wins.

### Schematic (xschem)
- **Bus pins:** a pin named `WL[1:0]` (`WL<1:0>` is accepted) is one bus pin; wires labelled
  `WL[1]` / `WL[0]` connect to its bits by name. *Expand buses into one pin per bit* makes
  separate pins. Generate Layout gives each bit the bus pin's direction; New Testbench gives each
  bit a vector column and an output load.
- **Pin placement:** several names (or an expanded bus) are placed one at a time, each with a
  click. No more leftover "shadow" pins; `Esc` discards the pin being placed and the rest.
  Duplicate labels get unique instance names.
- **Pin labels stay horizontal** however a pin is rotated or flipped.
- **Ctrl+S and `x` save** without a "save file?" prompt; Ctrl/Alt with the remapped letter keys
  keep xschem's meaning (Ctrl+X cuts again).

### Verification
- **LVS:** a layout with nothing connected used to compare as a match (the extracted top circuit
  was empty). It is now a mismatch with the reason.

### Known issues
- The Connectivity panel can report "nothing drawn at its gate" for row transistors whose gate is
  cut near the middle of the cell. The gate is fine; the checker probes it inside the cut. Fixed
  in the next release.

## 0.4.0-alpha.1 - 2026-10-05

The first public release of OpenLayout: an open-source custom IC design environment for the ASAP7
7 nm FinFET PDK, built on xschem, KLayout, ngspice and FasterCap. It takes a cell from schematic
through simulation, layout, DRC, LVS, parasitic extraction and post-layout simulation, without
leaving one environment.

This is an **alpha**. Expect rough edges, and expect the file formats (`.olsim`, `.config`,
`.ol.json`) to change before 1.0.

### Highlights

**One environment**
- **The hub:** a Library Manager (library, cell and view, with run status per cell) and a
  Python command line. xschem and KLayout run as one session each and open views as tabs. Menus
  in every tool jump between schematic, layout and the hub.
- **One look:** a shared dark theme, and Virtuoso-style key bindings in xschem and KLayout.
- **Workareas:** a `libs.def` defines the libraries, and a cell is a directory of views. The ASAP7
  devices and standard cells are available in every workarea.

**Schematic and layout**
- **ASAP7 devices in xschem:** nmos/pmos in four VT flavours, standard-cell symbols generated
  from the library, and symbols generated from a schematic's pins.
- **FinFET and via PCells** that follow the ASAP7 standard-cell geometry, including a
  standard-cell frame and transistor chaining (shared diffusion).
- **Schematic-driven layout:** generate a layout from its schematic, then update it in place as
  the schematic changes.
- **Connectivity panel:** open nets (thin, colour-coded flight lines), shorts (counted once, with
  what touches what and an outline of the merged metal), unlabelled pins, and missing or extra
  parts. It re-checks live as you edit.
- **Editing tools:** a path tool with alignment guides, drag-move and stretch, align, Create
  Via, a layer selection window, and design-rule-driven spacing hints while drawing.

**Verification**
- **DRC:** a KLayout deck written rule by rule from the ASAP7 DRM. Every rule has a seeded test,
  and all 7.5T RVT library cells are clean in context.
- **LVS:** FinFET extraction (fins, VT flavours, split gates) against the xschem schematic or the
  standard-cell CDL. Every 7.5T RVT library cell is checked against its CDL
  (199 of 208 match exactly; see the limitations).
- **PEX:** a 3D field solver (FasterCap) for capacitance, and resistor networks for wires,
  contacts and vias. Calibrated against the library's reference extraction: delays within about
  2 %.
- All three run from KLayout, the hub or the command line, and update the hub's checklist.

**Simulation: OLSim and the waveform viewer**
- **Tests:** design variables and sweeps, corners, and outputs with specs. Points run in
  parallel in ngspice (BSIM-CMG via OSDI), and every run is kept in a history.
- **Digital vector files (`.vec`):** PWL stimulus and checked outputs. Levels can be
  expressions of design variables (`voh 0.8*vdd`).
- **Testbenches:** New Testbench makes `tb_<cell>`, with the supply source, loads on the outputs,
  a config view and a starting vector file. Select on Schematic picks outputs by clicking in
  xschem.
- **Config views:** schematic or extracted, chosen per cell or per instance in a hierarchy
  editor. Every run logs which view each instance used, and writes it at the top of its netlist.
- **Waveform viewer:**
  - stacked strips, overlays across corners and sweeps;
  - per-signal visibility checkboxes;
  - drag a curve onto another plot to merge them; empty plots remove themselves;
  - cursors, a calculator (delay, propDelay, …), digital and bus lanes, parametric plots;
  - PNG / CSV export.

### Install

Ubuntu 24.04:

    git clone https://github.com/vhdani04/OpenLayout.git ~/openlayout/flow
    ~/openlayout/flow/setup/install.sh
    source ~/.bashrc && openlayout doctor

The installer downloads and builds the pinned tool versions (`setup/versions.env`), the ASAP7 PDK
and the BSIM-CMG model. It takes a while the first time; afterwards it is idempotent.
`openlayout doctor` runs the whole self-test.

### Known limitations

- Ubuntu 24.04 only, and ASAP7 is the only PDK for now. Support for more PDKs is coming: the
  environment is built so another PDK plugs into the same infrastructure.
- PEX is per cell. Large blocks are not extracted hierarchically yet.
- No net cross-probing between schematic and layout yet.
- No Monte Carlo: the ASAP7 models have no mismatch statistics.
- The DRC deck has not been cross-checked against an official sign-off deck.
- LVS: nine of the 208 library cells stack series transistors in a different order than their CDL. They
  are checked device by device and are fine as black boxes.

### License

GPL-3.0-or-later. The tools and the PDK keep their own licenses: see `NOTICE.md`. Virtuoso
(Cadence Design Systems) and HSPICE (Synopsys) are named only to describe key-binding and
file-format compatibility. OpenLayout is independent and not affiliated with either company.
