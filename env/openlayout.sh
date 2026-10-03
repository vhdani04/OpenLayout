# Environment for the OpenLayout. Sourced from ~/.bashrc by setup/install.sh.
export OPENLAYOUT_ROOT="${OPENLAYOUT_ROOT:-$HOME/openlayout}"
export OPENLAYOUT_HOME="$OPENLAYOUT_ROOT/flow"
export PDK_ROOT="$OPENLAYOUT_ROOT/pdk"
export PDK=asap7
export ASAP7_PDK="$PDK_ROOT/asap7/asap7_pdk_r1p7"
export ASAP7_STDCELLS="$PDK_ROOT/asap7/asap7sc7p5t_28"
export OPENLAYOUT_MODELS="$OPENLAYOUT_ROOT/models"
export BSIMCMG_OSDI="$OPENLAYOUT_MODELS/bsimcmg/bsimcmg.osdi"
export ASAP7_SPICE_DIR="$OPENLAYOUT_MODELS/asap7_ngspice"
case ":$PATH:" in *":$OPENLAYOUT_HOME/bin:"*) ;; *) export PATH="$OPENLAYOUT_HOME/bin:$PATH" ;; esac
export KLAYOUT_PATH="$HOME/.klayout:$OPENLAYOUT_HOME/pdk/asap7/klayout"
