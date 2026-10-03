"""Dialogs for creating and copying cells."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                               QVBoxLayout)

from ..workarea import CREATABLE, NAME_RE, Cell, Library, Workarea


def _buttons(dialog: QDialog) -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def _writable(wa: Workarea) -> list[Library]:
    return [lib for lib in wa.libraries() if not lib.readonly and lib.exists]


class NewCellViewDialog(QDialog):
    def __init__(self, parent, wa: Workarea, lib: Library | None, cell: Cell | None):
        super().__init__(parent)
        self.setWindowTitle("New Cell View")
        self.setMinimumWidth(380)
        self.wa = wa
        self.lib = QComboBox()
        self.libs = _writable(wa)
        self.lib.addItems([lb.name for lb in self.libs])
        if lib and lib.name in [lb.name for lb in self.libs]:
            self.lib.setCurrentText(lib.name)
        self.cell = QComboBox(editable=True)
        self.view = QComboBox()
        self.view.addItems([vt.name for vt in CREATABLE])
        self.open_after = QCheckBox("Open after creating", checked=True)
        self.lib.currentTextChanged.connect(self._cells)
        self._cells()
        if cell and not cell.library.readonly:
            self.cell.setCurrentText(cell.name)
        else:
            self.cell.setCurrentText("")
        form = QFormLayout()
        form.addRow("Library", self.lib)
        form.addRow("Cell", self.cell)
        form.addRow("View", self.view)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.open_after)
        self.buttons = _buttons(self)
        lay.addWidget(self.buttons)
        self.cell.editTextChanged.connect(self._validate)
        self._validate()

    def _cells(self) -> None:
        lib = self.library()
        text = self.cell.currentText()
        self.cell.clear()
        self.cell.addItems([c.name for c in lib.cells()] if lib else [])
        self.cell.setCurrentText(text)

    def _validate(self) -> None:
        ok = bool(NAME_RE.match(self.cell.currentText())) and self.library() is not None
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)

    def library(self) -> Library | None:
        return next((lb for lb in self.libs if lb.name == self.lib.currentText()), None)

    def values(self):
        vt = next(vt for vt in CREATABLE if vt.name == self.view.currentText())
        return self.library(), self.cell.currentText().strip(), vt, self.open_after.isChecked()


class CopyCellDialog(QDialog):
    def __init__(self, parent, wa: Workarea, cell: Cell):
        super().__init__(parent)
        self.setWindowTitle(f"Copy Cell {cell.key}")
        self.setMinimumWidth(380)
        self.libs = _writable(wa)
        self.lib = QComboBox()
        self.lib.addItems([lb.name for lb in self.libs])
        if not cell.library.readonly:
            self.lib.setCurrentText(cell.library.name)
        default = cell.name.replace("_ASAP7_75t_", "_").lower() if cell.library.readonly else f"{cell.name}_copy"
        self.name = QLineEdit(default)
        form = QFormLayout()
        form.addRow("To library", self.lib)
        form.addRow("New cell name", self.name)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        self.buttons = _buttons(self)
        lay.addWidget(self.buttons)
        self.name.textChanged.connect(
            lambda t: self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(NAME_RE.match(t))))

    def values(self):
        lib = next((lb for lb in self.libs if lb.name == self.lib.currentText()), None)
        return lib, self.name.text().strip()
