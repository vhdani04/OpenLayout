# OpenLayout editing for xschem (sourced via tcl_files once the main window exists):
#   - Cadence-style property form for instances (q / double-click)
#   - pin dialog on P: names + direction, then the pins follow the mouse
#   - context keys: L / R draw line / rectangle in symbols, net label / rotate in schematics
#   - lines can be drawn at any angle (wires stay orthogonal)

if {[info commands winfo] eq ""} { return }

proc ol_in_symbol {} {
  return [expr {[file extension [xschem get schname]] eq ".sym"}]
}

# Drawing-area coordinates (pixels) -> schematic coordinates, snapped to the snap grid.
proc ol_to_sch {px py} {
  set z [xschem get zoom]
  set snap 10
  catch {set snap [xschem get cadsnap]}
  if {![string is double -strict $snap] || $snap <= 0} { set snap 10 }
  set x [expr {$px * $z - [xschem get xorigin]}]
  set y [expr {$py * $z - [xschem get yorigin]}]
  return [list [expr {round($x / $snap) * $snap}] [expr {round($y / $snap) * $snap}]]
}

proc ol_center_on_pointer {w} {
  update idletasks
  lassign [winfo pointerxy .] x y
  set x [expr {max(0, $x - [winfo reqwidth $w] / 2)}]
  set y [expr {max(0, $y - 40)}]
  wm geometry $w +$x+$y
}

# ---- property form -----------------------------------------------------------------------------

# Attribute values with spaces, quotes or backslashes are stored quoted (xschem syntax).
proc ol_quote_value {v} {
  if {[regexp {[\s"\\]} $v]} {
    regsub -all {(["\\])} $v {\\\1} v
    return "\"$v\""
  }
  return $v
}

if {[info commands ol_edit_prop_text] eq ""} {
  rename edit_prop ol_edit_prop_text
}

# Replaces xschem's edit_prop (called by xschem for instance properties). Same contract: reads
# tctx::retval (attribute string) and symbol, returns tctx::rcode (ok / empty = cancelled) and
# leaves the new attribute string in tctx::retval.
proc edit_prop {txtlabel} {
  global symbol no_change_attrs preserve_unchanged_attrs user_wants_copy_cell ol_props ol_theme
  set type {}
  catch {set type [xschem getprop symbol $symbol type]}
  # Code blocks and similar keep xschem's text editor.
  if {$type in {netlist_commands} || [string first "\n" $tctx::retval] >= 0} {
    return [ol_edit_prop_text $txtlabel]
  }
  set user_wants_copy_cell 0
  set no_change_attrs 0
  set preserve_unchanged_attrs 1   ;# with several instances selected, apply only edited fields
  set tctx::rcode {}
  set orig $tctx::retval
  set template {}
  catch {set template [xschem getprop symbol $symbol template]}

  # name first, then the symbol's parameters (template order), then anything else on the instance
  set keys {name}
  foreach k [concat [xschem list_tokens $template 0] [xschem list_tokens $orig 0]] {
    if {$k ni $keys} { lappend keys $k }
  }
  array unset ol_props
  foreach k $keys {
    if {[xschem list_tokens $orig 0] ne {} && $k in [xschem list_tokens $orig 0]} {
      set ol_props($k) [xschem get_tok $orig $k 0]
    } else {
      set ol_props($k) {}
    }
    set ol_props(orig,$k) $ol_props($k)
  }

  set w .ol_props
  catch {destroy $w}
  toplevel $w
  wm title $w "Edit Object Properties"
  wm transient $w [xschem get topwindow]
  frame $w.head
  label $w.head.cell -text "Cell:  $symbol" -anchor w -font $ol_theme(font)
  pack $w.head.cell -side top -fill x
  set nsel [xschem get lastsel]
  if {$nsel > 1} {
    label $w.head.n -text "$nsel objects selected - edited fields apply to all of them" -anchor w
    pack $w.head.n -side top -fill x
  }
  pack $w.head -side top -fill x -padx 10 -pady {10 4}

  frame $w.f
  set r 0
  foreach k $keys {
    set title [expr {$k eq "name" ? "Instance Name" : $k}]
    label $w.f.l$r -text $title -anchor e
    entry $w.f.e$r -textvariable ol_props($k) -width 34
    grid $w.f.l$r -row $r -column 0 -sticky e -padx {0 8} -pady 2
    grid $w.f.e$r -row $r -column 1 -sticky we -pady 2
    incr r
  }
  grid columnconfigure $w.f 1 -weight 1
  pack $w.f -side top -fill both -expand 1 -padx 10 -pady 4
  catch {focus $w.f.e[expr {[llength $keys] > 1 ? 1 : 0}]; $w.f.e[expr {[llength $keys] > 1 ? 1 : 0}] selection range 0 end}

  # add a new property
  frame $w.add
  label $w.add.l -text "Add property"
  entry $w.add.k -width 10
  label $w.add.eq -text "="
  entry $w.add.v -width 16
  button $w.add.b -text "Add" -command [list ol_props_add $w]
  pack $w.add.l $w.add.k $w.add.eq $w.add.v $w.add.b -side left -padx 2
  pack $w.add -side top -fill x -padx 10 -pady 4

  frame $w.b
  button $w.b.text -text "Text Editor…" -command {set tctx::rcode text; destroy .ol_props}
  button $w.b.cancel -text "Cancel" -width 8 -command {set tctx::rcode {}; destroy .ol_props}
  button $w.b.ok -text "OK" -width 8 -command {set tctx::rcode ok; destroy .ol_props}
  pack $w.b.text -side left
  pack $w.b.ok $w.b.cancel -side right -padx 4
  pack $w.b -side top -fill x -padx 10 -pady {4 10}
  bind $w <Return> {.ol_props.b.ok invoke}
  bind $w <KP_Enter> {.ol_props.b.ok invoke}
  bind $w <Escape> {.ol_props.b.cancel invoke}
  catch {ol_restyle $w}   ;# dark theme (xschem's own option values win over theme defaults)
  ol_center_on_pointer $w
  tkwait visibility $w
  grab set $w
  tkwait window $w

  if {$tctx::rcode eq "text"} {
    set tctx::retval $orig
    return [ol_edit_prop_text $txtlabel]
  }
  if {$tctx::rcode ne "ok"} {
    set tctx::retval $orig
    return {}
  }
  set new $orig
  foreach k [array names ol_props] {
    if {[string match orig,* $k]} continue
    if {![info exists ol_props(orig,$k)] || $ol_props($k) ne $ol_props(orig,$k)} {
      set new [xschem subst_tok $new $k [ol_quote_value $ol_props($k)]]
    }
  }
  set tctx::retval $new
  return ok
}

proc ol_props_add {w} {
  global ol_props
  set k [string trim [$w.add.k get]]
  if {$k eq "" || ![regexp {^[A-Za-z_][A-Za-z0-9_:]*$} $k] || [info exists ol_props($k)]} { bell; return }
  set ol_props($k) [$w.add.v get]
  set r [llength [winfo children $w.f]]
  set r [expr {$r / 2}]
  label $w.f.l$r -text $k -anchor e
  entry $w.f.e$r -textvariable ol_props($k) -width 34
  grid $w.f.l$r -row $r -column 0 -sticky e -padx {0 8} -pady 2
  grid $w.f.e$r -row $r -column 1 -sticky we -pady 2
  catch {ol_restyle $w.f}
  $w.add.k delete 0 end
  $w.add.v delete 0 end
}

# ---- pins ------------------------------------------------------------------------------------

proc ol_pin_dialog {px py} {
  global ol_pin
  if {![info exists ol_pin(dir)]} { set ol_pin(dir) input }
  set ol_pin(names) {}
  set ol_pin(rc) {}
  set w .ol_pin
  catch {destroy $w}
  toplevel $w
  wm title $w [expr {[ol_in_symbol] ? "Add Symbol Pin" : "Create Pin"}]
  wm transient $w [xschem get topwindow]
  frame $w.f
  label $w.f.ln -text "Pin Names" -anchor e
  entry $w.f.n -textvariable ol_pin(names) -width 28
  label $w.f.hint -text "several names: separate with spaces" -anchor w
  label $w.f.ld -text "Direction" -anchor e
  frame $w.f.d
  foreach {d t} {input Input output Output inout Input-Output} {
    radiobutton $w.f.d.$d -text $t -value $d -variable ol_pin(dir)
    pack $w.f.d.$d -side left -padx {0 8}
  }
  grid $w.f.ln -row 0 -column 0 -sticky e -padx {0 8} -pady 2
  grid $w.f.n -row 0 -column 1 -sticky we -pady 2
  grid $w.f.hint -row 1 -column 1 -sticky w
  grid $w.f.ld -row 2 -column 0 -sticky e -padx {0 8} -pady 6
  grid $w.f.d -row 2 -column 1 -sticky w -pady 6
  pack $w.f -padx 10 -pady 10 -fill x
  frame $w.b
  button $w.b.cancel -text "Cancel" -width 8 -command {set ol_pin(rc) {}; destroy .ol_pin}
  button $w.b.ok -text "Place" -width 8 -command {set ol_pin(rc) ok; destroy .ol_pin}
  pack $w.b.ok $w.b.cancel -side right -padx 4
  pack $w.b -side top -fill x -padx 10 -pady {0 10}
  bind $w <Return> {.ol_pin.b.ok invoke}
  bind $w <KP_Enter> {.ol_pin.b.ok invoke}
  bind $w <Escape> {.ol_pin.b.cancel invoke}
  catch {ol_restyle $w}
  ol_center_on_pointer $w
  focus $w.f.n
  tkwait visibility $w
  grab set $w
  tkwait window $w
  set names [regexp -all -inline {[^\s,]+} $ol_pin(names)]
  if {$ol_pin(rc) ne "ok" || ![llength $names]} { return }
  ol_place_pins $names $ol_pin(dir) $px $py
}

# Create the pins stacked at the pointer, then let them follow the mouse until the user clicks.
# px/py: pointer position in drawing-area pixels (from the key event).
proc ol_place_pins {names dir px py} {
  lassign [ol_to_sch $px $py] x y
  xschem unselect_all
  set step 20
  if {[ol_in_symbol]} {
    set d [dict get {input in output out inout inout} $dir]
    foreach n $names {
      xschem add_symbol_pin $x $y $n $d
      xschem select rect 5 [expr {[xschem get rects 5] - 1}] fast
      incr y $step
    }
  } else {
    set sym [dict get {input ipin.sym output opin.sym inout iopin.sym} $dir]
    set first 1
    foreach n $names {
      set iname "p_$n"
      xschem instance $sym $x $y 0 0 "name=$iname lab=$n" [expr {!$first}]
      xschem select instance $iname fast
      set first 0
      incr y $step
    }
  }
  # Start a move at the pointer (m with xschem's infix interface, which moves immediately instead of
  # waiting for a reference click): the new pins follow the mouse until the click.
  set infix 0
  catch {set infix $::infix_interface}
  set ::infix_interface 1
  xschem callback .drw 2 $px $py 109 0 0 0
  set ::infix_interface $infix
}

# ---- context keys ------------------------------------------------------------------------------

# Free-angle lines: xschem keeps one manhattan mode for lines and wires and orthogonal wiring
# leaves it set; toggling orthogonal wiring off and on (Shift+L) resets it to "any angle".
proc ol_free_angle {w x y} {
  if {[info exists ::orthogonal_wiring] && $::orthogonal_wiring} {
    xschem callback $w 2 $x $y 76 0 0 1
    xschem callback $w 2 $x $y 76 0 0 1
  }
}

proc ol_key_l {w x y} {
  if {[ol_in_symbol]} {
    ol_free_angle $w $x $y
    xschem line
  } else {
    xschem callback $w 2 $x $y 108 0 0 8   ;# Alt+l: wire name (net label)
  }
}

proc ol_key_r {w x y} {
  if {[ol_in_symbol]} {
    xschem rect
  } else {
    xschem callback $w 2 $x $y 82 0 0 1    ;# Shift+R: rotate
  }
}

proc ol_bind_keys {{w .drw}} {
  if {![winfo exists $w]} return
  bind $w <KeyPress-p> {ol_pin_dialog %x %y; break}
  bind $w <KeyPress-l> {ol_key_l %W %x %y; break}
  bind $w <KeyPress-r> {ol_key_r %W %x %y; break}
}

if {!([info exists env(OPENLAYOUT_KEYS)] && $env(OPENLAYOUT_KEYS) eq "xschem")} {
  ol_bind_keys
}
