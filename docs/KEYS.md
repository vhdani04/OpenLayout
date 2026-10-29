# OpenLayout keys

OpenLayout gives xschem and KLayout Virtuoso-style key bindings. To keep a tool's own bindings, start
it with `OPENLAYOUT_KEYS=xschem` or `OPENLAYOUT_KEYS=klayout` in the environment.

## Schematic (xschem)

| Key | Action | Key | Action |
|---|---|---|---|
| `i` / `Insert` | add instance (browser) | `w` | wire |
| `p` | pin: name(s) + direction dialog | `l` | wire name (net label) |
| `c` | copy | `m` | move |
| `s` | stretch | `r` | rotate |
| `q` | properties form | `Del` | delete |
| `u` / `Shift+U` | undo / redo | `Esc` | cancel |
| `f` | fit | `z` | zoom box |
| `Ctrl+Z` | zoom in | `Shift+Z` | zoom out |
| `e` | descend | `Ctrl+E` | return |
| `x` | save | `Ctrl+S` | save (no prompt) |

**Add Instance** (`i`, `Insert`, *Tools ▸ Add Instance…*, the toolbar's symbol button, or *Insert
symbol* in the right-click menu): a browser laid out like the hub's Library Manager - the
workarea's libraries (design libraries first, the PDK's dimmed) and a *Basic* library of xschem's
own devices (pins, labels, supplies, sources); the selected library's cells that have a symbol,
with a filter (a substring, or a glob with `*` / `?`; the arrow keys step through the matches);
and a preview of the symbol with its type and pins. Double-click, `Enter` or *Place* puts the
symbol on the mouse; *Keep open* leaves the browser up for the next one; `Esc` closes it.

The menus show OpenLayout's keys where they differ from xschem's (e.g. *Save* `X, Ctrl+S`, *Zoom In*
`Ctrl+Z`), and *Symbol ▸ Create Pin…* opens the pin dialog. xschem's dialogs, file chooser,
right-click menu, tabs and status bar follow the same dark theme as the hub and KLayout
(`share/theme/openlayout.json`).

**Symbol editor** (editing a `.sym`): `l` draws a line (any angle), `r` a rectangle, `p` adds
symbol pins. The symbol editor snaps to 2.5 (grid 10) so shapes can be placed precisely, while the
pin dialog keeps pins on the 10 grid; schematics snap to 10 (grid 20).

**Symbols from schematics**: New Cell View → symbol, the hub's *Generate
Symbol*, `openlayout make-symbol cell.sch` or xschem's *OpenLayout ▸ Generate Symbol from
Schematic* build the symbol from the schematic's pins - inputs left, outputs right, supplies
(VDD…/VSS…) top and bottom, other input-outputs right - with a green body, `@name` / `@symname`
labels and a red outline selection box around the body and pins (pins on its edges). The
selection box only shows in the symbol editor: placed instances don't draw it, but it
sets the area where the instance is hovered and selected (`hide=instance` on the box; needs the
OpenLayout xschem build, see `setup/patches`). A symbol without a schematic starts as an empty body
with the selection box.

`q` (or double-click) opens a form with one field per property - instance name, then the symbol's
parameters; *Add property* adds a new one and *Text Editor…* opens xschem's raw editor. With several
instances selected, only the fields you change are applied to all of them.

`p` asks for the pin name(s) (several separated by spaces) and the direction (input, output,
input-output). The pins are placed one at a time: the first follows the mouse until you click, then
the next one follows (names in the order typed; an expanded bus MSB first). Nothing stays selected
after a click. `Esc` discards the pin being placed and the ones still waiting; the pins already
placed stay. A name used before gets a second pin of its own (the old one stays where it is).
Pin labels stay horizontal however a pin is rotated or flipped: on a pin pointing up or down the
label sits centred above or below it (OpenLayout's ipin / opin / iopin symbols and an xschem patch,
`keep_horizontal=true` on a symbol text).

**Buses**: a pin named `WL[1:0]` (xschem's bus syntax; `WL<1:0>` is accepted and written as
`WL[1:0]`) is one bus pin. Wires labelled `WL[1]` and `WL[0]` connect to its bits by name - the
pin itself needs no wire - and the netlist has one port per bit (`.subckt cell WL[1] WL[0] ...`).
With *Expand buses into one pin per bit* ticked, `WL[1:0]` places two pins, `WL[1]` and `WL[0]`.
Generated symbols keep the bus pin; Generate Layout makes a layout pin per bit; New Testbench gives
each bit its own vector column (and each output bit its own load).

To resize a rectangle (such as the symbol's red selection box), point at one of its edges: the edge
lights up. Press and drag it: a dashed outline shows the new size, and on release the rectangle
snaps to it (the edge lands on the snap grid; `u` undoes it). A corner moves both of its edges.
Pressing on a pin still moves the pin.

**Ground is VSS** (the ASAP7 convention, as in the standard cells and the layout's VSS rail): the
ground symbol (`gnd.sym`) names its net VSS - a global net like VDD - instead of xschem's `0`.
For simulation, OpenLayout's netlisting adds one 0 V source tying VSS to SPICE's node 0
(`V_OL_VSS VSS 0 0`), so testbenches work unchanged. Older schematics with the stock ground
(`lab=0`) still match the layout: the schematic link treats `0` / `GND` as VSS. The VDD / VSS a cell
uses are supply pins of its layout - the frame's rails - so the connectivity check also checks the
supply connections.

xschem also runs in its `cadence_compat` mode: persistent commands (a command stays active
until `Esc`), orthogonal wiring (wires only; lines can be drawn at any angle) and a cursor that
snaps to pins. The mouse cursor is the normal pointer.

## Layout (KLayout)

| Key | Action | Key | Action |
|---|---|---|---|
| `r` | rectangle | `p` / `Shift+P` | path (OpenLayout) / polygon |
| `i` | instance | `l` | label |
| `k` | ruler | `Shift+K` | clear rulers |
| `m` | move | `c` | copy |
| `s` | stretch | `q` | properties |
| `a` | align | `o` | create via |
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
The path is drawn along its centre line, its end flush with the cursor; a click is a corner,
centred on the click, and the last click (double-click / `Enter`) is the end. **Alignment guides**:
when the path's leading edge lines up with a corner or an edge centre of a nearby
shape on the same layer, the end snaps to it and a dashed orange line joins that point to the
nearest corner of the leading edge - lined up with the centre of a shape's edge, the next corner
turns the path into that shape centred on it.

**Moving**: with something selected, the cursor is the four-way move arrow over
it: press and drag to move it, release to drop it (`u` undoes). A press-drag anywhere else draws a
selection box; a click selects. **Move (`m`)**: the selection - or, with nothing selected, the object
under the mouse - follows the mouse from where `m` was pressed (infix); a click places it. The
command then repeats: click the next object (it follows from that click) and click to place it,
until `Esc` or a right click. Clicking selects the top-level object - a whole transistor, not a
shape inside it (descend with `x` to edit inside a cell).

**Pins and their labels**: selecting a pin shape (a metal's pin purpose) selects its label too - the
text on that metal's pin or label purpose lying on it - so moving, copying, deleting or mirroring
the pin takes the label along. A label clicked on its own moves by itself.

**Stretch (`s`)**: point at an edge (or a corner) of a shape and press `s` - it follows the mouse and a
click places it; afterwards the editor is back in select mode. In stretch mode (toolbar *Partial*) a
pressed edge follows the mouse the same way until a click places it.

**Align (`a`)**: select what should move (or just point at it), press `a`, click an edge of it (the
reference), then click a parallel edge of anything else: the selection moves so the two edges line
up - sideways for vertical edges, up/down for horizontal ones. Edges are instance outlines and
shapes, also inside instances (e.g. a transistor's diffusion or gate; near an outline the outline
wins). The edge under the mouse is highlighted; `Esc` or a right click cancels; `u` undoes.

**Vias (`o`)**: *Create Via* lists the ASAP7 vias with their cut sizes - V0 from LISD or LIG up to
M1 (18 x 18 nm), V1 and V2 (18 x 18), V3 (18 x 24), V4 (24 x 24), V5 (24 x 32), V6 and V7
(32 x 32), V8 (40 x 40) - followed by via stacks (e.g. LIG -> M2 = V0 + V1), with rows and columns
for arrays. After *Place* the via follows the mouse, centred on it, and every click drops one; `Esc`
or a right click finishes. Metal pads are the tech LEF's default vias (VIA12 ... VIA89), running
along each metal's direction. A placed via is an OpenLayout_ASAP7 `via` PCell: `q` changes its
via, rows and columns.

**Pins (*OpenLayout ▸ Place Pins…*)**: places the pins of whole buses at once (the cell needs its
schematic link, from *Generate / Update Layout from Schematic*). Tick the buses, then choose where:
*on the net's terminals* (the sub-cell pin nearest the chosen side - connected, no wire needed),
*on the ends of the net's wires* (route the bus out first), or *along a side of the cell*, aligned
with the terminals or evenly spaced at a pitch from the left / bottom (on M4 - M7 onto the SADP
tracks). Pins already there are moved; `u` undoes the whole placement.

**Custom standard cells.** *OpenLayout ▸ Standard-Cell Frame…* draws the cell template at the origin
of the open cell, as plain shapes in the cell itself (no extra hierarchy level - every shape can be
selected and edited): a 7.5-track frame (270 nm high, a whole number of 54 nm gate pitches wide)
with the boundary, n-well / implant split, VT layer, all ten fin rows, the VDD / VSS rails on M1
(labelled as pins), LIG rails under them (joined to M1 by V0 at every gate pitch), gate cuts and dummy gates at both cell edges - like the ASAP7 library
cells. The window builds any stack of N and P regions: its rows, listed top to bottom, are each an
N or a P region (135 nm, five fin tracks) with their own width in gate pitches - *Add row*, *Remove*,
*Move up* / *Move down*, and *All gate pitches equal* to keep them the same width (the boundary
steps where they differ). The rails are placed automatically: each outer edge carries its region's
supply, two regions of the same type share a rail, and an N and a P region pair up across a gate
boundary (no rail, their gates shared), so that every region reaches its supply - an N / P / N
stack gets VSS, a gate boundary, VDD between the P and the top N, and VSS on top. Each row's *Rail
above* (and the bottom edge's) can be set to VDD / VSS / none instead; the preview draws the stack
and its rails, and a region left without its supply rail is warned about. Running it again redraws
the frame's shapes (it opens on the cell's current stack); shapes you added yourself are kept. As the frame covers the whole cell, a click picks what lies on top of it - the topmost wire,
contact or gate first, then a transistor - and only an empty spot picks a frame shape; the hover
highlight shows the same object a click takes. **Click the same spot again** for the next object
underneath, down through the stack to the frame's own shapes (its GCUT, fins, rails): the status bar
says which one ("2 of 4 under the mouse: GCUT shape (frame)"). To pick shapes under transistors
directly, switch instances off in the **Select** window, or lock the layers you don't want (see the
LSW below). A drag that starts on an unselected frame
shape draws a selection box; a selected frame shape drags like any shape (to move the whole frame,
box-select it).

Transistors go in with *Standard-cell row* on and at y = 0: nMOS sit on the bottom fins, pMOS on
the top fins, and an nMOS and a pMOS in the same column share one gate. A free-standing transistor dragged into the frame becomes a row transistor and snaps onto the row, so its fins sit on the frame's whatever its fin count; dropped outside the frame it snaps to the 54 nm gate grid with its fins on the 27 nm fin grid. The transistors have no
gate contact: put one wherever the routing wants it along the gate - LIG over the gate (and a V0
to M1), or a LIG-M1 via from `o`. Row devices have at most 3 fins (use fingers for more). The transistor PCells draw no GCUT: where a
gate is cut depends on the cell, so draw GCUT where yours needs it (the frame already cuts at the
rails and at its edge dummy gates).

**More rows (e.g. an N/P/N cell).** Stretch the frame's boundary over the extra rows and the frame
covers them: a row transistor's origin snaps to the nearest half-row line (a multiple of 135 nm -
5 fin pitches - so its fins stay on the fin grid), and a free-standing transistor dropped above the
first row becomes a row transistor where it was dropped (e.g. the nMOS row on top of an N/P/N cell).
A row flipped top to bottom (*Mirror over X axis*) has its origin on the rail line - an nMOS row
under a VSS rail at 405 nm sits at y = 405 nm, its fins next to that rail - and chains with
transistors flipped the same way. Mirroring or rotating transistors refreshes their chains (dummy
gates) in the same undo step.

**Generating from the schematic** (KLayout only: *OpenLayout ▸ Generate / Update Layout from
Schematic*, or *Update from Schematic* in the Connectivity panel) first opens the **Generate Layout**
form, with two tabs. **Instances**: one row per kind of instance - a sub-cell, or a transistor model
with its fins and fingers - and its count (an array of 32 bit cells is one row, *b2SRAMsbc x32*).
Untick a row to leave all of those out; double-click it for a window listing them one by one, to
place only some (the row then shows a partial tick). Every instance starts ticked; left-out
instances are not placed, and ones already in the layout are left as they are. **Pins**: one row
per pin (the ports, then the supplies the
cell uses) with *Create*, direction, metal layer and size; *Layer for the checked pins* + *Apply*
sets them all at once. Pins the layout has already start unchecked, and so do VDD / VSS when the
standard-cell frame's rails provide them. Both tabs (and the instance window) have *Select All* /
*Deselect All*. A pin is a square of its layer's minimum width (18 nm on
M1-M3, 24 on M4/M5, 32 on M6/M7, 40 on M8/M9) on the pin purpose, with the label - no drawing shape
under it. The form also offers the standard-cell frame / boundary when the cell has none.
It puts the cell's boundary corner at (0, 0): a transistor-level cell
gets the frame (sized for its transistors chained per row) unless it has one already, a cell of
only sub-cells a plain boundary. Generated parts are parked below the cell, never overlapping: the
pMOS in a row at y = -0.54, the nMOS under them at y = -0.81 (other cells further down), left to
right; parts added by a later update go after the ones already parked. Drag a transistor into the
cell and it snaps onto its row (y = 0, or the nearest half-row line) and the 54 nm gate grid - and
chains to a neighbour. An older
layout with free-standing transistors gets the frame on its next update, its transistors converted
to row devices and parked.

The **x and y axes** through the origin are drawn in every layout view (*OpenLayout ▸ Show Axes*
switches them off and on).

**Layer grid** (*OpenLayout ▸ Show Layer Grid…*, or the same button on the toolbar): a window with
one checkbox per layer; a ticked layer's tracks - where it may be routed - are drawn over the layout
as thin lines, one colour per layer, solid where a DRC rule puts the wires there and dashed where
they are only the place-and-route tracks of the tech LEF. The lines are markers, not shapes (nothing
to select, nothing saved); they follow zoom and pan, and a layer whose tracks would be less than 5
pixels apart waits until the view is zoomed in (the window says which). *Clear* (or *OpenLayout ▸
Clear Layer Grid*) removes them. The grids are in the coordinates of the cell being edited - the DRC
checks that cell flat from its origin - and are read from the PDK files each session, not typed into
OpenLayout (klayout/python/openlayout_kl/layer_grid.py; hover a layer in the window for its source):

| Layer | Lines | Track centrelines | Min width (nm) | Source |
|---|---|---|---|---|
| Fin | horizontal | y = 13.5 + 27k nm | 7 | DRC deck FIN.S.1 / FIN.W.1 (DRM: exact fin pitch 27 nm) |
| Gate | vertical | x = 27 + 54k nm | 20 | DRC deck GATE.S.1 / GATE.W.1 (DRM: exact gate pitch 54 nm) |
| M1 | vertical, dashed | x = 0 + 36k nm | 18 | tech LEF M1 PITCH / OFFSET (no DRM grid rule) |
| M2 | horizontal, dashed | y = 45, 81, ... 225 nm (36 nm apart) in each 270 nm row | 18 | tech LEF M2 LEF58_PITCH 36 FIRSTLASTPITCH 45; row height from the library LEF's SITE |
| M3 | vertical, dashed | x = 0 + 36k nm | 18 | tech LEF M3 PITCH / OFFSET (no DRM grid rule) |
| M4 | horizontal | y = 12 + 48k nm | 24 | DRC deck M4.AUX.2 (DRM: minimum-width wires on tracks 2 x 24 nm apart, offset 0) |
| M5 | vertical | x = 12 + 48k nm | 24 | DRC deck M5.AUX.2 |
| M6 | horizontal | y = 16 + 64k nm | 32 | DRC deck M6.AUX.2 |
| M7 | vertical | x = 16 + 64k nm | 32 | DRC deck M7.AUX.2 |
| M8, M9 | - | **not drawn** | 40 | tech LEF: PITCH 80 nm but no OFFSET, no DRM grid rule - the positions are not defined |

"DRC deck" is pdk/asap7/klayout/drc/asap7.drc (written from the DRM r1p7), "tech LEF" the library's
techlef_misc/asap7_tech_1x_201209.lef. Where the two disagree the DRC rule wins: the LEF has M4
OFFSET 3 nm and M5 OFFSET 0 (the DRC: 12 nm, the wire centre) and no OFFSET for M6 / M7. The DRM
lets the M4-M7 grid be shifted by a multiple of 12 / 16 nm through an environment variable;
OpenLayout's deck uses the default, 0. Vias have no grid of their own: a via sits where the tracks of
the two metals cross. Checked against the library (tests/klayout/test_layer_grid.py): every fin,
gate and minimum-width M2 piece of the 212 cells of the 7.5T R library lies on its line. M1 is the
exception: the cells draw M1 where their pins need it, most of it on the gate lines (x = 27 + 54k
nm), not on the LEF's M1 router tracks.

**Connecting to the rails**: run a source's LISD down (or up) into the LIG rail - LIG and LISD
connect where they overlap, as in the ASAP7 cells - and the rail's V0s take it to the M1 VDD / VSS.
The same rule means LIG must stay 14 nm clear of LISD wherever they should not connect (the
connectivity check reports such an overlap as a short).

**Mirror and rotate**: right-click a selection - or any shape, path or instance, which is then
selected - for *Mirror over X axis* (flip top to bottom), *Mirror over Y axis* (flip left to right)
and *Mirror over both axes*, about the selection's centre so it stays in place; *About the cell
origin* mirrors over the cell's own axes instead (the x = 0 / y = 0 lines), and *Rotate 90° left /
right* turns it. Works on shapes and on PCell / cell instances alike, one undo step each. The two
mirrors are also in the OpenLayout menu.

**Chaining** (shared diffusion, abutment): drop a transistor onto another of the same type and
row - its outer source/drain on the other's, or overlapping it by up to one more gate pitch - and it
snaps into the chain. Dropped beside it (dummy gates side by side, or one shared dummy gate), it
stays where you put it: a deliberate diffusion break, e.g. to line a gate up with its pair in the
other region. Chained,
the dummy gates between them go and the diffusion runs through; dropped right on top of a
neighbour, it goes to the side whose nets fit. With a schematic link it only
chains when the touching source/drain nets match, flipping the dropped transistor if that makes
them match. Moving a transistor away again restores its dummy gates. *OpenLayout ▸ Chain Selected
Transistors* packs the selection into chains left to right. In a transistor's properties (`q`)
*Contact on the shared left/right diffusion* can be switched off for the inner node of a series
stack (as in the library's NAND2).

The **LSW** (left side) is the only layer panel. *All layers* / *Used layers* tabs (used = has
shapes in the current cell). Click a layer to make it the current drawing layer, untick to hide it.
**AV** shows every layer; **NV** hides every layer except the current one. Selectability, as in
Virtuoso: right-click a layer to **lock** it (clicks in the layout skip it; locked layers are dimmed),
**AS** makes everything selectable, **NS** only the current layer (instances and vias, which are no
layer, are left out too) - e.g. NS on GCUT: clicks and box selections take only gate cuts. Hidden
layers can't be selected either.

The **Select** window (*OpenLayout ▸ Show Select*, right side, above Connectivity) sets which object types can be
selected: instances (transistors, cells), vias, shapes, pins, labels, the boundary and the
standard-cell frame (rails, fins, GCUT, implants), with *All* / *Shapes only* presets, the number of
locked layers and *Unlock all layers*. Clicks, box selections and the hover highlight all follow it;
turning a type off unselects it.

**DRD spacing hints** (design-rule-driven editing, notify only): in every editing tool - path, box,
polygon, stretch (`s` or the Partial tool), move (drag, `m`, KLayout's Move), copy (`c`), instance
placement and via placement (`o`) - every gap between what you are drawing or moving and a
neighbouring shape that is closer than the ASAP7 minimum spacing is outlined in red with a
dimension line labelled with the minimum: "18 nm min" on the same layer, "14 nm min to LISD"
between layers. The values are the DRC deck's: line-end vs. side spacing for LISD / LIG / M1-M3 /
M8-M9, the horizontal / vertical values for WELL, ACTIVE, GATE, SDT, GCUT and the track metals
M4-M7, the via spacings, corner-to-corner where the DRM has it, and between layers GATE-ACTIVE,
LIG-LISD / SDT / GATE / GCUT, SDT-GATE, GCUT-GATE, GCUT-ACTIVE and ACTIVE-WELL. **Minimum width**
("width 18 nm min"; horizontal / vertical where the DRM differs, e.g. M4 44 nm along the track, 24
across) and **minimum area** ("area 504 nm² min") are shown too, for the shape as it will be -
merged with what it touches on its layer, so a stub joined to a wire is fine. **Enclosures**: a
via cut on its metal needs the metal past it on two opposite sides ("M1 enclosure 5 / 0 nm min",
the DRM's end caps; V4-V7 11 nm, V8 20 nm, V0 by LISD 3 nm), and the extension rules NSELECT /
PSELECT / WELL around ACTIVE, GATE past ACTIVE (4 nm), ACTIVE past GATE (25 nm), GCUT past GATE
(17 nm), ACTIVE past FIN (10 nm), LIG past GATE (1 nm) and WELL / implants past GATE (7 nm) - shown
whether you edit the inner shape or the outer one. Shapes touching the
edited one count as connected to it and are not checked (the hints know no netlist: LIG and LISD
of the same net that do not touch are reported; Run DRC knows better). Instance placement covers
cells of the layout and standard cells (not PCells, whose parameters KLayout's instance tool keeps
to itself). Nothing is constrained - the hints go when the edit ends or on Esc. Switch them off
with *OpenLayout > DRD Spacing Hints*.

The **Connectivity** panel (right side) compares the layout with its schematic. It lists every
net as one of:

- **complete:** every terminal of the net is connected.
- **open:** the net is in several pieces. Its flight lines join the pieces: thin, solid, and one
  vibrant colour per net (the net's name in the list has the same colour). Under the net, each
  unconnected terminal is listed with the reason when it touches nothing, e.g. `pin B (its label is
  not on m1 metal)`: a pin is where its text label is, so the label must sit on the pin's metal.
- **short with X:** the net touches net X in the layout. Under it, *touches X* lists X's
  terminals in the same piece of metal. Click the net to outline the merged shapes in red, which
  shows where the two nets meet. The summary counts each short once (`1 short (VSS - Z)`).

**Net names on shapes** (*OpenLayout > Show Net Names on Shapes*, `Shift+N`, or the checkbox in
the panel): every piece of gate, LIG, LISD and metal shows the name of its net, the way a schematic-
driven layout editor does. The names come from the schematic link (else from the cell's pin labels);
the text scales with the zoom, runs along vertical wires and fits inside its shape, and appears once
it is big enough to read - zoom in to see the names of small contacts. Hidden layers stay unlabelled.
A shape that carries two nets (a short) shows both names, in red.

It also lists **pins without a label** (a schematic pin with no text label in the layout), parts
**not placed**, and parts **not in schematic**. Click a net to make its flight lines bolder;
double-click it to zoom to it.

## Moving between tools

Both tools have an **OpenLayout** menu that goes through the hub:

- xschem: *Open Layout in KLayout*, *Generate Symbol from Schematic*, *Open Symbol/Schematic*,
  *Show in Library Manager*,
  *Netlist (hub)*, *Simulate (hub)*
- KLayout: *Generate / Update Layout from Schematic* (the only place layouts are generated - a form
  asks which pins to create on which metal), *Check Connectivity*, *Run DRC* (ASAP7 deck on the cell
  being edited, markers in the marker browser - see [DRC.md](DRC.md)), *Run LVS* (against the
  cell's xschem schematic, results in the netlist browser - see [LVS.md](LVS.md)), *Open Schematic*,
  *Open Symbol*, *Show in Library Manager*, *Show LSW*, *Show Connectivity*

## Hub

| Key | Action | Key | Action |
|---|---|---|---|
| `Ctrl+N` | new cell view | `Ctrl+Shift+N` | new library |
| `Ctrl+O` | open | `Del` | delete (to trash) |
| `F2` | rename cell | `Ctrl+Shift+C` | copy cell |
| `F7` | netlist | `F8` | simulate |
| `F5` | refresh | `F1` | this page |
