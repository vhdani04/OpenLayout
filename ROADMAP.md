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
- [ ] DRC / LVS / PEX buttons are placeholders until Phases 5–6
- [x] App-menu entry; tools run as single sessions driven over localhost

## Phase 4 — Look & feel (one consistent environment)   <- NEXT
- [ ] Shared design language: palette, fonts, icons across hub / KLayout / xschem
- [ ] xschem: colorscheme, fonts, Tk widget styling, Cadence-compat mode, Virtuoso bindkeys, custom menus/toolbar (overlay via xschemrc + Tcl, no fork)
- [ ] KLayout: Virtuoso bindkeys, LSW dock, dark scheme, menus, toolbar, PCells
- [ ] Cross-probing schematic <-> layout (stretch goal)

## Phase 5 — DRC
- [ ] KLayout DRC deck written from the ASAP7 DRM, rule by rule, with pass/fail test layouts
- [ ] Regression: all std-cell GDS must be DRC-clean
- [ ] Cross-check against Calibre deck when it arrives; results browser in KLayout

## Phase 6 — LVS + extraction
- [ ] FinFET device extractor (fin counting -> nfin), VT flavor recognition
- [ ] Regression: every std cell passes LVS vs its CDL
- [ ] Parasitic extraction -> post-layout ngspice simulation

## Phase 7 — Custom cell library
- [ ] Device PCells (nfin, fingers, contacts)
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
