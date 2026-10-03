"""Test session setup: run tools with a throwaway HOME so tests never touch the user's ~/.xschem,
~/.klayout or hub settings. ~/.spiceinit is copied: ngspice needs it to load the BSIM-CMG model."""
import os
import shutil
import tempfile

_real_home = os.path.expanduser("~")
os.environ["HOME"] = tempfile.mkdtemp(prefix="openlayout-test-home-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(os.environ["HOME"], ".config")
_spiceinit = os.path.join(_real_home, ".spiceinit")
if os.path.isfile(_spiceinit):
    shutil.copy(_spiceinit, os.environ["HOME"])
