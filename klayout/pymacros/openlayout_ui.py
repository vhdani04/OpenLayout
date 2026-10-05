# $description: OpenLayout look and feel
# $autorun
# $show-in-menu: false
#
# Loads OpenLayout into KLayout (see klayout/python/openlayout_kl/gui.py): dark theme, Virtuoso-style keys,
# path tool, ASAP7 PCells, LSW and Connectivity panels, OpenLayout menu.
# OPENLAYOUT_UI=0 disables it; OPENLAYOUT_KEYS=klayout keeps KLayout's key bindings.
import os
import sys

import pya

_flow = os.environ.get("OPENLAYOUT_HOME", os.path.expanduser("~/openlayout/flow"))
for _p in (os.path.join(_flow, "klayout", "python"), os.path.join(_flow, "python")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if os.environ.get("OPENLAYOUT_UI", "1") != "0":
    from openlayout_kl import gui, pcells

    pcells.register_library()
    gui.start(pya.Application.instance().main_window())
