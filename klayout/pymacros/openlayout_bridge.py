# $description: OpenLayout hub bridge
# $autorun
# $show-in-menu: false
#
# Command server that lets the OpenLayout hub drive this KLayout session. Active only when
# KLayout was started by the hub (OPENLAYOUT_KLAYOUT_PORT is set). Protocol: one JSON request
# line per connection, one JSON reply line back.
#   {"cmd": "ping"}
#   {"cmd": "open", "file": "/path/cell.gds", "cell": "INVx1", "readonly": false}
#   {"cmd": "drc_results", "file": "/path/cell.gds", "cell": "INVx1", "report": "/path/x.lyrdb"}
import json
import os

import pya


class OpenLayoutBridge:
    def __init__(self, port):
        self.server = pya.QTcpServer()
        self.server.newConnection = self._on_connection
        self.sockets = []
        if not self.server.listen(pya.QHostAddress("127.0.0.1"), port):
            print(f"OpenLayout bridge: cannot listen on port {port}")

    def _on_connection(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self.sockets.append(sock)
            sock.readyRead = lambda s=sock: self._on_ready(s)

    def _on_ready(self, sock):
        if not sock.canReadLine():
            return
        line = bytes(sock.readLine()).decode().strip()
        try:
            reply = self.handle(json.loads(line))
        except Exception as e:  # report every failure back to the hub
            reply = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        sock.write((json.dumps(reply) + "\n").encode())
        sock.flush()
        sock.disconnectFromHost()
        self.sockets = [s for s in self.sockets if s.state() != pya.QAbstractSocket.UnconnectedState]

    def handle(self, req):
        cmd = req.get("cmd")
        if cmd == "ping":
            return {"ok": True, "version": pya.Application.instance().version()}
        if cmd == "open":
            return self.open(req["file"], req.get("cell"), bool(req.get("readonly")))
        if cmd == "status":
            return {"ok": True, "views": self.status()}
        if cmd == "generate":  # {"schematic": path} - Layout XL style generate/update from source
            from openlayout_kl import gui
            report = gui.instance.generate_for(req["schematic"])
            return {"ok": True, "report": report, "message": gui.OpenLayoutUI.describe(report)}
        if cmd == "drc_results":  # {"file", "cell", "report"} - a batch DRC's results in the marker browser
            from openlayout_kl import drc
            return {"ok": True, "violations": drc.show_results(req["file"], req.get("cell"), req["report"])}
        if cmd == "connectivity":  # summary of the Connectivity panel's last check
            from openlayout_kl import connectivity, gui
            gui.instance.nets.run_check(force=True)
            res = gui.instance.nets.result
            return {"ok": True, "summary": connectivity.summary(res) if res else None}
        if cmd == "screenshot":  # {"file": ..., "width": w, "height": h} - whole main window
            mw = pya.Application.instance().main_window()
            if req.get("width") and req.get("height"):
                mw.resize(int(req["width"]), int(req["height"]))
            for _ in range(20):
                pya.Application.instance().process_events()
            mw.grab().save(req["file"])
            return {"ok": True}
        return {"ok": False, "error": f"unknown command {cmd!r}"}

    def status(self):
        """Open layouts: one entry per view with its file and the cell shown."""
        mw = pya.Application.instance().main_window()
        views = []
        for i in range(mw.views()):
            view = mw.view(i)
            for ci in range(view.cellviews()):
                cv = view.cellview(ci)
                views.append({"file": cv.filename(), "cell": cv.cell_name, "current": i == mw.current_view_index})
        return views

    def open(self, file, cell, readonly):
        mw = pya.Application.instance().main_window()
        file = os.path.realpath(file)
        view_index = cv_index = None
        for i in range(mw.views()):
            view = mw.view(i)
            for ci in range(view.cellviews()):
                if os.path.realpath(view.cellview(ci).filename()) == file:
                    view_index, cv_index = i, ci
        if view_index is None:
            mw.load_layout(file, "asap7", 1)  # mode 1: new view
            view_index, cv_index = mw.current_view_index, 0
        mw.select_view(view_index)
        view = mw.current_view()
        layout = view.cellview(cv_index).layout()
        target = layout.cell(cell) if cell else None
        if target is not None:
            view.select_cell(target.cell_index(), cv_index)
        view.max_hier()
        view.zoom_fit()
        if readonly:
            mw.message(f"{cell}: read-only PDK library layout - do not save changes", 8000)
        mw.showNormal()
        mw.raise_()
        mw.activateWindow()
        return {"ok": True}


_port = int(os.environ.get("OPENLAYOUT_KLAYOUT_PORT", "0") or 0)
if _port and pya.Application.instance().main_window() is not None:
    openlayout_bridge = OpenLayoutBridge(_port)
