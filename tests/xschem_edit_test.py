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
before = int(send("xschem get rects 5") or 0)
reply = send("after 600 {set ::ol_pin(names) A; set ::ol_pin(dir) input; .ol_pin.b.ok invoke}; "
             "ol_pin_dialog 200 200; " + ESC + "; list [xschem get rects 5] "
             "[xschem getprop rect 5 [expr {[xschem get rects 5] - 1}] name]")
check("symbol pin dialog adds a named pin", reply == f"{before + 1} A", reply)
# STARTLINE (4) once drawing, or MENUSTART (65536) while waiting for the first click
reply = send("ol_key_l .drw 300 300; set s [xschem get ui_state]; " + ESC + "; expr {($s & 65540) != 0}")
check("l starts a line in the symbol editor", reply == "1", reply)

print("PASS xschem edit" if not failures else f"FAIL xschem edit: {', '.join(failures)}")
