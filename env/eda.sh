# Environment for the ASAP7 open flow. Sourced from ~/.bashrc by setup/install.sh.
export EDA_ROOT="${EDA_ROOT:-$HOME/eda}"
export EDA_FLOW="$EDA_ROOT/flow"
export PDK_ROOT="$EDA_ROOT/pdk"
export PDK=asap7
export ASAP7_PDK="$PDK_ROOT/asap7/asap7_pdk_r1p7"
export ASAP7_STDCELLS="$PDK_ROOT/asap7/asap7sc7p5t_28"
export EDA_MODELS="$EDA_ROOT/models"
export BSIMCMG_OSDI="$EDA_MODELS/bsimcmg/bsimcmg.osdi"
export ASAP7_SPICE_DIR="$EDA_MODELS/asap7_ngspice"
case ":$PATH:" in *":$EDA_FLOW/bin:"*) ;; *) export PATH="$EDA_FLOW/bin:$PATH" ;; esac
