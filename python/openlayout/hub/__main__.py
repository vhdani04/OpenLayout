"""Start the hub:  openlayout hub [workarea]"""
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from ..workarea import Workarea, WorkareaError
from . import theme
from .main_window import MainWindow


def resolve_workarea(arg: str | None) -> Workarea | None:
    candidates = [arg] if arg else [str(Path.cwd()), QSettings("OpenLayout", "hub").value("workarea", "")]
    for c in candidates:
        if c:
            try:
                wa = Workarea.find(c)
            except WorkareaError:
                wa = None
            if wa:
                return wa
    return None


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("OpenLayout")
    app.setOrganizationName("OpenLayout")
    app.setDesktopFileName("openlayout")
    theme.apply(app)
    win = MainWindow(resolve_workarea(sys.argv[1] if len(sys.argv) > 1 else None))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
