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

# Restyle widgets created before the option database took effect (menubar, toolbar, status bar).
proc ol_restyle {w} {
  global ol_ui
  switch -- [winfo class $w] {
    Entry - Text - Listbox - Spinbox { set bg $ol_ui(base) }
    default { set bg $ol_ui(panel) }
  }
  # The drawing area is painted by xschem itself; leave it alone.
  if {![string match *.drw $w]} {
    catch {$w configure -background $bg}
    catch {$w configure -foreground $ol_ui(text)}
    catch {$w configure -activebackground $ol_ui(border) -activeforeground $ol_ui(text)}
    catch {$w configure -highlightbackground $ol_ui(panel) -highlightcolor $ol_ui(accent)}
    catch {$w configure -insertbackground $ol_ui(text)}
    catch {$w configure -disabledforeground $ol_ui(dim)}
    catch {$w configure -selectcolor $ol_ui(base)}
  }
  if {[winfo class $w] eq "Menu"} {
    catch {$w configure -activebackground $ol_ui(select) -activeforeground #ffffff -relief flat}
  }
  foreach c [winfo children $w] { ol_restyle $c }
}

# xschem's toolbar glyphs are dark; repaint their dark pixels in the UI text color.
proc ol_lighten_image {img} {
  global ol_ui ol_lightened
  if {[info exists ol_lightened($img)] || [catch {image type $img} t] || $t ne "photo"} { return }
  set ol_lightened($img) 1
  set w [image width $img]
  set h [image height $img]
  for {set y 0} {$y < $h} {incr y} {
    for {set x 0} {$x < $w} {incr x} {
      if {[$img transparency get $x $y]} continue
      lassign [$img get $x $y] r g b
      if {$r + $g + $b < 330} { $img put $ol_ui(text) -to $x $y }
    }
  }
}

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
  text $w.t -width 70 -height 18 -font $ol_theme(mono) -relief flat -borderwidth 10
  $w.t insert end [string trim $ol_keys_help]
  $w.t configure -state disabled
  pack $w.t -fill both -expand 1
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
  $m add command -label "Generate Layout from Schematic" -command {ol_hubcmd generate}
  $m add command -label "Open Symbol" -command {ol_hubcmd open symbol}
  $m add command -label "Open Schematic" -command {ol_hubcmd open schematic}
  $m add command -label "Show in Library Manager" -command {ol_hubcmd select}
  $m add separator
  $m add command -label "Netlist (hub)" -command {ol_hubcmd netlist}
  $m add command -label "Simulate (hub)" -command {ol_hubcmd simulate}
  $m add separator
  $m add command -label "Virtuoso Keys…" -command ol_show_keys
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

# The styling above probes options with catch; don't leave those in errorInfo.
set ::errorInfo ""
