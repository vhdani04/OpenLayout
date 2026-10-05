# Notices

## OpenLayout

Copyright (C) 2026 vhdani04 and the OpenLayout contributors.

OpenLayout is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version. It is distributed in the hope that it will be
useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See [LICENSE](LICENSE) for the full text.

The patches in `setup/patches/` modify KLayout and xschem. They are distributed under those
projects' licenses (KLayout: GPL-3.0-or-later; xschem: GPL-2.0-or-later, used here under
GPL-3.0-or-later).

## Third-party software and data

OpenLayout does not include the following software or data. `setup/install.sh` downloads each one
from its upstream project, under that project's own license:

| Component | Used for | License |
|---|---|---|
| [KLayout](https://www.klayout.de) | layout editor, DRC, LVS; OpenLayout's KLayout macros run inside it | GPL-3.0-or-later |
| [xschem](https://github.com/StefanSchippers/xschem) | schematic editor; OpenLayout's Tcl scripts run inside it | GPL-2.0-or-later |
| [ngspice](https://ngspice.sourceforge.io) | circuit simulator | Modified BSD (some files under other free licenses) |
| [OpenVAF-reloaded](https://github.com/arpadbuermen/OpenVAF) | compiles the BSIM-CMG Verilog-A model to OSDI | GPL-3.0 |
| [BSIM-CMG](https://www.bsim.berkeley.edu) Verilog-A model | FinFET compact model | ECL-2.0, Copyright The Regents of the University of California |
| [FasterCap](https://github.com/iic-jku/FasterCap), [LinAlgebra](https://github.com/ediloren/LinAlgebra), [Geometry](https://github.com/iic-jku/Geometry) | 3D capacitance field solver (parasitic extraction) | LGPL-2.1 |
| [ASAP7 PDK and standard cells](https://github.com/The-OpenROAD-Project/asap7) | process design kit, models, standard-cell libraries | BSD-3-Clause, Copyright Lawrence T. Clark, Vinay Vashishtha, Arizona State University |
| [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python) | the hub, OLSim and the waveform viewer | LGPL-3.0 (or GPL-2.0 / GPL-3.0) |
| [pyqtgraph](https://www.pyqtgraph.org) | waveform plotting | MIT |
| [NumPy](https://numpy.org) | numerics | BSD-3-Clause |

### Data derived from ASAP7

These files are derived from the ASAP7 PDK (BSD-3-Clause; copyright Lawrence T. Clark, Vinay
Vashishtha, Arizona State University):

- the DRC and LVS decks in `pdk/asap7/klayout/`, written from the ASAP7 design rule manual
  (DRM r1p7);
- the KLayout technology (`asap7.lyt`) and layer properties (`asap7.lyp`), generated from the
  PDK's layer map and display resources;
- the parasitic-extraction technology (`asap7_pex.json`), calibrated against the PDK's
  technology files and the standard-cell library's reference extraction netlists.

The ASAP7 license:

```
BSD 3-Clause License

Copyright 2020 Lawrence T. Clark, Vinay Vashishtha, or Arizona State
University

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
contributors may be used to endorse or promote products derived from this
software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
```

## Trademarks

Virtuoso is a trademark of Cadence Design Systems, Inc. HSPICE is a trademark of Synopsys, Inc. All
other product names are trademarks of their respective owners. They are mentioned only to describe
key-binding and file-format compatibility. OpenLayout is an independent project, not affiliated
with, sponsored by or endorsed by any of these companies, and contains none of their software,
documentation or data.
