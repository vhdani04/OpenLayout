"""OpenLayout xschem editing (property form, pin dialog, symbol border, context keys) against a
running xschem. Usage: python3 tests/xschem_edit_test.py <port> <workarea>
(xschem must run in <workarea> with the OpenLayout xschemrc and listen on <port>.)
"""
import os
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

# pin dialog in a schematic: two output pins, placed together and following the mouse
reply = send("after 600 {set ::ol_pin(names) {OUT2 OUT3}; set ::ol_pin(dir) output; .ol_pin.b.ok invoke}; "
             "ol_pin_dialog 200 200; set s [xschem get ui_state]; " + ESC + "; "
             "list [xschem getprop instance p_OUT2 lab] [xschem getprop instance p_OUT3 cell::type] "
             "[expr {($s & 32) != 0}]")
check("pin dialog places output pins that follow the mouse", reply == "OUT2 opin 1", reply)

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
    """The pin dialog at `at` (pixels) with these names, then the pins dropped by a click at `to`
    (or `then`: what to do instead of the click)."""
    send(f"set ::ol_pin(expand) {expand}; after 400 {{set ::ol_pin(names) {{{names}}}; "
         f"set ::ol_pin(dir) input; .ol_pin.b.ok invoke}}; ol_pin_dialog {at[0]} {at[1]}")
    send(move(*to))
    send(then or click(*to))
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
place("DATA[1:0]", (300, 300), (500, 380), expand=1)
check("expanded bus: one pin per bit", "{DATA[1]}" in pin_list() and "{DATA[0]}" in pin_list(), pin_list())
place("SEL<1:0>", (300, 300), (200, 250))
check("SEL<1:0> is written SEL[1:0]", "{SEL[1:0]}" in pin_list(), pin_list())
reply = send("after 400 {set ::ol_pin(names) 1bad; .ol_pin.b.ok invoke; "
             "after 200 {set ::err [.ol_pin.f.err cget -text]; .ol_pin.b.cancel invoke}}; "
             "ol_pin_dialog 300 300; set ::err")
check("a bad pin name keeps the dialog open with the reason", "letters" in reply, reply)
send("xschem set_modify 0")

print("PASS xschem edit" if not failures else f"FAIL xschem edit: {', '.join(failures)}")
