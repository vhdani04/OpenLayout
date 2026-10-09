# Base xschem configuration for OpenLayout. Sourced by every workarea's xschemrc.
set ol_xschem_dir [file dirname [file normalize [info script]]]
# OpenLayout symbols first: they shadow xschem devices of the same name (gnd.sym = VSS)
set XSCHEM_LIBRARY_PATH $ol_xschem_dir/symbols:${XSCHEM_SHAREDIR}/xschem_library/devices
source $ol_xschem_dir/openlayout_libs.tcl
source $ol_xschem_dir/openlayout_theme.tcl
source $ol_xschem_dir/openlayout_keys.tcl
# GUI additions run after xschem has built its main window.
lappend tcl_files $ol_xschem_dir/openlayout_ui.tcl $ol_xschem_dir/openlayout_edit.tcl \
  $ol_xschem_dir/openlayout_browser.tcl
# Netlisting (GUI and batch): VSS tied to SPICE ground.
lappend tcl_files $ol_xschem_dir/openlayout_netlist.tcl
