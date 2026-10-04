# Layout versus schematic (ASAP7)

OpenLayout's LVS is a KLayout LVS script,
[`pdk/asap7/klayout/lvs/asap7.lvs`](../pdk/asap7/klayout/lvs/asap7.lvs). It extracts the FinFETs
and their connections from the layout and compares them with the cell's xschem schematic (plus the
standard-cell CDL for placed library cells).

## Running it

| Where | How | Results |
|---|---|---|
| KLayout | **OpenLayout > Run LVS** | the cell being edited (saved or not) against `<cell>.sch` next to its layout; the cross-reference in the netlist browser |
| Hub | select a cell, **Tools > LVS** (or the cell's context menu) | summary in the CIW, the cell's LVS badge; on a mismatch KLayout opens the layout with the netlist browser |
| Shell | `openlayout lvs cell.gds [--cell NAME] [--schematic cell.sch\|cell.spice] [--stdcells check]` | summary (mismatching circuits, nets, devices); `cell.lvsdb` |
| CIW | `ol.lvs("lib", "cell")` | as the hub button |

The schematic is netlisted by xschem as a subcircuit (as Generate Layout does). A cell without a
schematic - a library standard cell - is compared with its CDL. The hub keeps results in
`verify/<lib>/<cell>/<cell>.lvsdb`.

## What is compared

- **Devices**: `nmos_*` / `pmos_*` in four flavours - rvt (no VT layer), lvt (LVT), slvt (SLVT),
  sram (SRAMVT): the ASAP7 model names the xschem symbols and the CDL use. A transistor is GATE
  (not cut by GCUT) over ACTIVE, typed by NSELECT / PSELECT.
- **Size**: W is the ACTIVE height under the gate - 27 nm per fin - and is compared with the
  schematic's `nfin x nf x m x 27 nm` (the CDL's `w`); the summary reports it in fins. L is 20 nm.
  Parallel fingers are combined first, so `nfin=3 nf=2` matches two 3-fin fingers on the same
  nets, and wide stacks drawn as several parallel stacks ("split gates", as the library's x4 / x6
  cells do) are joined on both sides.
- **Connectivity**: source/drain - SDT - LISD; gate - LIG; LIG - LISD where they overlap; LISD /
  LIG - V0 - M1 - V1 ... M9. Pin shapes (pin purpose 251) conduct like the metal; labels on the pin
  (251) or label (2) purpose name nets.
- **Net names**: the comparison pairs nets by topology, then every labelled layout net must carry
  the schematic net's name. A swapped pair of labels, or a placed cell wired to the wrong pins,
  is a mismatch even though the topology matches.
- **Ground**: xschem's ground (`0`, `GND`) is VSS, the ASAP7 ground net.
- **Bulk**: ASAP7 has no drawn bulk connection (taps are cells), so transistors are compared with
  three terminals. The schematic's bulk must be VSS (nMOS) or VDD (pMOS); anything else is reported
  as a mismatch ("bulk on ...").

### Placed standard cells

Library cells placed in a design are compared as **black boxes**: their pins, by name, against the
CDL's pin list - like Calibre's `LVS BOX` for a verified library. Wire the rails up: label VDD /
VSS at the top level (on the cells' rails) so the cells' supply pins connect. `--stdcells check`
compares their transistors too.

## Validation

`openlayout doctor` runs:

- `tests/klayout/test_lvs.py` - an inverter layout against xschem-style netlists: a match, then a
  different fin count, VT flavour and bulk, an open (a V0 removed), a short (an M1 bar), two fingers
  against INVx2, a placed INVx1 (black box) with correct and swapped pins, and a transistor PCell.
- `tests/klayout/test_lvs_library.py` - every library cell against its CDL, transistor by
  transistor (RVT in the doctor; `-rd libs=R,L,SL,SRAM` runs all four libraries: 208 cells each).
  199 match exactly. In nine cells (A2O1A1O1Ixp25, AOI211xp5, NAND3x2, NOR3x2, OAI21x1,
  OAI221xp5, SDFLx1/x2/x3) the layout stacks series transistors in a different order than the
  CDL, which a strict topological comparison reports (Calibre accepts it through logic-gate
  recognition). For these, the test checks that layout and CDL have the same transistors: per type
  and gate pin, the same total width. They are fine as black boxes in designs.
- `tests/klayout/test_lvs_gui.py` - Run LVS in KLayout on a workarea cell with an xschem schematic,
  an edit that breaks it, the batch run and its results in the netlist browser, a library cell
  against the CDL.

## Not compared

- Series-transistor order within a stack is compared strictly (see above).
- Bulk / well connectivity (no taps in the cells - see *Bulk*).
- Parasitics: extraction for post-layout simulation is the next step (Phase 6, PEX).
