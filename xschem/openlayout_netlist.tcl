# OpenLayout netlisting (GUI and batch): the ground net is VSS (ASAP7 convention, see
# symbols/gnd.sym); for simulation, SPICE netlists that use the global VSS get one 0 V source tying
# it to node 0. Wraps xschem's netlist proc, which writes every netlist.

proc ol_tie_vss {file} {
  if {![file exists $file]} { return 0 }
  set f [open $file r]
  set text [read $f]
  close $f
  if {![regexp -nocase -line {^\.global\s.*\mVSS\M} $text]} { return 0 }
  if {[regexp -nocase -line {^V_OL_VSS\s} $text]} { return 0 }
  set tie "* OpenLayout: the ground net VSS is SPICE node 0\nV_OL_VSS VSS 0 0\n"
  set ends [regexp -all -inline -nocase -line -indices {^\.end\s*$} $text]
  if {[llength $ends]} {
    set at [lindex [lindex $ends end] 0]
    set text [string range $text 0 [expr {$at - 1}]]$tie[string range $text $at end]
  } else {
    append text $tie
  }
  set f [open $file w]
  puts -nonewline $f $text
  close $f
  return 1
}

if {[info procs netlist] ne {} && [info procs ol_netlist_xschem] eq {}} {
  rename netlist ol_netlist_xschem
  proc netlist {source_file show netlist_file} {
    global netlist_dir
    set result [ol_netlist_xschem $source_file $show $netlist_file]
    if {[xschem get netlist_type] eq {spice}} {
      catch {ol_tie_vss [file join [regsub {/$} $netlist_dir {}] $netlist_file]}
    }
    return $result
  }
}
