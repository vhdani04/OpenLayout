"""Parasitic extraction from KLayout: OpenLayout > Run PEX runs `openlayout pex` (FasterCap 3D field
solver + resistor networks, python/openlayout/pex.py) on the cell being edited - and writes <cell>.pex.spice next to the layout file, for post-layout
simulation.

run(): the batch run, parsed. run_current(): the menu command - the current cell as edited (saved
or not), pins in the order of its schematic when it has one. It runs in the background with a log
window (each step and each window of a windowed solve as it finishes, with the time since the
start) and Stop / Close buttons; KLayout stays usable meanwhile. Large blocks are solved
`default_jobs()` windows at a time.
"""
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import pya

from . import checks
from .lvs import schematic_for

_box = None            # the (non-modal) summary of the last run
_run = None            # the run in progress (PexRun), if any
_last = None           # the last run started
RESULT_RE = re.compile(r"^RESULT PEX \S+ devices=(\d+) resistors=(\d+) capacitors=(\d+)(.*)$", re.M)


def default_jobs() -> int:
    """Windows solved at a time: FasterCap keeps about one core busy per solve, so all but two."""
    return max(1, min(6, (os.cpu_count() or 2) - 2))


def _argv(gds, cell, out, schematic, mode, jobs):
    argv = ["openlayout", "pex", str(gds), "--cell", cell, "--out", str(out), "--mode", mode]
    if schematic:
        argv += ["--schematic", str(schematic)]
    if jobs and jobs > 1:
        argv += ["--jobs", str(jobs)]
    return argv


def parse(text, out):
    """The summary of a finished run's output, or None."""
    m = RESULT_RE.search(text)
    if not m:
        return None
    caps = dict(re.findall(r"C\((\S+)\)=([0-9.]+)fF", m.group(4)))
    return {"devices": int(m.group(1)), "resistors": int(m.group(2)), "capacitors": int(m.group(3)),
            "total_fF": {k: float(v) for k, v in caps.items()}, "out": str(out)}


def run(gds, cell, out, schematic=None, mode="rc", jobs=1):
    """Batch PEX (as `openlayout pex`). Returns (summary dict, output text)."""
    res = subprocess.run(_argv(gds, cell, out, schematic, mode, jobs), capture_output=True, text=True, timeout=7200)
    text = res.stdout + res.stderr
    summary = parse(text, out)
    if res.returncode != 0 or summary is None:
        raise RuntimeError(f"PEX did not run:\n{text[-800:]}")
    return summary, text


class PexRun:
    """One `openlayout pex` in the background, with its log window."""

    def __init__(self, mw, cv, cell, gds, out, sch):
        self.mw, self.cv, self.cell, self.out = mw, cv, cell, out
        self.summary, self.text, self.done, self.t0 = None, "", False, time.time()
        self.argv = _argv(gds, cell, out, sch, "rc", default_jobs())

        self.dlg = pya.QDialog(mw)
        self.dlg.windowTitle = f"PEX - {cell}"
        self.dlg.setModal(False)
        lay = pya.QVBoxLayout(self.dlg)
        self.status = pya.QLabel("", self.dlg)
        lay.addWidget(self.status)
        self.log = pya.QPlainTextEdit(self.dlg)
        self.log.objectName = "pex_log"
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(pya.QPlainTextEdit.NoWrap)
        font = pya.QFont("Monospace")
        font.setStyleHint(pya.QFont.TypeWriter)
        self.log.setFont(font)
        self.log.setMinimumWidth(640)
        self.log.setMinimumHeight(320)
        lay.addWidget(self.log)
        row = pya.QHBoxLayout()
        row.addStretch(1)
        self.stop_button = pya.QPushButton("Stop", self.dlg)
        self.stop_button.clicked = self.stop
        close = pya.QPushButton("Close", self.dlg)
        close.clicked = lambda: self.dlg.hide()      # the run goes on; Run PEX shows the window again
        row.addWidget(self.stop_button)
        row.addWidget(close)
        lay.addLayout(row)
        self.add(" ".join(self.argv))

        self.proc = pya.QProcess(self.dlg)
        self.proc.setProcessChannelMode(pya.QProcess.MergedChannels)
        self.proc.readyReadStandardOutput = self.read
        self.proc.finished = lambda *a: self.finish()
        self.timer = pya.QTimer(self.dlg)
        self.timer.interval = 1000
        self.timer.timeout = self.tick
        self.timer.start()
        self.tick()
        # setsid: its own process group, so Stop also ends the FasterCap processes it started
        self.proc.start("setsid", self.argv)
        self.dlg.show()

    def elapsed(self):
        s = int(time.time() - self.t0)
        return f"{s // 60:02d}:{s % 60:02d}"

    def add(self, line):
        self.log.appendPlainText(f"[{self.elapsed()}] {line}")

    def tick(self):
        if not self.done:
            self.status.text = f"Extracting {self.cell} ({default_jobs()} windows at a time) - {self.elapsed()}"

    def read(self):
        data = self.proc.readAllStandardOutput()
        chunk = data if isinstance(data, str) else bytes(data).decode(errors="replace")
        self.text += chunk
        self._partial = getattr(self, "_partial", "") + chunk
        *lines, self._partial = self._partial.split("\n")
        for line in lines:
            if line.strip():
                self.add(line.rstrip())

    def stop(self):
        if self.done:
            return
        pid = self.proc.processId()
        try:
            os.killpg(pid, signal.SIGTERM)
        except (OSError, TypeError):
            self.proc.kill()
        self.add("stopped")

    def finish(self):
        self.read()
        if getattr(self, "_partial", "").strip():
            self.add(self._partial.rstrip())
        self.done = True
        self.timer.stop()
        self.stop_button.setEnabled(False)
        self.summary = parse(self.text, self.out)
        global _run
        _run = None
        if self.summary is None:
            self.status.text = f"PEX of {self.cell} did not finish ({self.elapsed()})"
            self.mw.message(f"PEX {self.cell}: failed - see the PEX window", 20000)
            self.dlg.show()
            return
        s = self.summary
        self.status.text = f"Done in {self.elapsed()}: {s['out']}"
        self.mw.message(f"PEX {self.cell}: {s['out']}", 20000)
        checks.record(self.cv, "pex", True, f"{s['devices']} transistors, {s['resistors']} R, "
                                            f"{s['capacitors']} C")
        caps = "\n".join(f"    {net:10s} {c:.4f} fF" for net, c in s["total_fF"].items())
        global _box
        _box = pya.QMessageBox(pya.QMessageBox.Information, "OpenLayout PEX",
                               f"{self.cell}: {s['devices']} transistors, {s['resistors']} resistors, "
                               f"{s['capacitors']} capacitors\n\nTotal capacitance per pin:\n{caps}\n\n"
                               f"Netlist: {s['out']}", pya.QMessageBox.Ok, self.mw)
        _box.setModal(False)
        _box.show()


def run_current(mw=None, wait=False):
    """PEX of the current view's cell, in the background with its log window. Returns the PexRun
    (None without a layout); with wait, waits for it and returns the summary (None if it failed)."""
    global _run
    mw = mw or pya.Application.instance().main_window()
    if _run is not None and not _run.done:
        mw.message(f"PEX of {_run.cell} is still running", 5000)
        _run.dlg.show()
        _run.dlg.raise_()
        return _run
    view = mw.current_view()
    cv = view.active_cellview() if view else None
    if cv is None or not cv.is_valid():
        pya.MessageBox.info("OpenLayout", "Open a layout first.", pya.MessageBox.Ok)
        return None
    cell = cv.cell_name
    tmp = Path(tempfile.mkdtemp(prefix="ol_pex_"))
    gds = tmp / f"{cell}.gds"
    cv.layout().write(str(gds))                 # the layout as edited
    out = Path(cv.filename()).parent / f"{cell}.pex.spice" if cv.filename() else tmp / f"{cell}.pex.spice"
    sch = schematic_for(cv.filename(), cell) if cv.filename() else None
    mw.message(f"PEX: extracting {cell} (FasterCap) ...", 5000)
    global _last
    _run = _last = PexRun(mw, cv, cell, gds, out, sch)
    if not wait:
        return _run
    r = _run
    while not r.done:
        pya.QCoreApplication.processEvents()
        time.sleep(0.02)
    return r.summary
