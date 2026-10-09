# OpenLayout editing for xschem (sourced via tcl_files once the main window exists):
#   - property form for instances (q / double-click)
#   - pin dialog on P: names (buses: WL[1:0]) + direction, then the pins follow the mouse
#   - context keys: L / R draw line / rectangle in symbols, net label / rotate in schematics
#   - lines can be drawn at any angle (wires stay orthogonal)

if {[info commands winfo] eq ""} { return }

proc ol_in_symbol {} {
  return [expr {[file extension [xschem get schname]] eq ".sym"}]
}

# Drawing-area coordinates (pixels) -> schematic coordinates, snapped to `snap` (default 10: the
# pin/connection grid, also used in the symbol editor whose drawing snap is finer).
proc ol_to_sch {px py {snap 10}} {
  set z [xschem get zoom]
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
# P opens the pin dialog: one or more names (spaces between them), a direction, and whether buses
# are expanded. A bus is xschem's WL[1:0] (Cadence-style WL<1:0> is accepted and written as
# WL[1:0]). Unexpanded, it is one bus pin: wires labelled WL[1] / WL[0] connect to its bits by name,
# and the netlist has one port per bit. Expanded, it becomes one pin per bit (WL[1], WL[0]).
# The new pins then follow the mouse; a click places them (nothing stays selected), Esc discards
# them.

# Cadence bus syntax -> xschem's: WL<1:0> -> WL[1:0], D<3> -> D[3]
proc ol_bus_syntax {name} {
  regsub -all {<([^<>]*)>} $name {[\1]} name
  return $name
}

# The names typed in the dialog: separated by spaces, or commas outside brackets.
proc ol_pin_names {text} {
  set out {}
  foreach word [regexp -all -inline {\S+} [ol_bus_syntax $text]] {
    set cur {}
    set depth 0
    foreach ch [split $word {}] {
      if {$ch eq "\["} { incr depth } elseif {$ch eq "\]"} { incr depth -1 }
      if {$ch eq "," && $depth == 0} {
        if {$cur ne {}} { lappend out $cur }
        set cur {}
      } else {
        append cur $ch
      }
    }
    if {$cur ne {}} { lappend out $cur }
  }
  return $out
}

# A name's bits, MSB first as written (WL[1:0] -> WL[1] WL[0]); a plain name is itself.
proc ol_bus_bits {name} {
  if {![string match {*\[*} $name]} { return [list $name] }
  lassign [xschem expandlabel $name] bits n
  return [split $bits ,]
}

# Why a name can't be a pin, or "" if it can.
proc ol_pin_name_error {name} {
  if {![regexp {^[A-Za-z_][A-Za-z0-9_]*(\[[0-9:,]+\])?$} $name]} {
    return "\"$name\": use letters, digits and _, optionally a bus range like WL\[1:0\]"
  }
  if {[string match {*\[*} $name]} {
    lassign [xschem expandlabel $name] bits n
    if {$n eq {} || $n < 1} { return "\"$name\": not a valid bus range" }
  }
  return {}
}

# An instance name for a pin labelled `lab`: p_<lab> with anything but letters, digits and _ made
# _ (brackets in an instance name would make it an instance array), unique in the schematic.
proc ol_pin_instname {lab} {
  regsub -all {[^A-Za-z0-9_]} "p_$lab" _ base
  regsub {_+$} $base {} base
  set taken {}
  for {set k 0} {$k < [xschem get instances]} {incr k} {
    lappend taken [xschem getprop instance $k name]
  }
  set name $base
  set n 1
  while {$name in $taken} { set name "${base}_[incr n]" }
  return $name
}

proc ol_pin_dialog {px py} {
  global ol_pin
  ol_pin_cancel_placing
  if {![info exists ol_pin(dir)]} { set ol_pin(dir) input }
  if {![info exists ol_pin(expand)]} { set ol_pin(expand) 0 }
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
  label $w.f.hint -text "several names: separate with spaces    bus: WL\[1:0\]" -anchor w
  label $w.f.ld -text "Direction" -anchor e
  frame $w.f.d
  foreach {d t} {input Input output Output inout Input-Output} {
    radiobutton $w.f.d.$d -text $t -value $d -variable ol_pin(dir)
    pack $w.f.d.$d -side left -padx {0 8}
  }
  checkbutton $w.f.x -text "Expand buses into one pin per bit" -variable ol_pin(expand) -anchor w
  label $w.f.err -text "" -anchor w -foreground #e06c75
  grid $w.f.ln -row 0 -column 0 -sticky e -padx {0 8} -pady 2
  grid $w.f.n -row 0 -column 1 -sticky we -pady 2
  grid $w.f.hint -row 1 -column 1 -sticky w
  grid $w.f.ld -row 2 -column 0 -sticky e -padx {0 8} -pady 6
  grid $w.f.d -row 2 -column 1 -sticky w -pady 6
  grid $w.f.x -row 3 -column 1 -sticky w
  grid $w.f.err -row 4 -column 1 -sticky w
  pack $w.f -padx 10 -pady 10 -fill x
  frame $w.b
  button $w.b.cancel -text "Cancel" -width 8 -command {set ol_pin(rc) {}; destroy .ol_pin}
  button $w.b.ok -text "Place" -width 8 -command ol_pin_ok
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
  if {$ol_pin(rc) ne "ok"} { return }
  set labels {}
  foreach n [ol_pin_names $ol_pin(names)] {
    if {$ol_pin(expand)} { lappend labels {*}[ol_bus_bits $n] } else { lappend labels $n }
  }
  if {[llength $labels]} { ol_place_pins $labels $ol_pin(dir) $px $py }
}

# Place: check the names first; the dialog stays open (with the reason) for a bad one.
proc ol_pin_ok {} {
  global ol_pin
  set names [ol_pin_names $ol_pin(names)]
  if {![llength $names]} { .ol_pin.f.err configure -text "type at least one pin name"; return }
  foreach n $names {
    set e [ol_pin_name_error $n]
    if {$e ne {}} { .ol_pin.f.err configure -text $e; return }
  }
  set ol_pin(rc) ok
  destroy .ol_pin
}

# Create the pins stacked at the pointer, then let them follow the mouse until the user clicks.
# px/py: pointer position in drawing-area pixels (from the key event).
proc ol_place_pins {labels dir px py} {
  global ol_placing
  lassign [ol_to_sch $px $py] x y
  xschem unselect_all
  set step 20
  set made {}
  if {[ol_in_symbol]} {
    set d [dict get {input in output out inout inout} $dir]
    foreach n $labels {
      xschem add_symbol_pin $x $y $n $d
      set i [expr {[xschem get rects 5] - 1}]
      xschem select rect 5 $i fast
      lappend made [list rect $i]
      incr y $step
    }
  } else {
    set sym [dict get {input ipin.sym output opin.sym inout iopin.sym} $dir]
    set first 1
    foreach n $labels {
      set iname [ol_pin_instname $n]
      xschem instance $sym $x $y 0 0 "name=$iname lab=$n" [expr {!$first}]
      # select the one just made (by name: unique - an older pin of the same label is left alone)
      xschem select instance $iname fast
      lappend made [list instance $iname]
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
  # Watch the move: placed (a click) - unselect them; discarded (Esc) - delete them.
  set ol_placing(made) $made
  set ol_placing(esc) 0
  set ol_placing(active) 1
  set generic [bind .drw <KeyPress>]
  bind .drw <KeyPress-Escape> "set ::ol_placing(esc) 1\n$generic"
  after 40 ol_pin_watch
}

proc ol_pin_watch {} {
  global ol_placing
  if {![info exists ol_placing(active)] || !$ol_placing(active)} { return }
  if {[xschem get ui_state] & 32} {                 ;# STARTMOVE: still following the mouse
    after 40 ol_pin_watch
    return
  }
  set ol_placing(active) 0
  bind .drw <KeyPress-Escape> {}
  if {$ol_placing(esc)} {
    xschem unselect_all
    foreach m $ol_placing(made) {
      lassign $m kind id
      if {$kind eq "instance"} { xschem select instance $id fast } else { xschem select rect 5 $id fast }
    }
    xschem delete
  }
  # placed: the click that dropped them also selected what was under it - nothing stays selected
  xschem unselect_all
  xschem redraw
}

# A new P (or anything that must not run while pins are being placed) ends a placement first.
proc ol_pin_cancel_placing {} {
  global ol_placing
  if {[info exists ol_placing(active)] && $ol_placing(active)} {
    set ol_placing(esc) 1
    catch {xschem abort_operation}
    ol_pin_watch
  }
}

# ---- drawing tools vs. persistent commands ----------------------------------------------------
# With persistent commands on, xschem restarts the last line/wire on every click *before* looking at
# a newly chosen tool - picking circle/arc/rectangle after drawing a line kept drawing lines. Every
# tool entry point (toolbar, menus, keys) first ends the persistent command.
proc ol_end_persistent {} {
  # 1st call ends a line/wire in progress, 2nd clears the remembered command
  catch {xschem abort_operation}
  catch {xschem abort_operation}
}

proc ol_tool {args} {
  ol_end_persistent
  xschem {*}$args
}

proc ol_wrap_menu {m re} {
  if {![winfo exists $m] || [catch {$m index end} last] || $last eq "none"} { return }
  for {set i 0} {$i <= $last} {incr i} {
    switch -- [$m type $i] {
      cascade { ol_wrap_menu [$m entrycget $i -menu] $re }
      command {
        if {[regexp $re [$m entrycget $i -command] -> tool]} {
          $m entryconfigure $i -command [list ol_tool $tool]
        }
      }
    }
  }
}

proc ol_wrap_tool_commands {} {
  set re {^\s*xschem\s+(line|rect|polygon|arc|circle|place_text)\s*$}
  set top [xschem get top_path]
  if {[winfo exists $top.toolbar]} {
    foreach b [winfo children $top.toolbar] {
      if {![catch {$b cget -command} c] && [regexp $re $c -> tool]} {
        $b configure -command [list ol_tool $tool]
      }
    }
  }
  ol_wrap_menu $top.menubar $re
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
    ol_end_persistent
    ol_free_angle $w $x $y
    xschem line
  } else {
    xschem callback $w 2 $x $y 108 0 0 8   ;# Alt+l: wire name (net label)
  }
}

proc ol_key_r {w x y} {
  if {[ol_in_symbol]} {
    ol_tool rect
  } else {
    xschem callback $w 2 $x $y 82 0 0 1    ;# Shift+R: rotate
  }
}

proc ol_bind_keys {{w .drw}} {
  if {![winfo exists $w]} return
  bind $w <KeyPress-p> {ol_pin_dialog %x %y; break}
  bind $w <KeyPress-l> {ol_key_l %W %x %y; break}
  bind $w <KeyPress-r> {ol_key_r %W %x %y; break}
  # xschem's own shape keys: end the persistent line/wire first, then let xschem handle the key
  bind $w <KeyPress-w> {ol_end_persistent; xschem callback %W %T %x %y 119 0 0 0; break}
  bind $w <KeyPress-t> {ol_tool place_text; break}
  bind $w <Shift-KeyPress-C> {ol_tool arc; break}
  bind $w <Control-Shift-KeyPress-C> {ol_tool circle; break}
}

if {!([info exists env(OPENLAYOUT_KEYS)] && $env(OPENLAYOUT_KEYS) eq "xschem")} {
  ol_bind_keys
}
ol_wrap_tool_commands

# ---- grab a rectangle edge and slide it (stretch) -----------------------------------
# Hovering over an edge of a rectangle highlights just that edge (a corner: both of its edges). Press
# and drag it: a dashed outline shows the resized rectangle, with the grabbed edge highlighted, and
# the edge snaps to the grid. On release the rectangle takes the outline's size (one undo step).
# Pins (layer 5) are left alone: pressing on a pin still moves it. xschem has no overlay drawing, so
# the outline and highlight are thin Tk canvases placed over the drawing area; they pass the mouse
# on to it.
array set ol_stretch {active 0 pixels 6 key {} rects {}}

proc ol_stretch_colors {} {
  # background, dashed outline, highlighted edge
  if {![info exists ::dark_colorscheme] || $::dark_colorscheme} {
    set bg [expr {[info exists ::dark_colors] ? [lindex $::dark_colors 0] : "#000000"}]
    return [list $bg #ffffff #ffd23f]
  }
  set bg [expr {[info exists ::light_colors] ? [lindex $::light_colors 0] : "#ffffff"}]
  return [list $bg #000000 #ff8c00]
}

# {c i x1 y1 x2 y2} of every rectangle. xschem only reports coordinates of selected rectangles, so
# each one is selected and unselected without drawing; rectangles already selected stay selected.
# Cached until the drawing may have changed (see ol_rects_changed).
proc ol_rect_list {} {
  global ol_stretch
  set counts {}
  for {set c 0} {$c < $::cadlayers} {incr c} { lappend counts [xschem get rects $c] }
  set key [list [xschem get schname] $counts]
  if {$key eq $ol_stretch(key)} { return $ol_stretch(rects) }
  set selected {}
  foreach r [split [xschem selected_set rect] \n] {
    if {[llength $r] == 6} { dict set selected [lrange $r 0 1] $r }
  }
  set had [xschem get lastsel]
  set rects {}
  for {set c 0} {$c < $::cadlayers} {incr c} {
    for {set i 0} {$i < [lindex $counts $c]} {incr i} {
      if {[dict exists $selected [list $c $i]]} {
        lappend rects [dict get $selected [list $c $i]]
        continue
      }
      xschem select rect $c $i fast nodraw
      foreach r [split [xschem selected_set rect] \n] {
        if {[lindex $r 0] == $c && [lindex $r 1] == $i} { lappend rects $r }
      }
      xschem select rect $c $i clear fast nodraw
    }
  }
  if {$had == 0} { xschem unselect_all 0 }
  set ol_stretch(key) $key
  set ol_stretch(rects) $rects
  return $rects
}

proc ol_rects_changed {} { set ::ol_stretch(key) {} }

# The rectangle edge nearest to drawing-area pixel (x, y): {c i x1 y1 x2 y2 edges} with edges a
# subset of {l r t b} (two for a corner), or {} if none is within reach or (x, y) is on a pin.
proc ol_edge_hit {x y} {
  global ol_stretch
  set z [xschem get zoom]
  set mx [expr {$x * $z - [xschem get xorigin]}]
  set my [expr {$y * $z - [xschem get yorigin]}]
  set tol [expr {$ol_stretch(pixels) * $z}]
  set rects [ol_rect_list]
  foreach r $rects {
    lassign $r c i x1 y1 x2 y2
    if {$c == 5 && $mx >= $x1 - $tol / 2 && $mx <= $x2 + $tol / 2 &&
        $my >= $y1 - $tol / 2 && $my <= $y2 + $tol / 2} { return {} }
  }
  set best {}
  set bestd $tol
  foreach r $rects {
    lassign $r c i x1 y1 x2 y2
    # pins, and rectangles too small on screen to tell an edge from the inside, move as a whole
    if {$c == 5 || $x2 - $x1 < 3 * $tol || $y2 - $y1 < 3 * $tol} continue
    if {$mx < $x1 - $tol || $mx > $x2 + $tol || $my < $y1 - $tol || $my > $y2 + $tol} continue
    set edges {}
    set d $tol
    foreach {e dist} [list l [expr {abs($mx - $x1)}] r [expr {abs($mx - $x2)}] \
                           t [expr {abs($my - $y1)}] b [expr {abs($my - $y2)}]] {
      if {$dist <= $tol} {
        lappend edges $e
        if {$dist < $d} { set d $dist }
      }
    }
    if {$edges ne {} && ($best eq {} || $d < $bestd)} {
      set best [list $c $i $x1 $y1 $x2 $y2 $edges]
      set bestd $d
    }
  }
  return $best
}

# -- overlay: straight screen-space segments drawn on thin canvases over the drawing area
proc ol_strip {w name} {
  set cw $w.olstrip_$name
  if {![winfo exists $cw]} {
    canvas $cw -highlightthickness 0 -bd 0 -width 1 -height 1
    $cw create line 0 0 0 0 -tags l -capstyle butt
    # the strips sit right under the mouse: hand everything on to the drawing area
    bind $cw <Motion> {ol_strip_fwd %W motion %x %y %b %s}
    bind $cw <ButtonPress-1> {ol_strip_fwd %W press %x %y %b %s}
    bind $cw <B1-Motion> {ol_strip_fwd %W drag %x %y %b %s}
    bind $cw <ButtonRelease-1> {ol_strip_fwd %W release %x %y %b %s}
    bind $cw <ButtonPress> {ol_strip_fwd %W ButtonPress %x %y %b %s}
    bind $cw <ButtonRelease> {ol_strip_fwd %W ButtonRelease %x %y %b %s}
  }
  return $cw
}

proc ol_strip_fwd {cw kind x y b s} {
  set w [winfo parent $cw]
  set x [expr {$x + [winfo x $cw]}]
  set y [expr {$y + [winfo y $cw]}]
  switch -- $kind {
    motion  { event generate $w <Motion> -x $x -y $y -state $s }
    press   { ol_press $w $x $y $b $s }
    drag    { ol_motion $w $x $y $s }
    release { ol_release $w $x $y $b $s }
    default { event generate $w <$kind> -x $x -y $y -state $s -button $b }
  }
}

# horizontal or vertical segment (x1,y1)-(x2,y2) in pixels, t pixels thick
proc ol_seg {w name x1 y1 x2 y2 color t dash cursor} {
  set cw [ol_strip $w $name]
  lassign [ol_stretch_colors] bg
  set h [expr {abs($y2 - $y1) < abs($x2 - $x1)}]
  set len [expr {round(abs($h ? $x2 - $x1 : $y2 - $y1)) + $t}]
  set x0 [expr {round(min($x1, $x2) - $t / 2)}]
  set y0 [expr {round(min($y1, $y2) - $t / 2)}]
  set m [expr {$t / 2}]   ;# integer: Tk rounds .5 up, which would put a 1 px line outside the strip
  if {$h} {
    $cw configure -width $len -height $t
    $cw coords l 0 $m $len $m
  } else {
    $cw configure -width $t -height $len
    $cw coords l $m 0 $m $len
  }
  $cw configure -bg $bg -cursor $cursor
  $cw itemconfigure l -fill $color -width $t -dash $dash
  place $cw -in $w -x $x0 -y $y0
  raise $cw
}

proc ol_overlay_clear {w {keep {}}} {
  foreach cw [winfo children $w] {
    if {[string match *.olstrip_* $cw] && $cw ni $keep} { place forget $cw }
  }
}

proc ol_edge_cursor {edges} {
  switch -- [lsort $edges] {
    {l} - {r} { return sb_h_double_arrow }
    {b} - {t} { return sb_v_double_arrow }
    {b l} { return bottom_left_corner }
    {b r} { return bottom_right_corner }
    {l t} { return top_left_corner }
    {r t} { return top_right_corner }
  }
  return {}
}

# Rectangle (x1 y1 x2 y2, schematic units) as a dashed outline with the given edges highlighted;
# a dashed outline only when dashed is set, otherwise just the highlighted edges.
proc ol_overlay_rect {w x1 y1 x2 y2 edges dashed} {
  set z [xschem get zoom]
  set xo [xschem get xorigin]
  set yo [xschem get yorigin]
  set px1 [expr {($x1 + $xo) / $z}]
  set px2 [expr {($x2 + $xo) / $z}]
  set py1 [expr {($y1 + $yo) / $z}]
  set py2 [expr {($y2 + $yo) / $z}]
  lassign [ol_stretch_colors] bg line hilite
  set cursor [ol_edge_cursor $edges]
  set used {}
  foreach {e a b c d} [list t $px1 $py1 $px2 $py1  b $px1 $py2 $px2 $py2 \
                            l $px1 $py1 $px1 $py2  r $px2 $py1 $px2 $py2] {
    if {$e in $edges} {
      ol_seg $w hi_$e $a $b $c $d $hilite 3 {} $cursor
      lappend used $w.olstrip_hi_$e
    } elseif {$dashed} {
      ol_seg $w dash_$e $a $b $c $d $line 1 {4 4} $cursor
      lappend used $w.olstrip_dash_$e
    }
  }
  # strips in use are moved, never unmapped (one may hold the mouse grab)
  ol_overlay_clear $w $used
}

# -- hover: highlight the edge under the mouse
proc ol_hover {w x y s} {
  global ol_stretch
  if {$ol_stretch(active)} return
  set hit {}
  if {($s & 0x1f0d) == 0 && ([xschem get ui_state] & ~8) == 0} { set hit [ol_edge_hit $x $y] }
  if {$hit eq {}} {
    if {$ol_stretch(hover) ne {}} {
      set ol_stretch(hover) {}
      ol_overlay_clear $w
      $w configure -cursor {}
    }
    return
  }
  lassign $hit c i x1 y1 x2 y2 edges
  if {$hit eq $ol_stretch(hover)} return
  set ol_stretch(hover) $hit
  ol_overlay_rect $w $x1 $y1 $x2 $y2 $edges 0
  $w configure -cursor [ol_edge_cursor $edges]
}
set ol_stretch(hover) {}

# the mouse left the drawing area (and is not on one of the overlay strips)
proc ol_hover_leave {w} {
  set in [winfo containing {*}[winfo pointerxy $w]]
  if {$in eq $w || [string match $w.olstrip_* $in] || $::ol_stretch(active)} return
  set ::ol_stretch(hover) {}
  ol_overlay_clear $w
}

proc ol_press {w x y b s} {
  global ol_stretch
  focus $w
  # plain left press (no Shift/Ctrl/Alt) on a rectangle edge while no command is running
  set hit {}
  if {$b == 1 && ($s & 0x0d) == 0 && ([xschem get ui_state] & ~8) == 0} {
    set hit [ol_edge_hit $x $y]
  }
  if {$hit eq {}} {
    xschem callback $w 4 $x $y 0 $b 0 $s
    return
  }
  lassign $hit c i x1 y1 x2 y2 edges
  set z [xschem get zoom]
  array set ol_stretch [list active 1 hover {} c $c i $i rect [list $x1 $y1 $x2 $y2] new [list $x1 $y1 $x2 $y2] \
    edges $edges mx0 [expr {$x * $z - [xschem get xorigin]}] my0 [expr {$y * $z - [xschem get yorigin]}]]
  xschem unselect_all
  ol_overlay_rect $w $x1 $y1 $x2 $y2 $edges 1
  $w configure -cursor [ol_edge_cursor $edges]
}

proc ol_motion {w x y s} {
  global ol_stretch
  if {!$ol_stretch(active)} {
    xschem callback $w 6 $x $y 0 0 0 $s
    return
  }
  set z [xschem get zoom]
  set dx [expr {$x * $z - [xschem get xorigin] - $ol_stretch(mx0)}]
  set dy [expr {$y * $z - [xschem get yorigin] - $ol_stretch(my0)}]
  set g [expr {[info exists ::cadsnap] && [string is double -strict $::cadsnap] && $::cadsnap > 0 ? $::cadsnap : 10}]
  lassign $ol_stretch(rect) x1 y1 x2 y2
  set e $ol_stretch(edges)
  # the grabbed edges move by the mouse offset and land on the grid; the rectangle can't turn over
  if {"l" in $e} { set x1 [expr {min(round(($x1 + $dx) / $g) * $g, $x2 - $g)}] }
  if {"r" in $e} { set x2 [expr {max(round(($x2 + $dx) / $g) * $g, $x1 + $g)}] }
  if {"t" in $e} { set y1 [expr {min(round(($y1 + $dy) / $g) * $g, $y2 - $g)}] }
  if {"b" in $e} { set y2 [expr {max(round(($y2 + $dy) / $g) * $g, $y1 + $g)}] }
  set ol_stretch(new) [list $x1 $y1 $x2 $y2]
  ol_overlay_rect $w $x1 $y1 $x2 $y2 $e 1
}

proc ol_release {w x y b s} {
  global ol_stretch
  if {!($ol_stretch(active) && $b == 1)} {
    xschem callback $w 5 $x $y 0 $b 0 $s
    ol_rects_changed
    return
  }
  set ol_stretch(active) 0
  ol_overlay_clear $w
  $w configure -cursor {}
  lassign $ol_stretch(rect) x1 y1 x2 y2
  lassign $ol_stretch(new) n1 m1 n2 m2
  set c $ol_stretch(c)
  set i $ol_stretch(i)
  if {$ol_stretch(rect) eq $ol_stretch(new)} {
    # a click on an edge selects the rectangle
    xschem select rect $c $i
    return
  }
  ol_resize_rect $c $i $x1 $y1 $x2 $y2 $n1 $m1 $n2 $m2
  # a fresh hover state at the release point
  ol_hover $w $x $y 0
}

# Resize rectangle (c, i) from x1 y1 x2 y2 to n1 m1 n2 m2 (one or two edges moved) with xschem's own
# stretch: only the corners on the moved edges are selected (stretch area select) and moved, which
# records one undo step.
proc ol_resize_rect {c i x1 y1 x2 y2 n1 m1 n2 m2} {
  set moves {}
  set dx [expr {$n1 != $x1 ? $n1 - $x1 : $n2 - $x2}]
  set dy [expr {$m1 != $y1 ? $m1 - $y1 : $m2 - $y2}]
  set gx [expr {$n1 != $x1 ? $x1 : ($n2 != $x2 ? $x2 : {})}]
  set gy [expr {$m1 != $y1 ? $y1 : ($m2 != $y2 ? $y2 : {})}]
  if {$gx ne {} && $gy ne {}} {
    set corners [list $gx $gy]
  } elseif {$gx ne {}} {
    set corners [list $gx $y1 $gx $y2]
    set dy 0
  } else {
    set corners [list $x1 $gy $x2 $gy]
    set dx 0
  }
  set saved [expr {[info exists ::enable_stretch] ? $::enable_stretch : 0}]
  set ::enable_stretch 1
  xschem unselect_all 0
  set e 1e-3
  foreach {px py} $corners {
    xschem select_inside [expr {$px - $e}] [expr {$py - $e}] [expr {$px + $e}] [expr {$py + $e}]
  }
  set ::enable_stretch $saved
  # anything else that happens to have a point on those corners stays where it is
  foreach r [xschem selected_rect] {
    if {$r ne [list $c $i]} { xschem select rect {*}$r clear fast }
  }
  if {[xschem selected_rect] eq [list [list $c $i]]} { xschem move_objects $dx $dy }
  xschem unselect_all
  ol_rects_changed
}

proc ol_bind_stretch {{w .drw}} {
  if {![winfo exists $w]} return
  bind $w <ButtonPress-1> {ol_press %W %x %y %b %s; break}
  bind $w <ButtonRelease-1> {ol_release %W %x %y %b %s; break}
  bind $w <B1-Motion> {ol_motion %W %x %y %s; break}
  if {[string first ol_hover [bind $w <Motion>]] < 0} {
    bind $w <Motion> "+ol_hover %W %x %y %s"
    bind $w <Leave> "+after 50 [list ol_hover_leave $w]"
    bind $w <Enter> "+ol_rects_changed"
    bind $w <KeyRelease> "+ol_rects_changed"
  }
}
ol_bind_stretch

# ---- grid per editor -------------------------------------------------------------------------
# Schematics: snap 10 / grid 20 (pins connect on the 10 grid). Symbol editor: snap 2.5 / grid 10, so
# shapes can be placed precisely (e.g. a circle centered on a triangle tip) while pins - placed by
# the pin dialog - stay on the 10 grid. Re-applied whenever the edited file changes kind.
proc ol_editor_grid {} {
  global ol_grid_kind
  set kind [expr {[ol_in_symbol] ? "symbol" : "schematic"}]
  if {![info exists ol_grid_kind] || $ol_grid_kind ne $kind} {
    set ol_grid_kind $kind
    lassign [expr {$kind eq "symbol" ? {2.5 10} : {10 20}}] snap grid
    catch {xschem set cadsnap $snap; xschem set cadgrid $grid}
    set ::cadsnap $snap
    set ::cadgrid $grid
    # The status bar SNAP/GRID entries are re-applied by xschem when the mouse leaves them, so they
    # must show the current values (a stale "10" would silently undo the fine snap).
    set top [xschem get top_path]
    foreach {e v} [list $top.statusbar.3 $snap $top.statusbar.5 $grid] {
      if {[winfo exists $e]} { $e delete 0 end; $e insert 0 $v }
    }
  }
  after 300 ol_editor_grid
}
ol_editor_grid

# Option probing above uses catch; don't leave those in errorInfo.
set ::errorInfo ""
