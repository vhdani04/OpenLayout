# Changelog

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

- Ubuntu 24.04 only, and ASAP7 is the only PDK.
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
