# Design rule check (ASAP7)

OpenLayout's DRC deck is a KLayout DRC script written rule by rule from the **ASAP7 Design Rule
Manual, PDK release 1p7** (`$ASAP7_PDK/docs/asap7_drm_201207a.pdf`; ASU, Dec. 2020 - see the
citations in the [README](../README.md#acknowledgements-and-citations)):
[`pdk/asap7/klayout/drc/asap7.drc`](../pdk/asap7/klayout/drc/asap7.drc). Every check reports under
the DRM's rule name (e.g. `M1.S.2`), with the rule's description, so a marker can be looked up in
the manual directly.

## Running it

| Where | How | Results |
|---|---|---|
| KLayout | **OpenLayout > Run DRC** | the cell being edited (saved or not), markers in the marker browser; the result also goes to the cell's DRC badge in the hub |
| Hub | select a cell, **Tools > DRC** (or the cell's context menu) | summary in the CIW, the cell's DRC badge; with violations KLayout opens the layout with the markers |
| Shell | `openlayout drc cell.gds [--cell NAME] [--report FILE]` | summary per rule; `cell.drc.lyrdb` (File > Open in KLayout's marker browser) |
| CIW | `ol.drc("lib", "cell")` | as the hub button |

The hub keeps its results in `verify/<lib>/<cell>/<cell>.drc.lyrdb` in the workarea (library
directories stay untouched; the PDK libraries are read-only).

The report lists only the rules with violations. Clicking a violation in the marker browser zooms
the layout to it and draws it bold (thick yellow outline, hatched, with a halo); a net or device
picked in the LVS netlist browser is highlighted the same way.

The layout is checked **flat**. The grid rules (fins, gates, M4-M7 routing tracks) use absolute
coordinates: cells must sit on the ASAP7 placement grid - x on the 54 nm gate pitch, rows at
multiples of 270 nm - as the standard cells and the frame do.

## Validation

`openlayout doctor` runs three tests:

- `tests/klayout/test_drc.py` - about 190 small layouts, each breaking one rule; the rule must fire
  there (and, for net-aware rules, must *not* fire for the same shapes on one net). Clean
  references must produce no marker at all: INVx1 from the library, INVx1 rebuilt from the
  standard-cell frame + transistor PCells, every via PCell (V1-V8, centred on the routing tracks;
  a lone via pad may be under the metal's minimum area until a wire is attached),
  pins on metal.
- `tests/klayout/test_drc_library.py` - every 7.5T library cell placed as in a design (between two
  INVx1, flipped copies in the rows below and above) must be clean. RVT in the doctor;
  `-rd libs=R,L,SL,SRAM` runs all four libraries (848 cells, all clean but one waiver, below).
- `tests/klayout/test_drc_gui.py` - Run DRC in KLayout, editing and re-running, the batch run and
  its results in the marker browser.

**Library waiver.** `OAI22xp33` (all VT flavours) breaks `SDT.ACTIVE.AUX.2` as the DRM states it:
its source/drain trenches are 81 nm tall over 54 nm of ACTIVE.

## Rules and how they are checked

All rules of DRM chapter 3 are implemented except the ones listed under *Not checked*. Where the
DRM text leaves room, the deck follows the figures and the library cells; those choices are listed
under *Interpretations*.

| Section | Rules |
|---|---|
| 3.1 Geometry | GEOMETRY.NONORTHOGONAL (every layer) |
| 3.2 WELL | W.1-2, S.1-2, A.1A-B, WELL.GATE.EX.1-2 |
| 3.3 FIN | W.1-2, S.1, AUX.1 |
| 3.4 GATE | W.1-2, S.1-3, AUX.1-2, GATE.ACTIVE.AUX.3, EX.1-2, S.4 |
| 3.5 ACTIVE | FIN.EX.1, W.1-3, S.1, S.2A (net-aware), S.2B, WELL.S.4/EN.1, A.1A-B, AUX.1, AUX.3, SRAM variants |
| 3.6 GCUT | W.1, ACTIVE.S.1, GATE.EX.1, GATE.S.2, S.3, AUX.1-3 |
| 3.7 implants / VT | W.1-2, ACTIVE.EN.1-4, GATE.EX.1-2 for NSELECT, PSELECT, SLVT, LVT, SRAMVT; NSELECT.PSELECT.AUX.1, VT.AUX.2 |
| 3.8 SDT | W.1-4, S.1, GATE.S.2, ACTIVE/LISD.OV.1-4, AUX.1-4 |
| 3.9 LISD | W.1, S.1-3 (by edge length), SRAM.S.4, A.1, SRAM.AUX.1 |
| 3.10 LIG | W.1, S.1-5, LISD.S.6-7 and SDT.S.8 (net-aware), GATE.S.9A/B, S.10, GCUT.S.11, A.1-4, AUX.1-2, EX.1, LISD.OV.1, SRAM.OV.2 |
| 3.11 V0 | W.1, S.1-4 (end-cap classes), M1.EN.1, LISD.EN.2-3, LIG.EN.4, LIG.A.1, AUX.1-3 |
| 3.12 M1-M3 | W.1, S.1-6, A.1 |
| 3.13 V1-V3 | W.1, S.1-4, EN.1-2 (per level), AUX.1-2 |
| 3.14/3.16 M4-M7 | W.1-5, S.1-5, AUX.1-3 (horizontal M4/M6, vertical M5/M7) |
| 3.15/3.17 V4-V7 | W.1, S.1-3, EN.1-2, AUX.1-2 |
| 3.18 M8-M9 | W.1-5, S.1-8, A.1, L.1 |
| 3.19 V8-V9 | W.1, S.1-2, EN.1-2, AUX.1 |
| OpenLayout | OL.PIN.M1-M9: a pin shape (pin purpose, datatype 251) must lie on drawn metal of its layer |

### Interpretations

- **Spacing by edge length** (LISD, LIG, M1-M3; M8-M9 S.1-S.3): the lengths of the two facing
  edges pick the rule, as in the DRM figures - long sides (> 36 nm) vs. line ends (<= 36 nm,
  split at 24 nm). Measured between facing edges (projection); corner-to-corner rules separately.
- **Corner-to-corner** rules (M1.S.6, V*.S.2-4, LIG.LISD.S.7, V4-V9 corner rules) apply to shapes
  whose facing edges do not overlap in either direction.
- **Via end-caps** (V0-V3.S.2-4): a via "with a 5 nm end-cap" has its upper metal (M1 for V0) 5 nm
  past it on both ends of one axis. The DRM's middle V*.S.1 value (27 nm for vias on parallel tracks
  that are not aligned) is covered by these corner rules.
- **V1.M1.EN.1 "5 & 2"**: M1 extends 5 nm past V1 at one end and 2 nm at the other. The LEF's VIA12
  (2 nm both ends) breaks it: OpenLayout's V1 pad has 5 nm at both ends (18 x 28 nm, exactly the
  M1 minimum area). Likewise the M4 pad over V3 is 44 nm long (M4.W.5) and the V8 pads enclose the
  cut by 20 nm (V8.M8.EN.1 / V8.M9.EN.2) - the LEF's are smaller.
- **Exact-width vias** (V0.M1.AUX.3, V*.AUX.2): both via edges across the metal coincide with the
  metal's edges. The via sits in a straight wire exactly as wide as it, its two sides flush with the
  wire's two edges. A via 1 nm off its pad, in a wider blob, or at a corner or T of the wire fails;
  make the junction next to the via, like the library cells' short stubs (NAND2xp33: each V0 at the
  end of an 18 nm M1 stub, the stubs joined by a trunk beside it). V7 has no such rule (M8 has no routing direction and is wider than V7).
- **Enclosures given as "=="** (V0.LISD.EN.2-3) are checked as minimums.
- **Grids**: FIN.S.1 - fin centrelines at 13.5 nm + k x 27 nm; GATE.S.1 - gate centrelines at
  27 nm + k x 54 nm; M4-M7.AUX.1-2 - edges on the w grid and minimum-width wires on the tracks at
  2 x w x k (offset 0, the DRM default).
- **M4-M7 widths**: W.3 / W.4 allow widths of (2N+1) x w with N even (spanning 1, 3, 5 ... tracks);
  S.3 is the line-end gap along the tracks between wires on adjacent tracks, S.4 / S.5 the parallel
  run of such wires (>= 44 nm).
- **M8-M9 S.4-S.8** use the wire width (60 / 80 / 120 / 500 / 1000 nm and wider); the length
  dependent minimum widths W.2-W.4 use the length of the wire's sides.
- **GATE.AUX.2** (no vertical discontinuity): gate line ends facing each other closer than 54 nm.
- **GATE.S.3**: a gate (not cut by GCUT) with no other gate within one pitch horizontally.
- **ACTIVE.S.2A**: only across a diffusion break (a gap between two ACTIVE polygons), horizontally
  (DRM note 2); source/drain on the same net may be 38 nm apart (S.2B).
- **ACTIVE.AUX.3**: a notch opening sideways (two horizontal edges of one polygon facing each
  other); the library's L- and U-shaped ACTIVE (steps in fin count) are allowed.
- **SDT.ACTIVE.AUX.2**: SDT's top and bottom must be at the levels of the horizontal edges of the
  ACTIVE polygon under it.
- **SRAM rules** apply to shapes interacting SRAMDRC (layer 99); the regular rules to the others.

### Not checked

- **ACTIVE.LUP.1** (latch-up: 30 um to a substrate contact): ASAP7 has no tap layer to recognise
  substrate contacts; use the library's TAPCELL in rows.
- **M4-M7.AUX.4** (outside edge of a wide wire touching a routing track edge): not decidable from
  the DRM text together with W.3 / W.4.
- The DRM marks V4-V9 and M8-M9 rules as "to be revised in the next version"; they are checked as
  written.
