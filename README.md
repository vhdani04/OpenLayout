# OpenLayout

A Virtuoso-style, open-source custom IC design environment for the ASAP7 7nm FinFET PDK:
xschem (schematics) + ngspice (simulation, BSIM-CMG via OSDI) + KLayout (layout, DRC, LVS).

## Install (Ubuntu 24.04)

    git clone git@github.com:vhdani04/OpenLayout.git ~/openlayout/flow
    ~/openlayout/flow/setup/install.sh        # tools, PDK, models, shell setup — idempotent
    source ~/.bashrc && openlayout doctor

Pinned versions live in `setup/versions.env`.

## Layout on disk

    ~/openlayout/flow      this repo
    ~/openlayout/src       downloaded tool sources (not versioned)
    ~/openlayout/pdk       ASAP7 PDK + 7.5T standard cells (not versioned)
    ~/openlayout/models    generated: bsimcmg.osdi, ngspice ASAP7 cards + asap7.lib
    ~/designs/<x>   design workareas

## Using it

    openlayout new-workarea ~/designs/cpu8      # libs.def, xschemrc, sim/, libraries/cpu8
    cd ~/designs/cpu8
    openlayout new-lib alu                      # add a design library
    openlayout libs                             # libraries visible here (incl. PDK libraries)
    openlayout xschem                           # schematic editor with workarea libraries
    openlayout klayout                          # layout editor
    openlayout sim tb.sp                        # ngspice batch run

Workareas mirror Virtuoso: `libs.def` (like `cds.lib`) defines libraries; a library holds
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
and stipples converted from the PDK's Virtuoso `display.drf`, net-tracer connectivity
(gate/SD -> LIG/LISD -> V0 -> M1 ... M9), and the four std-cell GDS libraries available for
placement. Regenerate with `pdk/asap7/klayout/gen_asap7_{lyp,lyt}.py`.

See [ROADMAP.md](ROADMAP.md) for the plan.
