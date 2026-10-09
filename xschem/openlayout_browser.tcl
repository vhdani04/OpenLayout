# Add Instance: OpenLayout's symbol browser for xschem (i, Insert, Tools > Insert symbol, the
# toolbar's symbol button). Laid out like the hub's Library Manager: the workarea's libraries (design
# libraries first, the PDK's dimmed) and a Basic library of xschem's own devices (pins, labels,
# supplies, sources); a library's cells with a symbol, with a filter; and a preview of the symbol
# with its pins. Double-click, Enter or Place puts the symbol on the mouse; Esc closes.

# Nothing to do without a GUI (xschem -x batch netlisting).
if {[info commands winfo] eq ""} { return }

# {name dir kind}: kind design | pdk | basic
proc ol_inst_libraries {} {
  global ol_workarea_root ol_xschem_dir XSCHEM_SHAREDIR env
  set design {}
  set pdk {}
  if {[info exists ol_workarea_root] && [file exists $ol_workarea_root/libs.def]} {
    set roots {}
    foreach v {OPENLAYOUT_HOME OPENLAYOUT_ROOT} {
      if {[info exists env($v)]} { lappend roots [file normalize $env($v)] }
    }
    foreach lib [ol_read_libs_def $ol_workarea_root/libs.def] {
      lassign $lib name dir
      if {![file isdirectory $dir]} continue
      set kind design
      foreach r $roots { if {[string first $r/ $dir/] == 0} { set kind pdk } }
      if {$kind eq "pdk"} { lappend pdk [list $name $dir pdk] } else { lappend design [list $name $dir design] }
    }
  }
  return [concat $design $pdk [list [list Basic {} basic]]]
}

# {cell symbol-reference symbol-file} of a library's cells that have a symbol
proc ol_inst_cells {lib} {
  global ol_xschem_dir XSCHEM_SHAREDIR
  lassign $lib name dir kind
  set out {}
  if {$kind eq "basic"} {
    # OpenLayout's symbols shadow xschem's devices of the same name (see xschemrc_base.tcl)
    set seen {}
    foreach d [list $ol_xschem_dir/symbols $XSCHEM_SHAREDIR/xschem_library/devices] {
      foreach f [lsort [glob -nocomplain -directory $d *.sym]] {
        set cell [file rootname [file tail $f]]
        if {$cell in $seen} continue
        lappend seen $cell
        lappend out [list $cell [file tail $f] $f]
      }
    }
    return [lsort -dictionary -index 0 $out]
  }
  foreach c [lsort -dictionary [glob -nocomplain -types d -directory $dir *]] {
    set cell [file tail $c]
    if {[file exists $c/$cell.sym]} { lappend out [list $cell $name/$cell/$cell.sym $c/$cell.sym] }
  }
  return $out
}

# {type pins} of a symbol file: its K type and its pins (B 5 rectangles) in drawing order
proc ol_inst_symbol_info {file} {
  set type {}
  set pins {}
  if {[catch {open $file} fd]} { return [list {} {}] }
  set text [read $fd]
  close $fd
  regexp {(?n)^K \{[^\}]*type=([^\s\}]+)} $text -> type
  foreach line [split $text \n] {
    # a pin drawn on more than one edge (a feed-through) is listed once
    if {[string match {B 5 *} $line] && [regexp {name=([^\s\}]+)} $line -> n] && $n ni $pins} { lappend pins $n }
  }
  return [list $type $pins]
}

# a dim placeholder in an empty entry (Tk entries have none)
proc ol_placeholder {e text} {
  global ol_ui
  set l $e.ph
  label $l -text $text -foreground $ol_ui(dim) -background [$e cget -background] -font [$e cget -font] -anchor w
  set update [list apply {{e l} {
    if {[winfo exists $e] && [$e get] eq ""} { place $l -in $e -x 4 -rely 0.5 -anchor w } else { place forget $l }
  }} $e $l]
  bind $l <Button-1> [list focus $e]
  trace add variable ::[$e cget -textvariable] write [list apply {{cmd args} {after idle $cmd}} $update]
  after idle $update
}

proc ol_instance_browser {} {
  global ol_inst ol_ui ol_theme
  set w .ol_inst
  if {[winfo exists $w]} { wm deiconify $w; raise $w; focus $w.body.cell.f; return }
  set ol_inst(libs) [ol_inst_libraries]
  if {![info exists ol_inst(keep)]} { set ol_inst(keep) 0 }
  if {![info exists ol_inst(lib)]} { set ol_inst(lib) [lindex $ol_inst(libs) 0 0] }
  set ol_inst(filter) {}
  set ol_inst(cells) {}
  set ol_inst(shown) {}
  set ol_inst(file) {}
  array set cv $ol_theme(canvas)
  set head [list [lindex $ol_theme(font) 0] [lindex $ol_theme(font) 1] bold]
  set small [list [lindex $ol_theme(font) 0] [expr {[lindex $ol_theme(font) 1] - 1}]]

  toplevel $w -background $ol_ui(window)
  wm title $w "Add Instance"
  wm transient $w [xschem get topwindow]
  wm protocol $w WM_DELETE_WINDOW ol_inst_close

  # the columns: Library | Cell (filter) | preview + info, like the hub's Library Manager
  frame $w.body -background $ol_ui(window)
  foreach {col title} {lib Library cell Cell} {
    set f $w.body.$col
    frame $f -background $ol_ui(window)
    label $f.t -text $title -foreground $ol_ui(dim) -background $ol_ui(window) -anchor w -font $head
    listbox $f.l -exportselection 0 -activestyle none -width [expr {$col eq "lib" ? 22 : 26}] -height 18 \
      -background $ol_ui(base) -foreground $ol_ui(text) -selectbackground $ol_ui(select) \
      -selectforeground #ffffff -relief flat -borderwidth 0 -highlightthickness 0 \
      -yscrollcommand [list $f.y set]
    scrollbar $f.y -orient vertical -command [list $f.l yview]
    grid $f.t -row 0 -column 0 -columnspan 2 -sticky w -pady {0 4}
  }
  entry $w.body.cell.f -textvariable ol_inst(filter) -background $ol_ui(base) -foreground $ol_ui(text) \
    -insertbackground $ol_ui(text) -relief flat -borderwidth 4 -highlightthickness 1 \
    -highlightbackground $ol_ui(border) -highlightcolor $ol_ui(accent)
  ol_placeholder $w.body.cell.f "Filter"
  grid $w.body.cell.f -row 1 -column 0 -columnspan 2 -sticky we -pady {0 4}
  label $w.body.lib.sp -text " " -background $ol_ui(window) -font $small   ;# lines up with the filter
  grid $w.body.lib.sp -row 1 -column 0 -sticky w -pady {0 4}
  foreach col {lib cell} {
    grid $w.body.$col.l -row 2 -column 0 -sticky nsew
    grid $w.body.$col.y -row 2 -column 1 -sticky ns
    grid rowconfigure $w.body.$col 2 -weight 1
    grid columnconfigure $w.body.$col 0 -weight 1
  }

  set p $w.body.pv
  frame $p -background $ol_ui(window)
  label $p.t -text Symbol -foreground $ol_ui(dim) -background $ol_ui(window) -anchor w -font $head
  frame $p.box -background $ol_ui(border) -padx 1 -pady 1
  frame $p.box.draw -background $cv(background) -width 360 -height 260 -takefocus 0
  pack $p.box.draw -fill both -expand 1
  label $p.name -text "" -foreground $ol_ui(text) -background $ol_ui(window) -anchor w -font $head
  label $p.path -text "" -foreground $ol_ui(dim) -background $ol_ui(window) -anchor w -font $small
  label $p.pins -text "" -foreground $ol_ui(text) -background $ol_ui(window) -anchor w -justify left \
    -wraplength 360
  grid $p.t -row 0 -column 0 -sticky w -pady {0 4}
  grid $p.box -row 1 -column 0 -sticky nsew
  grid $p.name -row 2 -column 0 -sticky w -pady {8 0}
  grid $p.path -row 3 -column 0 -sticky w
  grid $p.pins -row 4 -column 0 -sticky w -pady {4 0}
  grid rowconfigure $p 1 -weight 1
  grid columnconfigure $p 0 -weight 1

  grid $w.body.lib -row 0 -column 0 -sticky nsew -padx {0 10}
  grid $w.body.cell -row 0 -column 1 -sticky nsew -padx {0 10}
  grid $p -row 0 -column 2 -sticky nsew
  grid columnconfigure $w.body 0 -weight 1
  grid columnconfigure $w.body 1 -weight 1
  grid columnconfigure $w.body 2 -weight 3
  grid rowconfigure $w.body 0 -weight 1

  # bottom: hint, keep open, Close / Place
  frame $w.foot -background $ol_ui(window)
  label $w.foot.hint -text "Double-click or Enter places the symbol on the mouse  ·  Esc closes" \
    -foreground $ol_ui(dim) -background $ol_ui(window) -font $small
  checkbutton $w.foot.keep -text "Keep open" -variable ol_inst(keep) -background $ol_ui(window) \
    -activebackground $ol_ui(window) -foreground $ol_ui(text) -selectcolor $ol_ui(base) \
    -highlightthickness 0
  button $w.foot.close -text Close -command ol_inst_close -width 8
  button $w.foot.place -text Place -command ol_inst_place -width 8 -state disabled
  ol_primary $w.foot.place
  pack $w.foot.hint -side left
  pack $w.foot.place $w.foot.close -side right -padx {6 0}
  pack $w.foot.keep -side right -padx {0 12}

  pack $w.foot -side bottom -fill x -padx 14 -pady {6 12}
  pack $w.body -side top -fill both -expand 1 -padx 14 -pady {12 0}

  foreach lib $ol_inst(libs) {
    lassign $lib name dir kind
    $w.body.lib.l insert end $name
    if {$kind ne "design"} { $w.body.lib.l itemconfigure end -foreground $ol_ui(dim) }
  }
  bind $w.body.lib.l <<ListboxSelect>> ol_inst_lib_changed
  bind $w.body.cell.l <<ListboxSelect>> ol_inst_cell_changed
  bind $w.body.cell.l <Double-Button-1> ol_inst_place
  bind $w <Return> ol_inst_place
  bind $w <KP_Enter> ol_inst_place
  bind $w <Escape> ol_inst_close
  # arrows in the filter move through the cells
  bind $w.body.cell.f <Down> {ol_inst_step 1; break}
  bind $w.body.cell.f <Up> {ol_inst_step -1; break}
  trace add variable ol_inst(filter) write ol_inst_filter_changed

  # where it was last time, else centred on xschem's window
  if {[info exists ol_inst(geometry)]} {
    wm geometry $w $ol_inst(geometry)
  } else {
    wm withdraw $w
    update idletasks
    set top [xschem get topwindow]
    set x [expr {[winfo rootx $top] + ([winfo width $top] - [winfo reqwidth $w]) / 2}]
    set y [expr {[winfo rooty $top] + ([winfo height $top] - [winfo reqheight $w]) / 3}]
    wm geometry $w +[expr {max(0, $x)}]+[expr {max(0, $y)}]
    wm deiconify $w
  }
  # the preview needs its window mapped (a size) before the first drawing
  tkwait visibility $p.box.draw
  xschem preview_window create $p.box.draw {}
  set i [lsearch -index 0 $ol_inst(libs) $ol_inst(lib)]
  $w.body.lib.l selection set [expr {$i < 0 ? 0 : $i}]
  $w.body.lib.l see [expr {$i < 0 ? 0 : $i}]
  ol_inst_lib_changed
  focus $w.body.cell.f
}

proc ol_inst_lib_changed {} {
  global ol_inst
  set w .ol_inst
  set sel [$w.body.lib.l curselection]
  if {$sel eq ""} return
  set lib [lindex $ol_inst(libs) $sel]
  set ol_inst(lib) [lindex $lib 0]
  set ol_inst(cells) [ol_inst_cells $lib]
  ol_inst_show_cells
}

proc ol_inst_filter_changed {args} {
  if {[winfo exists .ol_inst]} { ol_inst_show_cells }
}

# the cells matching the filter (case-insensitive; * and ? work as in a glob, else a substring)
proc ol_inst_show_cells {} {
  global ol_inst
  set w .ol_inst
  set pat [string tolower [string trim $ol_inst(filter)]]
  if {$pat ne "" && ![regexp {[*?\[]} $pat]} { set pat *$pat* }
  set keep [lindex $ol_inst(shown) [$w.body.cell.l curselection]]
  $w.body.cell.l delete 0 end
  set ol_inst(shown) {}
  foreach c $ol_inst(cells) {
    if {$pat ne "" && ![string match $pat [string tolower [lindex $c 0]]]} continue
    lappend ol_inst(shown) $c
    $w.body.cell.l insert end [lindex $c 0]
  }
  $w.body.cell.t configure -text "Cell ([llength $ol_inst(shown)])"
  set i [lsearch -exact $ol_inst(shown) $keep]
  if {$i < 0 && [llength $ol_inst(shown)]} { set i 0 }
  if {$i >= 0} {
    $w.body.cell.l selection set $i
    $w.body.cell.l see $i
  }
  ol_inst_cell_changed
}

proc ol_inst_step {d} {
  set l .ol_inst.body.cell.l
  set n [$l size]
  if {!$n} return
  set i [lindex [$l curselection] 0]
  set i [expr {$i eq "" ? 0 : max(0, min($n - 1, $i + $d))}]
  $l selection clear 0 end
  $l selection set $i
  $l see $i
  ol_inst_cell_changed
}

proc ol_inst_cell_changed {} {
  global ol_inst
  set w .ol_inst
  set p $w.body.pv
  set c [lindex $ol_inst(shown) [lindex [$w.body.cell.l curselection] 0]]
  if {$c eq ""} {
    set ol_inst(file) {}
    $p.name configure -text ""
    $p.path configure -text ""
    $p.pins configure -text ""
    $w.foot.place configure -state disabled
    bind $p.box.draw <Expose> {}
    bind $p.box.draw <Configure> {}
    catch {xschem preview_window close $p.box.draw {}}
    $p.box.draw configure -background [dict get $::ol_theme(canvas) background]
    return
  }
  lassign $c cell ref file
  set ol_inst(file) $file
  lassign [ol_inst_symbol_info $file] type pins
  $p.name configure -text "$ol_inst(lib) / $cell[expr {$type ne {} ? "   ($type)" : ""}]"
  $p.path configure -text $ref
  set n [llength $pins]
  $p.pins configure -text [expr {$n ? "[expr {$n == 1 ? {1 pin} : "$n pins"}]:  [join $pins {  }]" : "no pins"}]
  $w.foot.place configure -state normal
  # no frame background while xschem draws in it (Tk would paint over the drawing), as xschem's own
  # choosers do
  $p.box.draw configure -background {}
  xschem preview_window draw $p.box.draw $file
  bind $p.box.draw <Expose> [list xschem preview_window draw $p.box.draw $file]
  bind $p.box.draw <Configure> [list xschem preview_window draw $p.box.draw $file]
}

proc ol_inst_place {} {
  global ol_inst
  set w .ol_inst
  set c [lindex $ol_inst(shown) [lindex [$w.body.cell.l curselection] 0]]
  if {$c eq ""} return
  set ref [lindex $c 1]
  if {!$ol_inst(keep)} { ol_inst_close }
  set drw [xschem get current_win_path]
  if {[winfo exists $drw]} { focus $drw }
  if {[xschem get ui_state] & 8192} { xschem abort_operation }   ;# PLACE_SYMBOL: replace it
  xschem place_symbol $ref
}

proc ol_inst_close {} {
  global ol_inst
  set w .ol_inst
  if {![winfo exists $w]} return
  set ol_inst(geometry) [wm geometry $w]
  foreach t [trace info variable ::ol_inst(filter)] { trace remove variable ::ol_inst(filter) {*}$t }
  catch {xschem preview_window destroy $w.body.pv.box.draw {}}
  destroy $w
}

# Tools > Insert symbol and the toolbar's symbol button open it too
proc ol_inst_hook_ui {} {
  set top [xschem get top_path]
  set m $top.menubar.tools
  set i [ol_menu_find $m {Insert symbol}]
  if {$i >= 0} {
    $m entryconfigure $i -label "Add Instance…" -command ol_instance_browser -accelerator "I, Ins"
  }
  foreach b [winfo children $top.toolbar] {
    if {[catch {$b cget -command} cmd]} continue
    if {[string trim $cmd] eq "xschem place_symbol"} { $b configure -command ol_instance_browser }
  }
}
ol_inst_hook_ui
