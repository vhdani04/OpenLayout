# OpenLayout — Roadmap

Goal: Virtuoso-like full-custom environment on open tools (KLayout, xschem, ngspice)
for ASAP7, then a full-custom 8-bit CPU.

## Phase 0 — Foundation  [DONE]
- [x] Ubuntu 24.04 VM, SSH, shared folder (Desktop\EDA\eda-link <-> ~/share)
- [x] KLayout 0.30.12, xschem, ngspice 47 (OSDI), OpenVAF
- [x] ASAP7 PDK + 7.5T std cells; BSIM-CMG compiled; model cards converted; inverter simulates
- [x] Make shared folder permanent
- [x] Switch login session to "Ubuntu on Xorg" (window control for the hub; better VBox behavior)
- [x] Calibre deck request submitted to ASU

## Phase 1 — Unified environment ("one place")  [DONE]
- [x] Single install root + one reproducible setup script (tools pinned to versions)
- [x] `openlayout` env/launcher: sets PDK_ROOT, model paths; `openlayout xschem`, `openlayout klayout`, `openlayout sim` start tools pre-configured for ASAP7
- [x] Git repo for everything we write (PDK configs, themes, scripts, hub, decks)
- [x] Virtuoso-style project layout: workarea/ with libraries -> cells -> views
      (schematic .sch, symbol .sym, layout .gds, netlist, extracted, sim results), defined by a libs.def (like cds.lib)

## Phase 2 — PDK integration  [DONE]
- [x] KLayout tech: ASAP7 .lyt (layer map from the DRM) + .lyp (Virtuoso-like colors/stipples)
- [x] xschem ASAP7 device symbols (nmos/pmos x rvt/lvt/slvt/sram, nfin/l params), N-prefix OSDI netlisting, model+corner include
- [x] Std-cell import: auto-generate xschem symbols from CDL; GDS as KLayout reference library

## Phase 3 — Hub app v1 (CIW + Library Manager)  [PySide6]  [DONE]
- [x] Library/Cell/View browser; double-click opens view in right tool
- [x] New library/cell/view, copy/rename/delete (keeps sch/sym/layout in sync)
- [x] Console/log pane (CIW with Python `ol` API); Netlist + Simulate; per-cell status badges
- [x] DRC button (Phase 5), LVS and PEX buttons (Phase 6)
- [x] App-menu entry; tools run as single sessions driven over localhost

## Phase 4 — Look & feel (one consistent environment)  [DONE]
- [x] Shared design language: palette, fonts, icons across hub / KLayout / xschem (share/theme/openlayout.json)
- [x] xschem: colorscheme, fonts, Tk widget styling, Cadence-compat mode, Virtuoso bindkeys, OpenLayout menu (overlay via xschemrc + Tcl, no fork)
- [x] KLayout: Virtuoso bindkeys, LSW dock, dark scheme, OpenLayout menu (device PCells moved to Phase 7)
- [x] Cross-tool navigation schematic <-> layout <-> Library Manager via the hub
- [ ] Net-level cross-probing (select a net in one tool, highlight in the other) — needs LVS, Phase 6

## Phase 4b — Layout XL features (from first review)
- [x] Display classes: cut/marker layers dashed outlines, implants outlines, vias solid, pins = drawing color + X
- [x] Single LSW (right) with All / Used tabs; NV keeps the current layer; dotted grid
- [x] Path tool: width from the clicked edge, Manhattan only; rulers/move/stretch on the axes
- [x] FinFET (nmos/pmos) and via PCells (OpenLayout_ASAP7)
- [x] Generate / Update Layout from Schematic with a persistent schematic link
- [x] Connectivity panel: open nets with flight lines, shorts, missing/extra parts (live re-check)

## Phase 5 — DRC  [DONE]
- [x] KLayout DRC deck written from the ASAP7 DRM, rule by rule, with pass/fail test layouts (docs/DRC.md)
- [x] Regression: all std-cell GDS DRC-clean in context (848 cells; one documented library waiver)
- [x] Results in KLayout's marker browser: OpenLayout > Run DRC, hub DRC button, `openlayout drc`
- [x] Generators DRC-clean: frame + transistor PCells, via PCells (pads enlarged to the DRM where the LEF's are smaller)
- [ ] Cross-check against the Calibre deck if it arrives

## Phase 6 — LVS + extraction
- [x] FinFET device extractor (ACTIVE height -> W = 27 nm per fin), VT flavour recognition, split gates (docs/LVS.md)
- [x] Regression: every std cell against its CDL (199 / 208 exact; 9 with reordered series stacks checked device by device)
- [x] LVS from KLayout (netlist browser), the hub (LVS button) and `openlayout lvs`; net names and bulk ties checked
- [ ] Net-level cross-probing schematic <-> layout from the LVS cross-reference
- [x] Parasitic extraction -> post-layout ngspice simulation: FasterCap 3D capacitances, R networks (docs/PEX.md)
- [x] PEX calibrated against the library's Calibre xACT 3D netlists (54 cells, delays within ~2 %)
- [ ] PEX of large blocks (hierarchical: cells, then routing)

## Phase 6b — Simulation environment
- [x] Maestro: tests, design variables / sweeps, corners, outputs + specs, parallel ngspice runs, histories (docs/MAESTRO.md)
- [x] Digital vector files (.vec): PWL stimulus, output checking, vector-check plots
- [x] Waveform viewer (pyqtgraph): strips, overlays, cursors, calculator, digital / bus lanes, parametric plots, export
- [x] Post-layout tests: cells simulated with their PEX netlist
- [ ] Monte Carlo (needs mismatch statistics the ASAP7 models do not have), optimization

## Phase 7 — Custom cell library
- [x] Device PCells (nfin, fingers, contacts) — done in Phase 4b; DRC-verify in Phase 5
- [ ] INV, NAND2, NOR2, XOR, MUX2, latch, DFF — each: sch -> sim -> layout -> DRC -> LVS -> PEX sim
- [ ] Characterize (delay/power) with ngspice

## Phase 8 — 8-bit CPU
- [ ] Architecture + ISA spec; Verilog reference model + testbench (iverilog/verilator)
- [ ] Datapath: ALU bit-slice -> 8-bit ALU, register file, PC, shifter
- [ ] Control + decode; clocking
- [ ] Hierarchical assembly, full-chip DRC/LVS, post-layout simulation of programs

## Phase 9 — Extensions (optional)
- [ ] FreePDK3 (GAA) as a second PDK on the same infrastructure
- [ ] Docs / portfolio write-up
