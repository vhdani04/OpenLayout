# OpenLayout additions to the xschem GUI (sourced via tcl_files once the main window exists):
# dark styling of already-built widgets, light toolbar icons, and the OpenLayout menu.

# Robust replacement for xschem's TCP request handler (xschem.tcl: xschem_getdata).
# The original redefines `puts` around each request and writes the reply with `puts`. A request
# that arrives while another one is running (commands like `update` process events) nests inside
# it, and the two `puts` renames collide - leaving xschem without a working `puts` (endless "puts"
# errors). A client that already gave up makes the reply write fail with a background error.
# This version runs one request at a time, always restores `puts`, and ignores dead clients.
proc xschem_getdata {sock} {
  global xschem_server_getdata tclcmd_puts ol_server_busy
  if {$sock ni [chan names]} { return }   ;# already answered and closed
  if {[info exists ol_server_busy] && $ol_server_busy} {
    # Another request is running: try again once it has finished.
    fileevent $sock readable {}
    after 20 [list xschem_getdata $sock]
    return
  }
  while {1} {
    if {[catch {gets $sock line} n] || $n < 0} { break }
    append xschem_server_getdata(line,$sock) $line 

  }
  if {![info exists xschem_server_getdata(line,$sock)]} { set xschem_server_getdata(line,$sock) {} }
  fileevent $sock readable {}             ;# handle each request exactly once
  set ol_server_busy 1
  if {[info commands puts] eq "" && [info commands ::tcl::puts] ne ""} { rename ::tcl::puts puts }
  redef_puts
  uplevel #0 [list catch $xschem_server_getdata(line,$sock) tclcmd_puts]
  catch {rename puts {}}
  catch {rename ::tcl::puts puts}
  set ol_server_busy 0
  catch {puts -nonewline $sock $tclcmd_puts; flush $sock}
  catch {close $sock}
  foreach k {addr line res} { unset -nocomplain xschem_server_getdata($k,$sock) }
}

# Copy every background error into xschem's stderr (the hub logs it to .openlayout/logs/xschem.log)
# before xschem shows its usual dialog. `chan puts` keeps working even if `puts` is redefined.
if {![info exists ol_orig_bgerror]} {
  set ol_orig_bgerror [interp bgerror {}]
  proc ol_bgerror {msg opts} {
    catch {chan puts stderr "xschem background error: [dict get $opts -errorinfo]"; chan flush stderr}
    {*}$::ol_orig_bgerror $msg $opts
  }
  interp bgerror {} ol_bgerror
}

# Nothing to do without a GUI (xschem -x batch netlisting).
if {[info commands winfo] eq ""} { return }

array set ol_ui $ol_theme(ui)
array set ol_canvas $ol_theme(canvas)

# xschem sets its own grey palette in the option database once its GUI starts (xschem.tcl, at
# startupFile priority): put the theme back on top, so the widgets it creates later - dialogs, the
# property forms, its file chooser - come up themed.
ol_theme_options

# c1 blended towards c2 by t (0..1)
proc ol_blend {c1 c2 t} {
  lassign [winfo rgb . $c1] r1 g1 b1
  lassign [winfo rgb . $c2] r2 g2 b2
  format #%02x%02x%02x {*}[lmap a [list $r1 $g1 $b1] b [list $r2 $g2 $b2] {
    expr {round(($a + ($b - $a) * $t) / 257.0)}
  }]
}

# Restyle widgets created before the theme took effect (menubar, toolbar, tabs, status bar).
proc ol_restyle {w} {
  global ol_ui
  set class [winfo class $w]
  # The drawing area is painted by xschem itself; leave it alone.
  if {![string match *.drw $w]} {
    switch -- $class {
      Entry - Text - Listbox - Spinbox { set bg $ol_ui(base) }
      Button { set bg [expr {[string match *.toolbar.* $w] ? $ol_ui(panel) : $ol_ui(border)}] }
      default { set bg $ol_ui(panel) }
    }
    catch {$w configure -background $bg}
    catch {$w configure -foreground $ol_ui(text)}
    catch {$w configure -activebackground $ol_ui(border) -activeforeground $ol_ui(text)}
    catch {$w configure -highlightbackground $ol_ui(panel) -highlightcolor $ol_ui(accent) -highlightthickness 0}
    catch {$w configure -insertbackground $ol_ui(text)}
    catch {$w configure -disabledforeground $ol_ui(dim)}
    catch {$w configure -selectcolor $ol_ui(base)}
    catch {$w configure -troughcolor $ol_ui(base)}
    if {$class in {Button Menubutton}} { catch {$w configure -relief flat -borderwidth 0} }
    if {$class eq "Entry"} { catch {$w configure -relief flat -borderwidth 2} }
  }
  if {$class eq "Menu"} {
    catch {$w configure -activebackground $ol_ui(select) -activeforeground #ffffff -relief flat \
             -activeborderwidth 0 -selectcolor $ol_ui(accent)}
    # the drop-down menus: a padded edge, a step off the toolbar under them (not the menubar itself)
    if {![string match *.menubar $w]} { catch {$w configure -borderwidth 5 -background $::ol_theme(menu)} }
  }
  foreach c [winfo children $w] { ol_restyle $c }
}

# xschem colors a few widgets itself - some from C (the snap / grid fields: PaleGreen, or OrangeRed
# when not the default), some from its procs (the Netlist / Simulate buttons' state). Those widgets'
# commands are wrapped so that the colors they are given map onto the theme's.
proc ol_map_colors {map argv} {
  set out {}
  set n [llength $argv]
  for {set i 0} {$i < $n} {incr i} {
    set a [lindex $argv $i]
    lappend out $a
    if {$a in {-background -bg -activebackground -foreground -fg -activeforeground} && $i + 1 < $n} {
      set v [lindex $argv [incr i]]
      set k [string tolower $v]
      lappend out [expr {[dict exists $map $k] ? [dict get $map $k] : $v}]
    }
  }
  return $out
}

proc ol_wrap_colors {w map} {
  if {![winfo exists $w] || [info commands ::ol_raw$w] ne ""} { return }
  rename $w ::ol_raw$w
  proc $w {args} [format {
    if {[lindex $args 0] in {configure entryconfigure itemconfigure} && [llength $args] > 2} {
      set args [ol_map_colors {%s} $args]
    }
    uplevel 1 [list ::ol_raw%s {*}$args]
  } $map $w]
}

proc ol_theme_status_and_menubar {} {
  global ol_ui simulate_bg
  set top [xschem get top_path]
  # snap / grid fields on the input color. xschem marks a value other than its default (OrangeRed),
  # but OpenLayout sets them per editor (2.5 / 10 in the symbol editor) - not a warning.
  foreach e [list $top.statusbar.3 $top.statusbar.5] {
    if {![winfo exists $e]} continue
    ol_wrap_colors $e [list palegreen $ol_ui(base) orangered $ol_ui(base) black $ol_ui(text)]
    $e configure -foreground $ol_ui(text) -background $ol_ui(base) -relief flat -borderwidth 2 -width 6
  }
  # Netlist / Simulate / Waves: quiet pills, the state colors toned down to the theme's
  set mb $top.menubar
  if {[winfo exists $mb]} {
    set ok [ol_blend $ol_ui(panel) $ol_ui(ok) 0.45]
    set fail [ol_blend $ol_ui(panel) $ol_ui(fail) 0.45]
    set warn [ol_blend $ol_ui(panel) $ol_ui(warn) 0.45]
    ol_wrap_colors $mb [list #888888 $ol_ui(border) green $ok green2 $ok palegreen $ok red $fail \
                          orangered $fail orange $warn yellow $warn]
    set simulate_bg $ol_ui(border)
    foreach label {Netlist Simulate Waves} {
      catch {$mb entryconfigure $label -background $ol_ui(border) -activebackground $ol_ui(select) \
               -foreground $ol_ui(text) -activeforeground #ffffff}
    }
    catch {$mb entryconfigure { - } -label {  }}
  }
}

# The tabs: the current one in the selection blue, the others quiet (xschem: PaleGreen / DarkGreen).
proc set_tab_names {{mod {}}} {
  global tabbed_interface has_x ol_ui
  if {![info exists has_x] || !$tabbed_interface || ![winfo exists .tabs]} return
  set currwin [xschem get current_win_path]
  set currsch [xschem get schname]
  regsub {\.drw} $currwin {} tabname
  if {$tabname eq {}} { set tabname .x0 }
  catch {.tabs configure -background $ol_ui(window)}
  foreach b [winfo children .tabs] {
    if {[winfo class $b] ne "Button"} continue
    if {$b eq ".tabs$tabname"} {
      $b configure -text [file tail $currsch]$mod -background $ol_ui(select) -foreground #ffffff \
        -activebackground $ol_ui(select) -activeforeground #ffffff
      balloon $b $currsch
    } else {
      $b configure -background $ol_ui(panel) -foreground [expr {$b eq ".tabs.add" ? $ol_ui(text) : $ol_ui(dim)}] \
        -activebackground $ol_ui(border) -activeforeground $ol_ui(text)
    }
    $b configure -relief flat -borderwidth 0 -padx 10 -pady 2 -highlightthickness 0
  }
}

# The Layers menu shows the current layer: in its color as text (xschem paints the whole entry).
proc reconfigure_layers_button {{topwin {}}} {
  global ol_ui
  set c [xschem get rectcolor]
  set col [lindex $tctx::colors $c]
  if {$c == 0} { set col $ol_ui(text) }   ;# layer 0 is the background color
  catch {$topwin.menubar entryconfigure Layers -background $ol_ui(panel) -foreground $col \
           -activebackground $ol_ui(select) -activeforeground #ffffff}
}

# xschem's menus show its own keys; OpenLayout's (openlayout_keys.tcl, openlayout_edit.tcl) differ for
# a few. {menu label accelerator}
set ol_menu_keys {
  file  {Save}                                   {X, Ctrl+S}
  file  {Start new Xschem process}               {}
  edit  {Move objects stretching attached wires} {S, Ctrl+M}
  edit  {Rotate selected objects}                {R, Shift+R}
  edit  {Push symbol}                            {}
  view  {Zoom In}                                {Ctrl+Z}
  view  {Zoom Out}                               {Shift+Z}
  tools {Insert line}                            {L in symbols}
  tools {Insert rect}                            {R in symbols}
  tools {Insert polygon}                         {}
  sym   {Place net pin label}                    {L, Alt+L}
}

# index of the menu entry labelled exactly `label`, or -1
proc ol_menu_find {m label} {
  if {![winfo exists $m] || [$m index end] eq "none"} { return -1 }
  for {set i 0} {$i <= [$m index end]} {incr i} {
    if {[$m type $i] ni {separator tearoff} && [$m entrycget $i -label] eq $label} { return $i }
  }
  return -1
}

proc ol_fix_menu_keys {} {
  global ol_menu_keys env
  if {[info exists env(OPENLAYOUT_KEYS)] && $env(OPENLAYOUT_KEYS) eq "xschem"} return
  set mb [xschem get top_path].menubar
  foreach {menu label key} $ol_menu_keys {
    set i [ol_menu_find $mb.$menu $label]
    if {$i >= 0} { $mb.$menu entryconfigure $i -accelerator $key }
  }
  # xschem's Tools and Symbol menus are long flat lists: separators between their groups
  foreach {menu label} {
    tools {Grab screen area}  tools {Join/Trim wires}
    sym {Make symbol from schematic}  sym {Place symbol pin}  sym {Change selected inst. texts to floaters}
    sym {List of nets}
  } {
    set i [ol_menu_find $mb.$menu $label]
    if {$i > 0 && [$mb.$menu type [expr {$i - 1}]] ne "separator"} { $mb.$menu insert $i separator }
  }
  # P opens the pin dialog: list it first in the Symbol menu
  set m $mb.sym
  if {[winfo exists $m] && [ol_menu_find $m "Create Pin…"] < 0} {
    $m insert 0 command -label "Create Pin…" -accelerator P -command {
      set d [xschem get current_win_path]
      lassign [winfo pointerxy $d] x y
      ol_pin_dialog [expr {$x - [winfo rootx $d]}] [expr {$y - [winfo rooty $d]}]
    }
    $m insert 1 separator
  }
}

# xschem's dark-GUI toolbar glyphs are light on an opaque black square: the black becomes transparent
# and each glyph pixel the UI text color blended over the panel by its brightness (keeping the
# antialiasing), so the icons sit on the toolbar like the hub's.
proc ol_lighten_image {img} {
  global ol_ui ol_lightened
  if {[info exists ol_lightened($img)] || [catch {image type $img} t] || $t ne "photo"} { return }
  set ol_lightened($img) 1
  lassign [winfo rgb . $ol_ui(panel)] pr pg pb
  lassign [winfo rgb . $ol_ui(text)] tr tg tb
  set w [image width $img]
  set h [image height $img]
  for {set y 0} {$y < $h} {incr y} {
    for {set x 0} {$x < $w} {incr x} {
      if {[$img transparency get $x $y]} continue
      lassign [$img get $x $y] r g b
      set l [expr {max($r, $g, $b) / 255.0}]
      if {$l < 0.16} {
        $img transparency set $x $y 1
      } else {
        $img put [format #%02x%02x%02x [expr {round(($pr + ($tr - $pr) * $l) / 257.0)}] \
                    [expr {round(($pg + ($tg - $pg) * $l) / 257.0)}] [expr {round(($pb + ($tb - $pb) * $l) / 257.0)}]] \
          -to $x $y
      }
    }
  }
}

# Dark glyphs on a transparent background (xschem's context-menu icons): dark pixels in the text color.
proc ol_tint_dark_image {img} {
  global ol_ui ol_lightened
  if {$img eq "" || [info exists ol_lightened($img)] || [catch {image type $img} t] || $t ne "photo"} { return }
  set ol_lightened($img) 1
  for {set y 0} {$y < [image height $img]} {incr y} {
    for {set x 0} {$x < [image width $img]} {incr x} {
      if {[$img transparency get $x $y]} continue
      lassign [$img get $x $y] r g b
      if {$r + $g + $b < 330} { $img put $ol_ui(text) -to $x $y }
    }
  }
}

# Windows xschem builds on demand with fixed colors of its own are themed as they appear.
proc ol_on_map {w} {
  global ol_ui ol_theme ol_canvas
  switch -- $w {
    .ins {
      # xschem's component browser (Ctrl+I): its preview on the canvas color, not white
      set d $w.center.right
      if {![winfo exists $d]} {
        if {[winfo exists $w] && [incr ::ol_load_wait] < 100} { after 20 [list ol_on_map $w] }
        return
      }
      set ::ol_load_wait 0
      ol_wrap_colors $d [list white $ol_canvas(background) #ffffff $ol_canvas(background)]
      if {[string tolower [$d cget -background]] in {white #ffffff}} { $d configure -background white }
    }
    .ctxmenu {
      # the right-click menu: menu colors, light icons, a 1 px border; Insert symbol opens Add Instance
      $w configure -background $ol_ui(border) -padx 1 -pady 1
      foreach b [winfo children $w] {
        if {[winfo class $b] ne "Button"} continue
        $b configure -background $ol_theme(menu) -foreground $ol_ui(text) -activebackground $ol_ui(select) \
          -activeforeground #ffffff -relief flat -borderwidth 0 -padx 10 -pady 3 -font $ol_theme(font)
        catch {ol_tint_dark_image [$b cget -image]}
      }
      if {[winfo exists $w.b1]} {
        $w.b1 configure -command {set tctx::retval 0; destroy .ctxmenu; after idle ol_instance_browser}
      }
    }
    .load {
      # xschem's file chooser: the preview on the canvas color, not white. It is mapped before its
      # panes are built: wait for the preview frame.
      set d $w.l.paneright.draw
      if {![winfo exists $d]} {
        if {[winfo exists $w] && [incr ::ol_load_wait] < 100} { after 20 [list ol_on_map $w] }
        return
      }
      set ::ol_load_wait 0
      ol_wrap_colors $d [list white $ol_canvas(background) #ffffff $ol_canvas(background)]
      if {[string tolower [$d cget -background]] in {white #ffffff}} { $d configure -background white }
    }
  }
}
bind Toplevel <Map> {+ol_on_map %W}
bind Dialog <Map> {+ol_on_map %W}   ;# xschem's dialogs (.load, .dialog) are of class Dialog

# a dialog's default button: the accent color, like the hub's
proc ol_primary {b} {
  global ol_ui
  $b configure -background $ol_ui(accent) -foreground #0e1014 -activebackground $ol_ui(select) -activeforeground #ffffff
}
# the file chooser's highlighted directories (xschem: dark green / red on a light list)
foreach k [array names dircolor] { set dircolor($k) $ol_ui(accent) }

proc ol_lighten_toolbar {w} {
  if {"-image" in [lmap o [$w configure] {lindex $o 0}]} {
    set img [$w cget -image]
    if {$img ne ""} { ol_lighten_image $img }
  }
  foreach c [winfo children $w] { ol_lighten_toolbar $c }
}

# Cross-tool commands go through the OpenLayout hub (it starts KLayout if needed).
proc ol_hubcmd {cmd args} {
  set path [xschem get schname]
  if {[catch {exec openlayout hubcmd $cmd $path {*}$args} msg]} {
    tk_messageBox -parent [xschem get topwindow] -icon warning -title OpenLayout -message $msg
  }
}

proc ol_show_keys {} {
  global ol_keys_help ol_theme
  set w .ol_keys
  if {[winfo exists $w]} { raise $w; return }
  toplevel $w
  wm title $w "OpenLayout keys"
  text $w.t -width 78 -height 13 -font $ol_theme(mono) -relief flat -borderwidth 12 -wrap none
  $w.t insert end [string trim $ol_keys_help]
  $w.t configure -state disabled
  pack $w.t -fill both -expand 1
}

# A symbol from the current schematic's pins (asks before replacing a symbol).
proc ol_make_symbol {} {
  set sch [xschem get schname]
  set parent [xschem get topwindow]
  if {[file extension $sch] ne ".sch"} {
    tk_messageBox -parent $parent -icon info -title OpenLayout -message "Open the cell's schematic first."
    return
  }
  set sym "[file rootname $sch].sym"
  set args {}
  if {[file exists $sym]} {
    if {[tk_messageBox -parent $parent -type yesno -icon question -title OpenLayout \
           -message "[file tail $sym] exists. Replace it with a symbol generated from the schematic?"] ne "yes"} {
      return
    }
    set args --force
  }
  if {[catch {exec openlayout make-symbol $sch {*}$args} msg]} {
    tk_messageBox -parent $parent -icon warning -title OpenLayout -message $msg
    return
  }
  xschem load_new_window $sym
}

proc ol_add_menu {} {
  set top [xschem get top_path]
  set mb $top.menubar
  if {[winfo exists $mb.openlayout]} { return }
  menu $mb.openlayout -tearoff 0
  if {[catch {$mb insert Help cascade -label OpenLayout -menu $mb.openlayout}]} {
    $mb add cascade -label OpenLayout -menu $mb.openlayout
  }
  set m $mb.openlayout
  $m add command -label "Open Layout in KLayout" -command {ol_hubcmd open layout}
  $m add command -label "Open Symbol" -command {ol_hubcmd open symbol}
  $m add command -label "Generate Symbol from Schematic" -command ol_make_symbol
  $m add command -label "Open Schematic" -command {ol_hubcmd open schematic}
  $m add command -label "Show in Library Manager" -command {ol_hubcmd select}
  $m add separator
  $m add command -label "Netlist (hub)" -command {ol_hubcmd netlist}
  $m add command -label "Simulate (hub)" -command {ol_hubcmd simulate}
  $m add command -label "OLSim (hub)" -command {ol_hubcmd olsim}
  $m add command -label "Waveform Viewer (hub)" -command {ol_hubcmd waves}
  $m add separator
  $m add command -label "Keyboard Shortcuts…" -command ol_show_keys
}

# xschem restores the last window size from ~/.xschem/geometry; a collapsed size (e.g. saved by a
# session without a window manager) would leave an unusable sliver - fall back to a normal window.
proc ol_sane_geometry {} {
  set top [xschem get top_path]
  if {$top eq ""} { set top . }
  if {[regexp {^(\d+)x(\d+)} [wm geometry $top] -> w h] && ($w < 400 || $h < 300)} {
    wm geometry $top 1280x800+80+60
  }
}

ol_add_menu
# xschem also restores a per-file size whenever it loads a schematic: re-check after startup and
# whenever the main window is resized.
after 300 ol_sane_geometry
bind [expr {[xschem get top_path] eq "" ? "." : [xschem get top_path]}] <Configure>   {+if {"%W" eq [winfo toplevel %W]} {after idle ol_sane_geometry}}
ol_restyle [xschem get top_path].
if {[winfo exists [xschem get top_path].toolbar]} { ol_lighten_toolbar [xschem get top_path].toolbar }
ol_theme_status_and_menubar
ol_fix_menu_keys
catch {reconfigure_layers_button [xschem get top_path]}
catch {set_tab_names}

# The styling above probes options with catch; don't leave those in errorInfo.
set ::errorInfo ""
