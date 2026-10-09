# Library plumbing for xschem: reads a workarea's libs.def  and puts each
# library's parent directory on XSCHEM_LIBRARY_PATH, so cells are referenced as lib/cell/cell.sym.

proc ol_expand {s} {
  while {[regexp {\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?} $s m var]} {
    set val [expr {[info exists ::env($var)] ? $::env($var) : ""}]
    set s [string map [list $m $val] $s]
  }
  return $s
}

# Returns a list of {name path} pairs, following INCLUDE lines.
proc ol_read_libs_def {file} {
  set libs {}
  set dir [file dirname [file normalize $file]]
  set fd [open $file]
  foreach line [split [read $fd] \n] {
    set line [string trim [lindex [split $line #] 0]]
    if {$line eq ""} continue
    lassign $line kw a b
    switch -- $kw {
      DEFINE {
        set path [file normalize [file join $dir [ol_expand $b]]]
        lappend libs [list $a $path]
      }
      INCLUDE {
        set inc [file normalize [file join $dir [ol_expand $a]]]
        if {[file exists $inc]} { set libs [concat $libs [ol_read_libs_def $inc]] }
      }
    }
  }
  close $fd
  return $libs
}

proc ol_setup_workarea {root} {
  global XSCHEM_LIBRARY_PATH netlist_dir ol_workarea_root
  set ol_workarea_root [file normalize $root]   ;# the Add Instance browser lists its libraries
  set parents {}
  foreach lib [ol_read_libs_def $root/libs.def] {
    lassign $lib name path
    if {[file tail $path] ne $name} {
      puts stderr "openlayout: library '$name' directory must be named '$name' (got $path)"
    }
    set parent [file dirname $path]
    if {$parent ni $parents} { lappend parents $parent }
  }
  foreach p $parents { append XSCHEM_LIBRARY_PATH :$p }
  set netlist_dir $root/sim/netlist
  file mkdir $netlist_dir
}
