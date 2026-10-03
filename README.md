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

    .lib asap7.lib tt                          * tt | ff | ss
    N1 d g s b nmos_rvt l=21n nfin=3           * OSDI instances start with N, not M

`~/.spiceinit` (written by `install.sh shell`) loads BSIM-CMG and puts the cards on ngspice's
`sourcepath`, so netlists need no absolute paths. Device flavors: `{n,p}mos_{lvt,rvt,slvt,sram}`.

See [ROADMAP.md](ROADMAP.md) for the plan.
