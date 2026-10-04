"""Bridges to the design tools and the netlist/simulation commands.

xschem and KLayout each run as one long-lived process per workarea. The hub talks to them over
localhost TCP: xschem through its built-in Tcl command server (`xschem_listen_port`), KLayout
through the OpenLayout bridge macro (klayout/pymacros/openlayout_bridge.py), which speaks one
JSON request/response line per connection.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

from .workarea import LAYOUT, SCHEMATIC, SYMBOL, Cell, View, Workarea, WorkareaError


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ToolBridge:
    name = "tool"

    def __init__(self, workarea: Workarea):
        self.workarea = workarea
        self.port = free_port()
        self.proc: subprocess.Popen | None = None
        self.extra_env: dict = {}  # e.g. OPENLAYOUT_HUB_PORT, set by the hub

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _log_file(self):
        d = self.workarea.root / ".openlayout" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return open(d / f"{self.name}.log", "ab")

    def _spawn(self, argv: list[str], env: dict | None = None) -> None:
        log = self._log_file()
        self.proc = subprocess.Popen(argv, cwd=self.workarea.root, stdout=log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, env={**os.environ, **self.extra_env, **(env or {})},
                                     start_new_session=True)

    def _wait_ready(self, timeout: float = 60.0) -> None:
        # Retry only while the port refuses connections. Once a connection is accepted, wait for its
        # answer instead of abandoning it: the tool would still process the request and fail
        # writing to a closed socket (xschem: "puts" errors).
        end = time.time() + timeout
        while time.time() < end:
            if not self.running:
                raise WorkareaError(f"{self.name} exited during startup (see .openlayout/logs/{self.name}.log)")
            try:
                self.ping(max(1.0, end - time.time()))
                return
            except ConnectionRefusedError:
                time.sleep(0.25)
            except OSError:
                break
        raise WorkareaError(f"{self.name} did not answer on port {self.port} within {timeout:.0f}s")

    def ensure_started(self) -> None:
        if not self.running:
            self.start()
            self._wait_ready()

    # subclasses
    def start(self) -> None: ...
    def ping(self, timeout: float = 5.0) -> None: ...
    def open(self, view: View) -> str: ...


class XschemBridge(ToolBridge):
    name = "xschem"

    def start(self) -> None:
        self._spawn(["xschem", "--tcl", f"set xschem_listen_port {self.port}; set tabbed_interface 1"])

    def send(self, tcl: str, timeout: float = 60.0) -> str:
        with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as s:
            s.sendall(tcl.encode() + b"\n")
            s.shutdown(socket.SHUT_WR)  # xschem runs the command once the client half-closes
            chunks = []
            while chunk := s.recv(65536):
                chunks.append(chunk)
        return b"".join(chunks).decode(errors="replace")

    def ping(self, timeout: float = 5.0) -> None:
        self.send("xschem get version", timeout=timeout)

    def open(self, view: View) -> str:
        if view.type not in (SCHEMATIC, SYMBOL):
            raise WorkareaError(f"xschem cannot open {view.name} views")
        self.ensure_started()
        path = str(view.path).replace("\\", "/")
        # The first window still shows the empty untitled schematic: load into it; later views get a tab.
        cur = self.send("xschem get schname").strip()
        cmd = "xschem load" if cur.endswith("untitled.sch") or not cur else "xschem load_new_window"
        self.send(f"{cmd} {{{path}}}")
        self.send("catch {wm deiconify .; raise .}")
        return f"opened {view.cell.key} {view.name} in xschem"


class KLayoutBridge(ToolBridge):
    name = "klayout"

    def start(self) -> None:
        self._spawn(["klayout", "-e", "-n", "asap7"], env={"OPENLAYOUT_KLAYOUT_PORT": str(self.port)})

    def request(self, payload: dict, timeout: float = 10.0) -> dict:
        with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as s:
            s.sendall(json.dumps(payload).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        reply = json.loads(buf.decode() or "{}")
        if not reply.get("ok"):
            raise WorkareaError(f"klayout: {reply.get('error', 'no reply')}")
        return reply

    def ping(self, timeout: float = 5.0) -> None:
        self.request({"cmd": "ping"}, timeout=timeout)

    def open(self, view: View) -> str:
        if view.type is not LAYOUT:
            raise WorkareaError(f"KLayout cannot open {view.name} views")
        self.ensure_started()
        self.request({"cmd": "open", "file": str(view.path), "cell": view.gds_cell or view.cell.name,
                      "readonly": view.readonly})
        return f"opened {view.cell.key} layout in KLayout"


# ---- batch commands (run by the hub through QProcess so output streams into the CIW) -------

def netlist_command(wa: Workarea, cell: Cell) -> tuple[list[str], Path, Path]:
    """xschem command that netlists a cell's schematic. Returns (argv, cwd, netlist path)."""
    sch = cell.view("schematic")
    if sch is None:
        raise WorkareaError(f"{cell.key} has no schematic")
    out = wa.netlist_dir()
    out.mkdir(parents=True, exist_ok=True)
    argv = ["xschem", "-x", "-q", "-r", "-n", "-s", "-o", str(out), str(sch.path)]
    return argv, wa.root, out / f"{cell.name}.spice"


def drc_command(wa: Workarea, cell: Cell) -> tuple[list[str], Path, Path, View]:
    """`openlayout drc` on a cell's layout. Returns (argv, cwd, report path, layout view)."""
    layout = cell.view("layout")
    if layout is None:
        raise WorkareaError(f"{cell.key} has no layout")
    report = wa.verify_dir(cell) / f"{cell.name}.drc.lyrdb"
    argv = ["openlayout", "drc", str(layout.path), "--cell", layout.gds_cell or cell.name, "--report", str(report)]
    return argv, wa.root, report, layout


def lvs_command(wa: Workarea, cell: Cell) -> tuple[list[str], Path, Path, View]:
    """`openlayout lvs` on a cell's layout against its schematic (none: the standard-cell CDL).
    Returns (argv, cwd, report path, layout view)."""
    layout = cell.view("layout")
    if layout is None:
        raise WorkareaError(f"{cell.key} has no layout")
    report = wa.verify_dir(cell) / f"{cell.name}.lvsdb"
    argv = ["openlayout", "lvs", str(layout.path), "--cell", layout.gds_cell or cell.name, "--report", str(report)]
    sch = cell.view("schematic")
    if sch is not None:
        argv += ["--schematic", str(sch.path)]
    return argv, wa.root, report, layout


def simulate_command(wa: Workarea, cell: Cell, netlist: Path) -> tuple[list[str], Path]:
    run = wa.run_dir(cell)
    run.mkdir(parents=True, exist_ok=True)
    return ["ngspice", "-b", str(netlist)], run
