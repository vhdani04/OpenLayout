# Virtuoso Schematic Editor (Composer) style editing for xschem.
# Set OPENLAYOUT_KEYS=xschem in the environment to keep xschem's own bindings.

if {[info exists env(OPENLAYOUT_KEYS)] && $env(OPENLAYOUT_KEYS) eq "xschem"} { return }

# xschem's Cadence compatibility mode: crosshair, persistent commands, orthogonal wiring,
# snap cursor, Ctrl-click-free selection behavior.
set cadence_compat 1
set persistent_command 1
set orthogonal_wiring 1
set snap_cursor 1
set use_cursor_for_selection 1
set draw_crosshair 1
set infix_interface 0
set tabbed_interface 1
set toolbar_visible 1
set toolbar_horiz 1

# replace_key(<key pressed>) <xschem key it acts as>.  Keys already matching Virtuoso are left
# alone: w wire, c copy, m move, q properties, u/U undo/redo, f fit, z zoom box, e/Ctrl+e
# descend/return, Del delete, Esc cancel.
set replace_key(Key-i)     Shift-I    ;# i        create instance
set replace_key(Key-p)     Control-p  ;# p        create pin
set replace_key(Key-l)     Alt-l      ;# l        wire name (net label)
set replace_key(Key-r)     Shift-R    ;# r        rotate
set replace_key(Key-s)     Control-m  ;# s        stretch (move with attached wires)
set replace_key(Key-x)     Control-s  ;# x        check and save
set replace_key(Control-z) Shift-Z    ;# Ctrl+z   zoom in
set replace_key(Shift-Z)   Control-z  ;# Shift+z  zoom out

set ol_keys_help {
Virtuoso-style keys (xschem)
  i          create instance          w        wire
  p          create pin               l        wire name (net label)
  c          copy                     m        move
  s          stretch                  r        rotate
  q          properties               Del      delete
  u / U      undo / redo              Esc      cancel
  f          fit                      z        zoom box
  Ctrl+z     zoom in                  Shift+z  zoom out
  e          descend                  Ctrl+e   return
  x          check and save           Ctrl+s   save
  OpenLayout menu: open layout, show in Library Manager, netlist, simulate
}
