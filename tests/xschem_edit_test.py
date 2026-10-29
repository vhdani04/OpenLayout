"""OpenLayout xschem editing (property form, pin dialog, symbol border, context keys) against a
running xschem. Usage: python3 tests/xschem_edit_test.py <port> <workarea>
(xschem must run in <workarea> with the OpenLayout xschemrc and listen on <port>.)
"""
import os
import re
import socket
import sys
import time
from pathlib import Path

PORT, WA = int(sys.argv[1]), Path(sys.argv[2])
failures = []


def send(cmd, timeout=30.0):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    s.sendall(cmd.encode() + b"\n")
    s.shutdown(socket.SHUT_WR)
    out = b""
    while chunk := s.recv(65536):
        out += chunk
    s.close()
    return out.decode(errors="replace").strip()


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


ESC = "xschem callback .drw 2 300 300 65307 0 0 0"
LIB = os.environ.get("OL_TEST_LIB", "t")
sch = WA / f"libraries/{LIB}/inv/inv.sch"
sym = WA / f"libraries/{LIB}/box/box.sym"

check("normal cursor (no crosshair)", send("set draw_crosshair") == "0")
check("p, l, r bound to OpenLayout", all("ol_" in send(f"bind .drw <KeyPress-{k}>") for k in "plr"))

# property form: edit nfin and rename M2 through the form (the after-script fills and confirms it)
send(f"xschem load {{{sch}}}")
reply = send("after 700 {set ::ol_props(nfin) 5; set ::ol_props(name) MX; .ol_props.b.ok invoke}; "
             "xschem unselect_all; xschem select instance M2; xschem callback .drw 2 300 300 113 0 0 0; "
             "list [xschem getprop instance MX nfin] [xschem getprop instance MX nf] [winfo exists .ol_props]")
check("property form edits fields and the instance name", reply == "5 2 0", reply)
reply = send("after 700 {.ol_props.b.cancel invoke}; xschem unselect_all; xschem select instance M1; "
             "xschem callback .drw 2 300 300 113 0 0 0; xschem getprop instance M1 nfin")
check("cancel leaves the instance unchanged", reply == "3", reply)

# pin dialog in a schematic: two output pins, one at a time - the first follows the mouse, Esc
# discards it and the one still waiting
reply = send("after 600 {set ::ol_pin(names) {OUT2 OUT3}; set ::ol_pin(dir) output; .ol_pin.b.ok invoke}; "
             "focus -force .drw; update; set n0 [xschem get instances]; ol_pin_dialog 200 200; set s [xschem get ui_state]; "
             "set n1 [xschem get instances]; set lab [xschem getprop instance p_OUT2 lab]; "
             "set t [xschem getprop instance p_OUT2 cell::type]; "
             "event generate .drw <KeyPress-Escape> -x 200 -y 200; after 200; update; "
             "list $lab $t [expr {$n1 - $n0}] [expr {($s & 32) != 0}] [expr {[xschem get instances] - $n0}]")
check("pin dialog: the first of two pins follows the mouse, Esc discards both", reply == "OUT2 opin 1 1 0", reply)

# x and Ctrl+s save at once (xschem's own Ctrl+s asks first); Ctrl+x / Ctrl+i stay xschem's
check("x and Ctrl+s save, Ctrl+x / Alt+s stay xschem's",
      "ol_save" in send("bind .drw <KeyPress-x>") and "ol_save" in send("bind .drw <Control-KeyPress-s>")
      and "%N" in send("bind .drw <Control-KeyPress-x>") and "%N" in send("bind .drw <Alt-KeyPress-s>"))

# symbol editor: border rectangle, symbol pin dialog, line key
send(f"xschem load {{{sym}}}")
check("new symbol has the red border rectangle", send("xschem get rects 7") == "1")
check("border is an outline (not filled)", send("xschem getprop rect 7 0 fill") == "false")
time.sleep(0.8)  # grid follows the editor (polled)
check("symbol editor uses the fine snap", send("set cadsnap") == "2.5" and send(".statusbar.3 get") == "2.5",
      (send("set cadsnap"), send(".statusbar.3 get")))
before = int(send("xschem get rects 5") or 0)
reply = send("after 600 {set ::ol_pin(names) A; set ::ol_pin(dir) input; .ol_pin.b.ok invoke}; "
             "ol_pin_dialog 200 200; " + ESC + "; list [xschem get rects 5] "
             "[xschem getprop rect 5 [expr {[xschem get rects 5] - 1}] name]")
check("symbol pin dialog adds a named pin", reply == f"{before + 1} A", reply)
# STARTLINE (4) once drawing, or MENUSTART (65536) while waiting for the first click
reply = send("ol_key_l .drw 300 300; set s [xschem get ui_state]; " + ESC + "; expr {($s & 65540) != 0}")
check("l starts a line in the symbol editor", reply == "1", reply)

# After drawing a line (persistent mode keeps it active), choosing the toolbar circle must not keep
# drawing lines. Real X events (pointer warp + button press/release) go through Tk like the mouse.
def click(x, y):
    return (f"event generate .drw <Motion> -x {x} -y {y} -warp 1; update; after 50; "
            f"event generate .drw <ButtonPress-1> -x {x} -y {y}; update; "
            f"event generate .drw <ButtonRelease-1> -x {x} -y {y}; update; after 50")


def move(x, y):
    return f"event generate .drw <Motion> -x {x} -y {y} -warp 1; update; after 50"


send("wm geometry . 1000x700+0+0; update; focus -force .drw; update")
lines_before = int(send("xschem get lines 4") or 0)
send("ol_key_l .drw 300 300; " + click(300, 300) + "; " + move(400, 380) + "; " + click(400, 380))
top = send("xschem get top_path")
send(f"{top}.toolbar.bToolInsertCircle invoke; " + click(600, 300) + "; " + move(650, 300) + "; "
     + click(650, 300) + "; xschem abort_operation; xschem abort_operation")
lines_after = int(send("xschem get lines 4") or 0)
check("toolbar circle after a line does not keep drawing lines", lines_after == lines_before + 1,
      f"lines {lines_before} -> {lines_after}")


# Grab an edge of the selection box and drag it (stretch). Hovering highlights just that
# edge; while dragging a dashed outline shows the new box; on release only the grabbed edge (or the
# two edges of a corner) moved, on the grid, as one undo step. Pins are not dragged along.
def mapped():
    return send("lsort [lmap c [winfo children .drw] {if {[string match *olstrip_* $c] && [winfo ismapped $c]} "
                "{string range $c [expr {[string first olstrip_ $c] + 8}] end} else continue}]")


def drag(x0, y0, x1, y1, release=True, target=".drw", off=(0, 0)):
    cmds = [f"event generate .drw <Motion> -x {x0} -y {y0} -warp 1; update; after 30",
            f"event generate {target} <ButtonPress-1> -x {x0 - off[0]} -y {y0 - off[1]}; update; after 30"]
    for i in range(1, 6):
        x, y = x0 + (x1 - x0) * i // 5, y0 + (y1 - y0) * i // 5
        cmds.append(f"event generate .drw <Motion> -x {x} -y {y} -state 256 -warp 1; update; after 30")
    if release:
        cmds.append(f"event generate .drw <ButtonRelease-1> -x {x1} -y {y1} -state 256; update; after 50")
    return "; ".join(cmds)


def box():
    send("xschem unselect_all 0; xschem select rect 7 0 fast nodraw")
    r = send("xschem selected_set rect")
    send("xschem unselect_all 0")
    return [float(v) for v in r.split()[2:]]


def pins():
    send("xschem unselect_all 0; for {set i 0} {$i < [xschem get rects 5]} {incr i} {xschem select rect 5 $i fast nodraw}")
    r = send("xschem selected_set rect")
    send("xschem unselect_all 0")
    return r


def to_px(x, y):
    z, xo, yo = (float(send(f"xschem get {k}")) for k in ("zoom", "xorigin", "yorigin"))
    return int(round((x + xo) / z)), int(round((y + yo) / z))


send("xschem zoom_box -200 -150 200 150; update")
x1, y1, x2, y2 = box()
pins0 = pins()
px, py = to_px(x2, (y1 + y2) / 2 + 7)
send(f"event generate .drw <Motion> -x {px} -y {py} -warp 1; update; after 50; update")
check("hovering an edge highlights just that edge", mapped() == "hi_r", mapped())
send(drag(px, py, px + 60, py + 15, release=False))
check("dragging shows a dashed outline with the grabbed edge highlighted",
      mapped() == "dash_b dash_l dash_t hi_r", mapped())
send(f"event generate .drw <ButtonRelease-1> -x {px + 60} -y {py + 15} -state 256; update; after 50")
b = box()
check("dragging the right edge resizes only the width", b[0] == x1 and b[1] == y1 and b[3] == y2 and b[2] > x2,
      f"{[x1, y1, x2, y2]} -> {b}")
check("the dragged edge lands on the snap grid", b[2] % float(send("set cadsnap")) == 0, b)
check("pins stay where they are", pins() == pins0)
x1, y1, x2, y2 = b
# press on the highlight strip itself (it lies under the mouse): handed on to the drawing area
px, py = to_px((x1 + x2) / 2 + 13, y1)
send(f"event generate .drw <Motion> -x {px} -y {py} -warp 1; update; after 50; update")
sx, sy = (int(v) for v in send("list [winfo x .drw.olstrip_hi_t] [winfo y .drw.olstrip_hi_t]").split())
send(drag(px, py, px + 20, py - 40, target=".drw.olstrip_hi_t", off=(sx, sy)))
b = box()
check("dragging the top edge moves only the top", b[0] == x1 and b[2] == x2 and b[3] == y2 and b[1] < y1,
      f"{[x1, y1, x2, y2]} -> {b}")
x1, y1, x2, y2 = b
px, py = to_px(x1, y2)
send(drag(px, py, px - 30, py + 30))
b = box()
check("dragging a corner moves both of its edges", b[0] < x1 and b[3] > y2 and b[1] == y1 and b[2] == x2,
      f"{[x1, y1, x2, y2]} -> {b}")
send("xschem undo; update")
check("a resize is one undo step", box() == [x1, y1, x2, y2], box())
send(f"event generate .drw <Motion> -x 5 -y 5 -warp 1; update; after 50; update")
check("no overlay left over", mapped() == "", mapped())

# A symbol's selection box (hide=instance) is not drawn where the symbol is placed, but still sets
# the instance's selection area (needs setup/patches/xschem-hide-rect-instance.patch).
hid = WA / f"libraries/{LIB}/hid"
hid.mkdir(exist_ok=True)
(hid / "hid.sym").write_text(
    "v {xschem version=3.4.8RC file_version=1.3}\nG {}\nK {type=subcircuit\nformat=\"@name @pinlist @symname\"\n"
    "template=\"name=x1\"\n}\nV {}\nS {}\nE {}\nB 7 -60 -40 60 40 {fill=false hide=instance}\nL 4 -20 -10 20 -10 {}\n")
(hid / "top.sch").write_text("v {xschem version=3.4.8RC file_version=1.3}\nG {}\nK {}\nV {}\nS {}\nE {}\n"
                             f"C {{{LIB}/hid/hid.sym}} 0 0 0 0 {{name=x1}}\n")
send("xschem set_modify 0")
send(f"xschem load {{{hid / 'top.sch'}}}")
svg = hid / "top.svg"
send(f"xschem print svg {{{svg}}}")
text = svg.read_text() if svg.exists() else ""
check("selection box is not drawn in instances", 'class="l7"' not in text and 'class="l4"' in text)
reply = send("xschem instance_bbox x1")
check("selection box still sets the instance area", reply.splitlines()[-1].split()[1:] == ["-60", "-40", "60", "40"],
      reply)

# ---- pins: placing, Esc, labels used twice, buses ------------------------------------------------
pinsch = WA / f"libraries/{LIB}/pins"
pinsch.mkdir(exist_ok=True)
(pinsch / "pins.sch").write_text("v {xschem version=3.4.8RC file_version=1.3}\nG {}\nK {}\nV {}\nS {}\nE {}\n")
send("xschem set_modify 0")
send(f"xschem load {{{pinsch / 'pins.sch'}}}; xschem zoom_box -300 -200 300 200; update")


def pin_list():
    return send('set r {}; for {set k 0} {$k < [xschem get instances]} {incr k} {'
                'if {[xschem getprop instance $k cell::type] in {ipin opin iopin}} {'
                'lappend r [list [xschem getprop instance $k name] [xschem getprop instance $k lab] '
                '{*}[lrange [xschem instance_coord $k] 2 3]]}}; set r')


def place(names, at, to, expand=0, then=None):
    """The pin dialog at `at` (pixels) with these names, then the pins dropped one at a time by a
    click at each point of `to` (one point or a list), or `then`: what to do instead of the click."""
    send(f"set ::ol_pin(expand) {expand}; after 400 {{set ::ol_pin(names) {{{names}}}; "
         f"set ::ol_pin(dir) input; .ol_pin.b.ok invoke}}; ol_pin_dialog {at[0]} {at[1]}")
    for pt in to if isinstance(to, list) else [to]:
        send(move(*pt))
        send(then or click(*pt))
        send("after 300; update")


place("A", (300, 300), (340, 260))
check("a placed pin: nothing stays selected or moving", send("list [xschem get lastsel] [xschem get ui_state]") == "0 0",
      send("list [xschem get lastsel] [xschem get ui_state]"))
first = pin_list()
place("A", (300, 300), (420, 340))
now = pin_list()
check("the same label twice: two pins with unique names",
      sorted(p.split()[0] for p in now.strip("{}").split("} {")) == ["p_A", "p_A_2"], now)
check("the same label twice: the first pin stays put", first.strip("{}") in now, f"{first} -> {now}")
place("GONE", (300, 300), (360, 360), then="event generate .drw <KeyPress-Escape> -x 360 -y 360; update")
check("Esc discards the pins being placed", "GONE" not in pin_list(), pin_list())
place("WL[1:0]", (300, 300), (260, 380))
check("a bus pin WL[1:0]: one pin, a plain instance name", "p_WL_1_0 {WL[1:0]}" in pin_list(), pin_list())
place("DATA[1:0]", (300, 300), (500, 380), expand=1, then="update")   # no click: only DATA[1] exists
reply = send("list [expr {[xschem get ui_state] & 32}] [xschem getprop instance p_DATA_1 lab]")
check("expanded bus: one pin at a time", "{DATA[0]}" not in pin_list() and reply == "32 {DATA[1]}", (reply, pin_list()))
send(click(500, 380) + "; after 300; update")                        # DATA[1] down, DATA[0] follows
send(move(500, 300) + "; " + click(500, 300) + "; after 300; update")
pins = pin_list()
check("expanded bus: each bit where it was clicked",
      "p_DATA_1 {DATA[1]}" in pins and "p_DATA_0 {DATA[0]}" in pins and
      [p.split()[-1] for p in pins.strip("{}").split("} {") if "DATA" in p][0] !=
      [p.split()[-1] for p in pins.strip("{}").split("} {") if "DATA" in p][1], pins)
check("expanded bus: done placing", send("list [xschem get lastsel] [xschem get ui_state]") == "0 0",
      send("list [xschem get lastsel] [xschem get ui_state]"))
place("P Q", (300, 300), (240, 200), then="update")
send(click(240, 200) + "; after 300; update; event generate .drw <KeyPress-Escape> -x 240 -y 200; "
     "after 200; update")
check("Esc while placing keeps the pins already put down", "p_P P" in pin_list() and "p_Q" not in pin_list(),
      pin_list())
place("SEL<1:0>", (300, 300), (200, 250))
check("SEL<1:0> is written SEL[1:0]", "{SEL[1:0]}" in pin_list(), pin_list())
# pin labels stay horizontal however the pin is rotated (keep_horizontal: OpenLayout's pin symbols
# and xschem patch): the rotated pin's box is wider than tall
reply = send("xschem instance opin.sym 200 0 1 0 {name=p_kh lab=VERYLONGPINNAME}; "
             "lrange [xschem instance_bbox p_kh] 1 4")
x1, y1, x2, y2 = (float(v) for v in reply.split())
check("a rotated pin's label stays horizontal", x2 - x1 > 2 * (y2 - y1), reply)
send("xschem unselect_all; xschem select instance p_kh; xschem delete")
reply = send("after 400 {set ::ol_pin(names) 1bad; .ol_pin.b.ok invoke; "
             "after 200 {set ::err [.ol_pin.f.err cget -text]; .ol_pin.b.cancel invoke}}; "
             "ol_pin_dialog 300 300; set ::err")
check("a bad pin name keeps the dialog open with the reason", "letters" in reply, reply)
send("xschem set_modify 0")

# ---- the theme reaches widgets xschem creates later; menus; status fields; tabs ---------------------
ui = dict(zip(*[iter(send("set ol_theme(ui)").split())] * 2))
reply = send("listbox .ol_tl; entry .ol_te; set r [join [list [.ol_tl cget -background] [.ol_te cget -background] "
             "[option get . background {}]]]; destroy .ol_tl .ol_te; set r")
check("new widgets come up themed (lists and inputs on the base color)",
      reply.split() == [ui["base"], ui["base"], ui["panel"]], reply)
mb = top + ".menubar"
keys = send(f"list [{mb}.tools entrycget [ol_menu_find {mb}.tools {{Add Instance…}}] -accelerator] "
            f"[{mb}.file entrycget [ol_menu_find {mb}.file Save] -accelerator] "
            f"[{mb}.tools entrycget [ol_menu_find {mb}.tools {{Insert polygon}}] -accelerator] "
            f"[expr {{[ol_menu_find {mb}.sym {{Create Pin…}}] >= 0}}]")
check("menus show OpenLayout's keys", keys == "{I, Ins} {X, Ctrl+S} {} 1", keys)
reply = send(f"{top}.statusbar.3 configure -background PaleGreen; set a [{top}.statusbar.3 cget -background]; "
             f"{top}.statusbar.3 configure -background OrangeRed; set b [{top}.statusbar.3 cget -background]; "
             f"{top}.statusbar.3 configure -background PaleGreen; join [list $a $b]")
check("the snap field's PaleGreen / OrangeRed map to the theme",
      reply.split()[0] == ui["base"] and reply.split()[1].lower() not in ("orangered", "#ff4500"), reply)
reply = send("set_tab_names; .tabs.x0 cget -background")
check("the current tab is in the selection color", reply == ui["select"], reply)

# ---- Add Instance: i opens the browser; libraries, filter, preview, placing ------------------------
send("xschem unselect_all; focus -force .drw; update")
send(f"event generate .drw <KeyPress-i> -x 400 -y 300; update; after 300; update")
libs = send("lmap l $ol_inst(libs) {lindex $l 0}")
check("i opens Add Instance, the workarea's libraries first and Basic last",
      send("winfo exists .ol_inst") == "1" and libs.split()[0] == LIB and libs.split()[-1] == "Basic"
      and "asap7_devices" in libs.split(), libs)
reply = send(".ol_inst.body.lib.l selection clear 0 end; .ol_inst.body.lib.l selection set "
             "[lsearch -index 0 $ol_inst(libs) asap7_devices]; ol_inst_lib_changed; "
             "set ol_inst(filter) nmos_rv; update; "
             "list [llength $ol_inst(shown)] [.ol_inst.body.pv.path cget -text] [.ol_inst.body.pv.pins cget -text]")
check("the filter narrows the cells; the preview names the symbol and its pins",
      reply.startswith("1 asap7_devices/nmos_rvt/nmos_rvt.sym") and "d  g  s  b" in reply, reply)
reply = send("ol_inst_place; update; list [winfo exists .ol_inst] [expr {([xschem get ui_state] & 8192) != 0}]")
check("Place closes it and puts the symbol on the mouse", reply == "0 1", reply)
send(ESC + "; update; xschem set_modify 0")
reply = send("set ol_inst(keep) 1; ol_instance_browser; ol_inst_place; update; "
             "set r [winfo exists .ol_inst]; ol_inst_close; set ol_inst(keep) 0; set r")
send(ESC + "; update; xschem set_modify 0")
check("Keep open leaves it open for the next one", reply == "1", reply)

# ---- copy: the reference click may land on the selection ------------------------------------------
# cadence_compat trims a selection to the object clicked - not when the click is a command's
# reference point (needs setup/patches/xschem-command-click-keeps-selection.patch)
cpdir = WA / f"libraries/{LIB}/cp"
cpdir.mkdir(exist_ok=True)
(cpdir / "cp.sch").write_text("v {xschem version=3.4.8RC file_version=1.3}\nG {}\nK {}\nV {}\nS {}\nE {}\n"
                              + "".join(f"C {{asap7_devices/nmos_sram/nmos_sram.sym}} {x} 0 0 0 {{name=M{i} l=20n nfin=2 nf=1 m=1}}\n"
                                        for i, x in enumerate((0, 100, 200), 1)))
def click1(x, y):
    # as the mouse does it: the release carries Button1Mask
    return (f"event generate .drw <Motion> -x {x} -y {y} -warp 1; update; after 50; "
            f"event generate .drw <ButtonPress-1> -x {x} -y {y}; update; "
            f"event generate .drw <ButtonRelease-1> -x {x} -y {y} -state 256; update; after 50")


send(f"xschem load {{{cpdir / 'cp.sch'}}}; xschem zoom_box -150 -150 350 150; update; focus -force .drw; update")
send("xschem unselect_all; xschem select instance M1; xschem select instance M2; xschem select instance M3")
px, py = to_px(100, 0)
send(f"event generate .drw <Motion> -x {px} -y {py} -warp 1; update; xschem callback .drw 2 {px} {py} 99 0 0 0; update")
send(click1(px, py))
reply = send("list [expr {([xschem get ui_state] & 64) != 0}] [llength [xschem selected_set]]")
check("c, then a click on one of the selected: the copy takes all of them", reply == "1 3", reply)
qx, qy = to_px(100, 100)
send(move(qx, qy) + "; " + click1(qx, qy))
check("the copies are placed", send("xschem get instances") == "6", send("xschem get instances"))
send("xschem undo; update")
send("xschem unselect_all; xschem select instance M1; xschem select instance M2")
px, py = to_px(0, 0)
send(click1(px, py))
check("a plain click on one of the selected still selects just that one",
      send("xschem selected_set") == "{M1}", send("xschem selected_set"))
send("xschem unselect_all; xschem set_modify 0")

# ---- Caps Lock: keys act as if it were off -------------------------------------------------------
# With Caps Lock, c arrives as C: xschem's "place arc". Re-issued without Lock it is the copy again.
send(f"xschem load {{{cpdir / 'cp.sch'}}}; xschem zoom_box -150 -150 350 150; update; focus -force .drw; update")
send("xschem unselect_all; xschem select instance M2")
n0 = int(send("xschem get instances"))
px, py = to_px(100, 0)
send(f"event generate .drw <Motion> -x {px} -y {py} -warp 1; update; "
     f"event generate .drw <KeyPress> -keysym C -state 2 -x {px} -y {py}; update")
send(click1(px, py))
qx, qy = to_px(100, 100)
send(move(qx, qy) + "; " + click1(qx, qy))
reply = send("xschem get instances")
check("c with Caps Lock on copies (not an arc)", reply == str(n0 + 1), reply)
send("xschem undo; update; xschem unselect_all; xschem set_modify 0")
check("keys pressed with Caps Lock are re-issued without it", "ol_caps_key" in send("bind .drw <Lock-KeyPress>"))

# ---- symbol pins stay on the 10 grid ---------------------------------------------------------------
# A pin off it can't be reached by schematic wires. Saving snaps it, its stub moves along and stays
# straight; a selected pin moves on the 10 grid.
offdir = WA / f"libraries/{LIB}/offgrid"
offdir.mkdir(exist_ok=True)
offsym = offdir / "offgrid.sym"
original = ("v {xschem version=3.4.8RC file_version=1.3}\nG {}\n"
            'K {type=subcircuit\nformat="@name @pinlist @symname"\ntemplate="name=x1"\n}\n'
            "V {}\nS {}\nE {}\n"
            "L 4 -80 15 -60 15 {}\nL 4 47.5 -77.5 47.5 77.5 {}\n"
            "B 5 -82.5 12.5 -77.5 17.5 {name=A dir=in}\nB 5 45 -80 50 -75 {name=B dir=inout}\n"
            "B 5 45 75 50 80 {name=C dir=inout}\nB 7 -80 -80 80 80 {fill=false hide=instance}\n")
offsym.write_text(original)
send(f"xschem load {{{offsym}}}; xschem zoom_full; update; focus -force .drw; update")
send("xschem set_modify 1; xschem save")  # xschem's own save: the file as xschem writes it, pins still off the grid
original = offsym.read_text()
time.sleep(0.8)
send("xschem select rect 5 0 fast")
time.sleep(0.8)
snap_pin = send("set cadsnap")
send("xschem unselect_all")
time.sleep(0.8)
check("a selected pin snaps at 10, other shapes at 2.5", (snap_pin, send("set cadsnap")) == ("10", "2.5"),
      (snap_pin, send("set cadsnap")))
send("event generate .drw <KeyPress-x> -x 300 -y 300; update")
saved = offsym.read_text()
check("saving a symbol puts its pins on the 10 grid",
      all(b in saved for b in ("B 5 -82.5 17.5 -77.5 22.5", "B 5 47.5 -82.5 52.5 -77.5", "B 5 47.5 77.5 52.5 82.5")),
      [l for l in saved.splitlines() if l.startswith("B 5")])
check("stubs move along and stay straight", "L 4 -80 20 -60 20 {}" in saved and "L 4 50 -80 50 80 {}" in saved,
      [l for l in saved.splitlines() if l.startswith("L 4")])
send("xschem undo; update; xschem save")
check("the snap is one undo step", offsym.read_text() == original,
      [l for l in offsym.read_text().splitlines() if l not in original.splitlines()])
send("xschem set_modify 0")

# ---- pins: only the pin on the mouse is drawn; symbol pins move whole; after a wire --------------
# xschem leaves what it moves drawn where the move started: a pin drawn when it was made stayed
# there as a second copy - for the next bit of a bus, on top of the one just put down.
def drw_region(cx, cy, w=130, h=30):
    """The drawing area's pixels around (cx, cy) as xwd sees them, or None without xwd."""
    import shutil
    import struct
    import subprocess
    if not shutil.which("xwd"):
        return None
    data = subprocess.run(["xwd", "-silent", "-id", send("winfo id .drw")], capture_output=True).stdout
    if len(data) < 100:
        return None
    v = struct.unpack(">25I", data[:100])
    hs, width, height, bpp, bpl, ncolors = v[0], v[4], v[5], v[11], v[12], v[19]
    px, b = data[hs + ncolors * 12:], bpp // 8
    return b"".join(px[y * bpl + max(0, cx - w) * b:y * bpl + min(width, cx + w) * b]
                    for y in range(max(0, cy - h), min(height, cy + h)))


(pinsch / "ghost.sch").write_text("v {xschem version=3.4.8RC file_version=1.3}\nG {}\nK {}\nV {}\nS {}\nE {}\n")
send("xschem set_modify 0")
send(f"xschem load {{{pinsch / 'ghost.sch'}}}; xschem zoom_box -300 -200 300 200; update; focus -force .drw; update")
time.sleep(0.8)  # grid follows the editor (polled)
send(move(400, 150) + "; xschem redraw; update")
before = drw_region(400, 150)
place("GH[1:0]", (400, 150), (400, 260), expand=1, then="update")    # GH[1] follows the mouse
send(move(400, 255) + "; " + move(400, 260) + "; update")              # (the rubber follows motions)
mid1 = drw_region(400, 150)
send(click1(400, 260) + "; after 300; update")                         # GH[1] down, GH[0] follows
send(move(400, 365) + "; " + move(400, 370) + "; update")
mid2 = drw_region(400, 260)
send(click1(400, 370) + "; after 300; update; xschem redraw; update")
after2 = drw_region(400, 260)
if before is None:
    print("SKIP a pin on the mouse is not also drawn where it was made (no xwd)")
else:
    check("a pin on the mouse is not also drawn where it was made", mid1 == before)
    check("the next bit of a bus is not drawn over the pin just put down", mid2 == after2)
check("both bits placed", "p_GH_1 {GH[1]}" in pin_list() and "p_GH_0 {GH[0]}" in pin_list(), pin_list())

# a wire ended with a double click stays xschem's persistent command: the click that puts a pin
# down started another wire, and the pin stayed on the mouse
send("xschem set_modify 0")
send(f"xschem load {{{pinsch / 'ghost.sch'}}}; xschem zoom_box -300 -200 300 200; update; focus -force .drw; update")
nw = int(send("xschem get wires"))
send("event generate .drw <KeyPress-w> -x 200 -y 500; update; " + click1(200, 500) + "; " + move(300, 500) + "; "
     + click1(300, 500) + "; event generate .drw <ButtonPress-1> -x 300 -y 500; update; "
     "event generate .drw <ButtonRelease-1> -x 300 -y 500 -state 256; update; after 100")
reply = send("list [xschem get wires] [xschem get ui_state]")
place("AW", (500, 500), (560, 500), then=click1(560, 500))
check("a pin right after a wire: placed with one click, no wire started",
      "p_AW AW" in pin_list() and send("list [xschem get wires] [xschem get ui_state]") == f"{nw + 1} 0",
      (reply, send("list [xschem get wires] [xschem get ui_state]"), pin_list()))
send("xschem set_modify 0")

# symbol editor: the pin's name and stub follow it, and it lands on the 10 grid (the pointer is not)
psdir = WA / f"libraries/{LIB}/pinsym"
psdir.mkdir(exist_ok=True)
(psdir / "pinsym.sym").write_text("v {xschem version=3.4.8RC file_version=1.3}\nG {}\n"
                                  'K {type=subcircuit\nformat="@name @pinlist @symname"\ntemplate="name=x1"\n}\n'
                                  "V {}\nS {}\nE {}\nB 7 -80 -50 80 50 {fill=false hide=instance}\n")
send(f"xschem load {{{psdir / 'pinsym.sym'}}}; xschem zoom_box -200 -150 200 150; update; focus -force .drw; update")
place("S[1:0]", (300, 300), [(343, 262), (461, 337)], expand=1)
send("xschem select_all")
rects = [r.split() for r in send("xschem selected_set rect").splitlines() if r.split()[0] == "5"]
lines = [tuple(float(v) for v in r.split()[2:]) for r in send("xschem selected_set line").splitlines() if r.strip()]
texts = send("xschem selected_set text")
send("xschem unselect_all")
ok, detail = len(rects) == 2, []
for r in rects:
    cx, cy = (float(r[2]) + float(r[4])) / 2, (float(r[3]) + float(r[5])) / 2
    detail.append((cx, cy))
    ok = ok and cx % 10 == 0 and cy % 10 == 0 and (cx, cy, cx + 20, cy) in lines
check("symbol pins: on the 10 grid, each with its stub", ok, (detail, lines))
tpos = [tuple(float(v) for v in t.split()[1:3]) for t in texts.splitlines() if t.strip()]
check("symbol pins: each name next to its pin", all((cx + 25, cy - 5) in tpos for cx, cy in detail),
      (detail, texts))
send("xschem set_modify 0")

# ---- wires: a junction only where the user clicked -----------------------------------------------
# With orthogonal wiring a click put down only the first leg of the L, ending at its corner: when
# that corner lay on another wire (or the user clicked on one at the other end of the L), the wires
# joined there - a solder dot nobody clicked, shorting two nets (needs
# setup/patches/xschem-wire-corner-off-nets.patch). Now a click puts down the whole L up to the
# click, and the corner keeps off other wires and pins.
jdir = WA / f"libraries/{LIB}/jn"
jdir.mkdir(exist_ok=True)
jsch = jdir / "jn.sch"
EXIST = [(100.0, -150.0, 100.0, 150.0), (-200.0, 0.0, 200.0, 0.0)]


def wire_run(clicks, end="esc"):
    """A fresh schematic with a vertical wire V (x=100) and a horizontal wire H (y=0); draw a wire
    with w and a click at each point (schematic coordinates); end it with Esc or a double click.
    Returns the new wires."""
    jsch.write_text("v {xschem version=3.4.8RC file_version=1.3}\nG {}\nK {}\nV {}\nS {}\nE {}\n"
                    "N 100 -150 100 150 {lab=V}\nN -200 0 200 0 {lab=H}\n")
    send("xschem set_modify 0")
    send(f"xschem load {{{jsch}}}; xschem zoom_box -250 -200 250 200; update; focus -force .drw; update")
    pts = [to_px(*c) for c in clicks]
    cmd = [f"event generate .drw <KeyPress-w> -x {pts[0][0]} -y {pts[0][1]}; update"]
    prev = pts[0]
    for x, y in pts:
        cmd.append(move((prev[0] + x) // 2, (prev[1] + y) // 2))
        cmd.append(click1(x, y))
        prev = (x, y)
    if end == "double":
        cmd.append(f"event generate .drw <ButtonPress-1> -x {prev[0]} -y {prev[1]}; update; "
                   f"event generate .drw <ButtonRelease-1> -x {prev[0]} -y {prev[1]} -state 256; update")
    cmd.append(f"event generate .drw <KeyPress-Escape> -x {prev[0]} -y {prev[1]}; update; after 100")
    send("; ".join(cmd))
    send("xschem save")
    found = re.findall(r"^N (\S+) (\S+) (\S+) (\S+)", jsch.read_text(), re.M)
    return [w for w in (tuple(float(v) for v in f) for f in found) if w not in EXIST]


def ends_on_existing(new):
    on = lambda p, w: ((w[1] == w[3] == p[1] and min(w[0], w[2]) <= p[0] <= max(w[0], w[2])) or
                       (w[0] == w[2] == p[0] and min(w[1], w[3]) <= p[1] <= max(w[1], w[3])))
    return sorted({p for w in new for p in (w[:2], w[2:]) if any(on(p, e) for e in EXIST)})


new = wire_run([(-40, 100), (100, 170)])
check("an L whose corner would sit on another wire turns the other way (no junction)",
      ends_on_existing(new) == [] and new, new)
new = wire_run([(40, -120), (40, 120)])
check("a wire crossing another one does not join it", ends_on_existing(new) == [] and new, new)
new = wire_run([(-150, 60), (100, -100)])
check("a click on a wire ends the wire there (the junction the user clicked)",
      ends_on_existing(new) == [(100.0, -100.0)], new)
new = wire_run([(-150, -60), (170, 110)])
check("a click puts down the whole L up to the click",
      [p for w in new for p in (w[:2], w[2:])].count((170.0, 110.0)) == 1 and ends_on_existing(new) == [], new)
new = wire_run([(-150, -60), (170, 110)], end="double")
check("a double click ends the wire at the click", len(new) == 2 and
      [p for w in new for p in (w[:2], w[2:])].count((170.0, 110.0)) == 1, new)
send("xschem set_modify 0")

print("PASS xschem edit" if not failures else f"FAIL xschem edit: {', '.join(failures)}")
