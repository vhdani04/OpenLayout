"""openlayout hubcmd: send a command to the running OpenLayout hub (used by the xschem/KLayout menus).

  openlayout hubcmd open     <file> <view> [--cell NAME]   open another view of the file's cell
  openlayout hubcmd select   <file> [--cell NAME]          show the cell in the Library Manager
  openlayout hubcmd netlist  <file>                        netlist the cell (hub CIW shows output)
  openlayout hubcmd simulate <file>                        netlist + simulate the cell
  openlayout hubcmd maestro  <file>                        the cell's Maestro (simulation setup)
  openlayout hubcmd viva     <file>                        the waveform viewer
  openlayout hubcmd ping     [<file>]
"""
import argparse
import json
import os
import socket
import sys

from .workarea import Workarea


def send(port: int, request: dict, timeout: float = 10.0) -> dict:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall(json.dumps(request).encode() + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.decode() or '{"ok": false, "error": "no reply from hub"}')


def hub_port(path: str | None) -> int | None:
    """The hub serving the file's workarea (session.json), else the hub that started this tool."""
    wa = Workarea.find(os.path.dirname(os.path.abspath(path)) if path else os.getcwd())
    port = wa.session().get("hub_port") if wa else None
    return port or (int(os.environ["OPENLAYOUT_HUB_PORT"]) if os.environ.get("OPENLAYOUT_HUB_PORT") else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openlayout hubcmd", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["open", "select", "netlist", "simulate", "maestro", "viva", "ping"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("view", nargs="?")
    ap.add_argument("--cell")
    a = ap.parse_args(argv)
    port = hub_port(a.path)
    if not port:
        print("The OpenLayout hub is not running for this workarea. Start it with `openlayout hub`.")
        return 1
    req = {"cmd": a.cmd, "path": os.path.abspath(a.path) if a.path else None, "view": a.view, "cell": a.cell}
    try:
        reply = send(port, req)
    except OSError:
        print("The OpenLayout hub is not answering. Start it with `openlayout hub`.")
        return 1
    print(reply.get("message") or reply.get("error") or "")
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
