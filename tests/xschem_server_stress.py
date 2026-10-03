"""Stress xschem's TCP command server the way an impatient client does: a slow request is running
(it processes events) while other clients connect, give up early and close. Afterwards xschem must
have raised no background errors (each one is an error dialog), `puts` must be the built-in again,
and normal requests must still work.

Usage: python3 tests/xschem_server_stress.py <port>
(Run it against plain xschem - started outside a workarea - to see the failure OpenLayout fixes.)
"""
import socket
import sys
import threading
import time

PORT = int(sys.argv[1])


def send(cmd, timeout=10.0):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    s.sendall(cmd.encode() + b"\n")
    s.shutdown(socket.SHUT_WR)
    out = b""
    while chunk := s.recv(65536):
        out += chunk
    s.close()
    return out.decode(errors="replace").strip()


def impatient(cmd):
    """Connect, send, give up after 0.2 s without reading the reply."""
    s = None
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=0.2)
        s.sendall(cmd.encode() + b"\n")
        s.shutdown(socket.SHUT_WR)
        s.recv(10)
    except OSError:
        pass
    finally:
        if s:
            s.close()


# Count background errors instead of showing dialogs.
send("set ::ol_bgerrors 0; interp bgerror {} {apply {{msg opts} {incr ::ol_bgerrors}}}")
# A long request that keeps processing events (like a load that opens a dialog) while other
# requests arrive: patient ones that wait for their answer, and impatient ones that give up.
slow = threading.Thread(target=lambda: send("for {set i 0} {$i < 20} {incr i} {update; after 100}; set slow done", 30))
slow.start()
time.sleep(0.2)
answers = []
for k in range(6):
    threading.Thread(target=lambda: answers.append(send("xschem get version", 30)), daemon=True).start()
    impatient("xschem get version")
    time.sleep(0.15)
slow.join()
time.sleep(1.0)
bg = send("set ::ol_bgerrors")
# Inside a request xschem redirects puts: both the redirect and the saved built-in must exist.
builtin = send("list [info procs puts] [info commands ::tcl::puts]") == "puts ::tcl::puts"
works = send("set x hello") == "hello" and len(answers) == 6 and all(answers)
ok = bg == "0" and builtin and works
print(("PASS" if ok else "FAIL") + f" xschem server (background errors={bg}, puts restored={builtin}, requests work={works})")
