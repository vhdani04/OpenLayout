# OpenLayout keys

OpenLayout gives xschem and KLayout Virtuoso-style bindkeys. To keep a tool's own bindings, start
it with `OPENLAYOUT_KEYS=xschem` or `OPENLAYOUT_KEYS=klayout` in the environment.

## Schematic (xschem — like Virtuoso Schematic Editor)

| Key | Action | Key | Action |
|---|---|---|---|
| `i` | create instance | `w` | wire |
| `p` | pin: name(s) + direction dialog | `l` | wire name (net label) |
| `c` | copy | `m` | move |
| `s` | stretch | `r` | rotate |
| `q` | properties form | `Del` | delete |
| `u` / `Shift+U` | undo / redo | `Esc` | cancel |
| `f` | fit | `z` | zoom box |
| `Ctrl+Z` | zoom in | `Shift+Z` | zoom out |
| `e` | descend | `Ctrl+E` | return |
| `x` | check and save | `Ctrl+S` | save |

**Symbol editor** (editing a `.sym`): `l` draws a line (any angle), `r` a rectangle, `p` adds
symbol pins. The symbol editor snaps to 2.5 (grid 10) so shapes can be placed precisely, while the
pin dialog keeps pins on the 10 grid; schematics snap to 10 (grid 20).

**Symbols from schematics** (Virtuoso *From Cellview*): New Cell View → symbol, the hub's *Generate
Symbol*, `openlayout make-symbol cell.sch` or xschem's *OpenLayout ▸ Generate Symbol from
Schematic* build the symbol from the schematic's pins - inputs left, outputs right, supplies
(VDD…/VSS…) top and bottom, other input-outputs right - with a green body, `@name` / `@symname`
labels and a red outline selection box around the body and pins (pins on its edges). As in
Virtuoso, the selection box only shows in the symbol editor: placed instances don't draw it, but it
sets the area where the instance is hovered and selected (`hide=instance` on the box; needs the
OpenLayout xschem build, see `setup/patches`). A symbol without a schematic starts as an empty body
with the selection box.

`q` (or double-click) opens a form with one field per property - instance name, then the symbol's
parameters; *Add property* adds a new one and *Text Editor…* opens xschem's raw editor. With several
instances selected, only the fields you change are applied to all of them.

`p` asks for the pin name(s) (several separated by spaces) and the direction (input, output,
input-output); the pins then follow the mouse until you click to place them.

To resize a rectangle (such as the symbol's red selection box), point at one of its edges: the edge
lights up. Press and drag it: a dashed outline shows the new size, and on release the rectangle
snaps to it (the edge lands on the snap grid; `u` undoes it). A corner moves both of its edges.
Pressing on a pin still moves the pin.

xschem also runs in its Cadence-compatibility mode: persistent commands (a command stays active
until `Esc`), orthogonal wiring (wires only; lines can be drawn at any angle) and a cursor that
snaps to pins. The mouse cursor is the normal pointer.

## Layout (KLayout — like Virtuoso Layout Suite)

| Key | Action | Key | Action |
|---|---|---|---|
| `r` | rectangle | `p` / `Shift+P` | path (OpenLayout) / polygon |
| `i` | instance | `l` | label |
| `k` | ruler | `Shift+K` | clear rulers |
| `m` | move | `c` | copy |
| `s` | stretch | `q` | properties |
| `a` | align | | |
| `u` / `Shift+U` | undo / redo | `Esc` | cancel |
| `f` | fit | `Ctrl+Z` / `Shift+Z` | zoom in / out |
| `Shift+F` | show all levels | `Ctrl+F` | top level only |
| `x` | descend into cell | `b` | return (ascend) |
| `Ctrl+A` | select all | `Ctrl+S` | save |

**Path (`p`)**: click the edge of an existing shape on the current layer to continue that wire -
the path takes the edge's length as its width and starts flush at the edge. Elsewhere it uses the
layer's minimum width (M1-M3 18 nm, M4-M5 24, M6-M7 32, M8-M9 40). While drawing, the segment snaps onto the facing edge of the next shape on
the same layer as soon as the path's front reaches it (highlighted in blue); clicking while snapped places the path flush against it and
finishes. The preview is drawn in the layer's own texture.
Segments are horizontal or
vertical only; click to add points, double-click or `Enter` to finish, `Backspace` removes the last
point, `Esc` cancels. Move, stretch and rulers are also restricted to the axes.

**Moving** works like Virtuoso: press on a transistor, instance or shape and drag it - it follows
the mouse and drops where you release the button (`u` undoes it). Pressing on empty space and
dragging draws a selection box; a click selects. Over a selection the cursor turns into the
four-way move arrow. Or point at it (or at the selection), press `m`, and click where it should go
(the first click places it). After a move the editor is back in select mode. Clicking selects the
top-level object - a whole transistor, not a shape inside it (descend with `x` to edit inside a
cell).

**Stretch (`s`)**: point at an edge (or a corner) of a shape and press `s` - it follows the mouse and a
click places it; afterwards the editor is back in select mode. In stretch mode (toolbar *Partial*)
an edge can also be dragged and is placed where the button is released.

**Align (`a`)**: select what should move (or just point at it), press `a`, click an edge of it (the
reference), then click a parallel edge of anything else: the selection moves so the two edges line
up - sideways for vertical edges, up/down for horizontal ones. Edges are instance outlines and
shapes, also inside instances (e.g. a transistor's diffusion or gate; near an outline the outline
wins). The edge under the mouse is highlighted; `Esc` or a right click cancels; `u` undoes.

**Custom standard cells.** *OpenLayout ▸ Standard-Cell Frame…* draws the cell template at the origin
of the open cell, as plain shapes in the cell itself (no extra hierarchy level - every shape can be
selected and edited): a 7.5-track frame (270 nm high, a whole number of 54 nm gate pitches wide)
with the boundary, n-well / implant split, VT layer, all ten fin rows, the VDD / VSS rails on M1
(labelled as pins), LIG rails, gate cuts and dummy gates at both cell edges - like the ASAP7 library
cells. Running it again (another width or VT) redraws the frame's shapes; shapes you added yourself
are kept. As the frame covers the whole cell, a click picks what lies on top of it - a transistor,
a wire - and only an empty spot picks a frame shape. A drag that starts on an unselected frame
shape draws a selection box; a selected frame shape drags like any shape (to move the whole frame,
box-select it).

Transistors go in with *Standard-cell row* on and at y = 0: nMOS sit on the bottom fins, pMOS on
the top fins, and an nMOS and a pMOS in the same column share one gate. Each transistor has its
gate contact - a LIG strap over its fingers at mid-cell, like the library's - which can be
switched off in its properties (`q`, *Gate contact*; e.g. on one of an nMOS/pMOS pair). Row
devices have at most 3 fins (use fingers for more). The transistor PCells draw no GCUT: where a
gate is cut depends on the cell, so draw GCUT where yours needs it (the frame already cuts at the
rails and at its edge dummy gates).

**Generating from the schematic** puts the cell's boundary corner at (0, 0): a transistor-level cell
gets the frame (sized for its transistors chained per row) unless it has one already, a cell of
only sub-cells a plain boundary. Generated parts are parked below the cell, never overlapping: the
pMOS in a row at y = -0.54, the nMOS under them at y = -0.81 (other cells further down), left to
right; parts added by a later update go after the ones already parked. Drag a transistor into the
cell and it snaps onto its row (y = 0) and the 54 nm gate grid - and chains to a neighbour. An older
layout with free-standing transistors gets the frame on its next update, its transistors converted
to row devices and parked.

The **x and y axes** through the origin are drawn in every layout view (*OpenLayout ▸ Show Axes*
switches them off and on).

**Chaining** (shared diffusion, like Virtuoso's abutment): drop a transistor next to another of the
same type and row - touching, or overlapping by up to a gate pitch - and it snaps into the chain:
the dummy gates between them go and the diffusion runs through. With a schematic link it only
chains when the touching source/drain nets match, flipping the dropped transistor if that makes
them match. Moving a transistor away again restores its dummy gates. *OpenLayout ▸ Chain Selected
Transistors* packs the selection into chains left to right. In a transistor's properties (`q`)
*Contact on the shared left/right diffusion* can be switched off for the inner node of a series
stack (as in the library's NAND2).

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
