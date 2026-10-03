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
| `r` | rectangle | `p` / `Shift+P` | path / polygon |
| `i` | instance | `l` | label |
| `k` | ruler | `Shift+K` | clear rulers |
| `m` | move | `c` | copy |
| `s` | stretch (partial edit) | `q` | properties |
| `u` / `Shift+U` | undo / redo | `Esc` | cancel |
| `f` | fit | `Ctrl+Z` / `Shift+Z` | zoom in / out |
| `Shift+F` | show all levels | `Ctrl+F` | top level only |
| `x` | descend into cell | `b` | return (ascend) |
| `Ctrl+A` | select all | `Ctrl+S` | save |

The **LSW** dock lists the drawing layers: click one to make it the current drawing layer,
untick to hide it; **AV** / **NV** show all / none, **Used** hides layers with no shapes.

## Moving between tools

Both tools have an **OpenLayout** menu that goes through the hub:

- xschem: *Open Layout in KLayout*, *Open Symbol/Schematic*, *Show in Library Manager*,
  *Netlist (hub)*, *Simulate (hub)*
- KLayout: *Open Schematic*, *Open Symbol*, *Show in Library Manager*, *Show LSW*

## Hub

| Key | Action | Key | Action |
|---|---|---|---|
| `Ctrl+N` | new cell view | `Ctrl+Shift+N` | new library |
| `Ctrl+O` | open | `Del` | delete (to trash) |
| `F2` | rename cell | `Ctrl+Shift+C` | copy cell |
| `F7` | netlist | `F8` | simulate |
| `F5` | refresh | `F1` | this page |
