# OpenLayout keys

OpenLayout gives xschem and KLayout Virtuoso-style bindkeys. To keep a tool's own bindings, start
it with `OPENLAYOUT_KEYS=xschem` or `OPENLAYOUT_KEYS=klayout` in the environment.

## Schematic (xschem — like Virtuoso Schematic Editor)

| Key | Action | Key | Action |
|---|---|---|---|
| `i` | create instance | `w` | wire |
| `p` | create pin | `l` | wire name (net label) |
| `c` | copy | `m` | move |
| `s` | stretch | `r` | rotate |
| `q` | properties | `Del` | delete |
| `u` / `Shift+U` | undo / redo | `Esc` | cancel |
| `f` | fit | `z` | zoom box |
| `Ctrl+Z` | zoom in | `Shift+Z` | zoom out |
| `e` | descend | `Ctrl+E` | return |
| `x` | check and save | `Ctrl+S` | save |

xschem also runs in its Cadence-compatibility mode: crosshair cursor, persistent commands
(a command stays active until `Esc`), orthogonal wiring and a cursor that snaps to pins.

## Layout (KLayout — like Virtuoso Layout Suite)

| Key | Action | Key | Action |
|---|---|---|---|
| `r` | rectangle | `p` / `Shift+P` | path (OpenLayout) / polygon |
| `i` | instance | `l` | label |
| `k` | ruler | `Shift+K` | clear rulers |
| `m` | move | `c` | copy |
| `s` | stretch (partial edit) | `q` | properties |
| `u` / `Shift+U` | undo / redo | `Esc` | cancel |
| `f` | fit | `Ctrl+Z` / `Shift+Z` | zoom in / out |
| `Shift+F` | show all levels | `Ctrl+F` | top level only |
| `x` | descend into cell | `b` | return (ascend) |
| `Ctrl+A` | select all | `Ctrl+S` | save |

**Path (`p`)**: click the edge of an existing shape on the current layer to continue that wire -
the path takes the edge's length as its width and starts flush at the edge. Elsewhere it uses the
layer's minimum width (M1-M3 18 nm, M4-M5 24, M6-M7 32, M8-M9 40). Segments are horizontal or
vertical only; click to add points, double-click or `Enter` to finish, `Backspace` removes the last
point, `Esc` cancels. Move, stretch and rulers are also restricted to the axes.

The **LSW** (right side) is the only layer panel. *All layers* / *Used layers* tabs (used = has
shapes in the current cell). Click a layer to make it the current drawing layer, untick to hide it.
**AV** shows every layer; **NV** hides every layer except the current one.

The **Connectivity** panel (right side) compares the layout with its schematic: open nets (with
flight lines in the layout), shorts, and parts missing from / extra to the schematic. Click a net
to highlight its flight lines, double-click to zoom to it.

## Moving between tools

Both tools have an **OpenLayout** menu that goes through the hub:

- xschem: *Open Layout in KLayout*, *Generate Layout from Schematic*, *Open Symbol/Schematic*,
  *Show in Library Manager*,
  *Netlist (hub)*, *Simulate (hub)*
- KLayout: *Generate / Update Layout from Schematic*, *Check Connectivity*, *Open Schematic*,
  *Open Symbol*, *Show in Library Manager*, *Show LSW*, *Show Connectivity*

## Hub

| Key | Action | Key | Action |
|---|---|---|---|
| `Ctrl+N` | new cell view | `Ctrl+Shift+N` | new library |
| `Ctrl+O` | open | `Del` | delete (to trash) |
| `F2` | rename cell | `Ctrl+Shift+C` | copy cell |
| `F7` | netlist | `F8` | simulate |
| `F9` | generate layout from schematic | | |
| `F5` | refresh | `F1` | this page |
