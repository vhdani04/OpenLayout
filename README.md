# OpenLayout

An open-source custom IC design environment for the ASAP7 7nm FinFET PDK:
xschem (schematics) + ngspice (simulation, BSIM-CMG via OSDI) + KLayout (layout, DRC, LVS) +
FasterCap (parasitic extraction). ASAP7 is the first PDK; support for more PDKs is coming.

## Install (Ubuntu 24.04)

    git clone https://github.com/vhdani04/OpenLayout.git ~/openlayout/flow
    ~/openlayout/flow/setup/install.sh        # tools, PDK, models, shell setup — idempotent
    source ~/.bashrc && openlayout doctor

Pinned versions live in `setup/versions.env`.

## Layout on disk

    ~/openlayout/flow      this repo
    ~/openlayout/src       downloaded tool sources (not versioned)
    ~/openlayout/pdk       ASAP7 PDK + 7.5T standard cells (not versioned)
    ~/openlayout/models    generated: bsimcmg.osdi, ngspice ASAP7 cards + asap7.lib
    ~/designs/<x>   design workareas

## The hub

    openlayout hub            # or "OpenLayout" in the app menu

The hub is OpenLayout's home: a **Library Manager** (Library | Cell | View, with filters;
view chips S/Y/L and a pass/fail dot per cell) above a **CIW** (log + Python command line).

- Double-click a cell or view to open it. xschem and KLayout run as one session each per
  workarea and the hub drives them over localhost (xschem's Tcl server, KLayout's
  `klayout/pymacros/openlayout_bridge.py`), so views open as tabs in the running tool.
- File: new/open workarea, new library, new cell view (schematic, symbol, layout).
- Edit: copy (also from PDK cells, e.g. a std cell into your library), rename, delete
  (moves to `<workarea>/.trash/`).
- Tools: Netlist (F7) and Simulate (F8) run xschem + ngspice batch; results land in
  `sim/<lib>/<cell>/` and the cell's checks in `.openlayout/state.json`.
- CIW: Python with an `ol` object — `help(ol)`, e.g. `ol.sim('mychip', 'tb_inv')`.

## Look & feel

One theme (`share/theme/openlayout.json`) drives the hub, xschem and KLayout: dark UI, near-black
canvases, shared accent colors. Both tools use **Virtuoso-style key bindings** (see [docs/KEYS.md](docs/KEYS.md),
or F1 in the hub) and get an **OpenLayout** menu:

- xschem: Open Layout in KLayout, Open Symbol/Schematic, Show in Library Manager, Netlist, Simulate
- KLayout: Open Schematic/Symbol, Show in Library Manager, LSW (layer palette),
  Run DRC, Run LVS, Run PEX

**DRC**: a KLayout deck written rule by rule from the ASAP7 DRM, run from KLayout, the hub or
`openlayout drc` - see [docs/DRC.md](docs/DRC.md).
**LVS**: FinFET extraction (fins, VT flavours) against the xschem schematic and the standard-cell
CDL, run from KLayout, the hub or `openlayout lvs` - see [docs/LVS.md](docs/LVS.md).
**PEX**: capacitances from the FasterCap 3D field solver, resistor networks for wires and vias, a
post-layout SPICE netlist; from KLayout, the hub or `openlayout pex` - see [docs/PEX.md](docs/PEX.md).
**OLSim**: the simulation environment (tests, variables and sweeps, corners, vector files, outputs with
specs, post-layout through config views - schematic or extracted per cell / instance) and a waveform
viewer (pyqtgraph); from the hub (Tools > OLSim, F9) or
`openlayout olsim` / `openlayout waves` - see [docs/OLSIM.md](docs/OLSIM.md).

Cross-tool menus call `openlayout hubcmd`, which talks to the hub over localhost
(`<workarea>/.openlayout/session.json` holds its port); the hub starts the other tool if needed.
`OPENLAYOUT_KEYS=xschem|klayout` keeps a tool's own bindings; `OPENLAYOUT_UI=0` disables the
KLayout additions.

## Schematic-driven layout

**Generate Layout** (hub F9, xschem or KLayout *OpenLayout* menu) netlists a cell's schematic and
creates or updates `<cell>.gds`:

- FinFETs become **OpenLayout_ASAP7** `nmos`/`pmos` PCells (vt, nfin, nf from the schematic; `m`
  copies). The PCells follow the ASAP7 std-cell geometry: 54 nm gate pitch with dummy gates, fins
  on the 27 nm grid, SDT/LISD source/drain contacts, implant and VT layers (no gate contact: it
  goes wherever the routing wants it). A `via` PCell covers LISD/LIG-M1 and M1-M9 stacks.
- Standard cells become instances of the ASAP7 std-cell libraries; other subcircuits are copied from
  their own layout view.
- Schematic ports become M1 pins.
- The link to the schematic is stored in `<cell>.ol.json`; every instance carries its schematic name
  (GDS property), so placement and routing survive **Update from Schematic** (parameter changes are
  applied in place, new parts land in a staging row, removed parts are reported, never deleted).

The **Connectivity** panel then shows which nets are open (flight lines), shorted or complete, and
re-checks as you edit.

## Using it

    openlayout new-workarea ~/designs/mychip      # libs.def, xschemrc, sim/, libraries/mychip
    cd ~/designs/mychip
    openlayout new-lib alu                      # add a design library
    openlayout libs                             # libraries visible here (incl. PDK libraries)
    openlayout xschem                           # schematic editor with workarea libraries
    openlayout klayout                          # layout editor
    openlayout sim tb.sp                        # ngspice batch run
    openlayout test                             # Python unit tests

Workareas: `libs.def` defines libraries; a library holds
cells; a cell is a directory `<lib>/<cell>/` holding its views (`<cell>.sch`, `<cell>.sym`,
`<cell>.gds`, ...). xschem references cells as `<lib>/<cell>/<cell>.sym`.

## Simulating ASAP7 devices

    .lib asap7.lib tt                          * tt | ff | ss  (models + all std cells)
    N1 d g s b nmos_rvt l=20n nfin=3           * OSDI instances start with N, not M
    X1 a vdd vss y INVx1_ASAP7_75t_R           * std cells are ordinary subcircuits

`~/.spiceinit` (written by `install.sh shell`) loads BSIM-CMG and puts the cards on ngspice's
`sourcepath`, so netlists need no absolute paths. Device flavors: `{n,p}mos_{lvt,rvt,slvt,sram}`.

`l=20n` is the drawn gate length (the model adds `xl=1n`); the std-cell netlists use it too.

## PDK libraries

Every workarea includes `pdk/asap7/libs.def`:

| Library | Contents |
|---|---|
| `asap7_devices` | `{n,p}mos_{rvt,lvt,slvt,sram}` (params `l nfin nf m`) and `asap7_corner` (emits `.lib asap7.lib <corner>`) |
| `asap7sc7p5t_28_{R,L,SL,SRAM}` | 7.5T standard-cell symbols, generated from the PDK CDL + Verilog |

In xschem, a schematic transistor named `M1` netlists as `NM1`. Place one `asap7_corner`
per testbench to load models.

KLayout (`openlayout klayout`) opens in editor mode with the `asap7` technology: layer colors
and stipples converted from the PDK's display resource file (`display.drf`), net-tracer connectivity
(gate/SD -> LIG/LISD -> V0 -> M1 ... M9), and the four std-cell GDS libraries available for
placement. Regenerate with `pdk/asap7/klayout/gen_asap7_{lyp,lyt}.py`.

See [ROADMAP.md](ROADMAP.md) for the plan.

## Acknowledgements and citations

OpenLayout is built around the ASAP7 predictive PDK and its 7.5-track standard-cell library,
developed at Arizona State University with ARM. The DRC deck is written from the ASAP7 design rule
manual; the LVS and PEX regressions and the PCell geometry follow the standard-cell library. If you
publish work done with OpenLayout, please cite the ASAP7 papers, as their authors ask:

1. L. T. Clark, V. Vashishtha, L. Shifren, A. Gujja, S. Sinha, B. Cline, C. Ramamurthy and G. Yeric,
   "ASAP7: A 7-nm finFET predictive process design kit," *Microelectronics Journal*, vol. 53,
   pp. 105-115, Jul. 2016. [doi:10.1016/j.mejo.2016.04.006](https://doi.org/10.1016/j.mejo.2016.04.006)
2. V. Vashishtha, M. Vangala and L. T. Clark, "ASAP7 predictive design kit development and cell
   design technology co-optimization: Invited paper," *Proc. IEEE/ACM International Conference on
   Computer-Aided Design (ICCAD)*, pp. 992-998, Nov. 2017.
   [doi:10.1109/ICCAD.2017.8203889](https://doi.org/10.1109/ICCAD.2017.8203889)
3. *ASAP7 PDK Design Rule Manual*, PDK release 1p7 (`asap7_drm_201207a.pdf`), Arizona State
   University, Dec. 2020. [github.com/The-OpenROAD-Project/asap7_pdk_r1p7](https://github.com/The-OpenROAD-Project/asap7_pdk_r1p7)

## License

OpenLayout is free software, released under the GNU General Public License v3.0 or later - see
[LICENSE](LICENSE). The tools and PDK it installs keep their own licenses; [NOTICE.md](NOTICE.md)
lists them, with the ASAP7 attribution.

Virtuoso is a trademark of Cadence Design Systems, Inc., and HSPICE of Synopsys, Inc. They are
named only to describe key-binding and file-format compatibility. OpenLayout is an independent
project, not affiliated with or endorsed by either company.
