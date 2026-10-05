"""Workarea model: libraries, cells and views.

This mirrors Virtuoso's design hierarchy. A workarea's `libs.def` (like cds.lib) defines
libraries; a library is a directory of cells; a cell is a directory `<lib>/<cell>/` whose views
are files named after the cell (`<cell>.sch`, `<cell>.sym`, `<cell>.gds`, ...).

A library directory may contain `openlayout.lib.json` with metadata:
  {"readonly": true, "description": "...", "layout_gds": "$VAR/path/to/library.gds"}
`layout_gds` gives every cell of the library a layout view inside that (multi-cell) GDS file,
which is how the PDK standard-cell layouts are exposed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

LIBS_DEF = "libs.def"
LIB_META = "openlayout.lib.json"
STATE_DIR = ".openlayout"
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
SCRIPTS = Path(__file__).resolve().parent / "klayout_scripts"
LINK_SUFFIX = ".ol.json"  # schematic link written by schematic-driven layout generation


class WorkareaError(Exception):
    pass


@dataclass(frozen=True)
class ViewType:
    name: str
    suffixes: tuple
    tool: str  # "xschem" | "klayout" | "text"


SCHEMATIC = ViewType("schematic", (".sch",), "xschem")
SYMBOL = ViewType("symbol", (".sym",), "xschem")
LAYOUT = ViewType("layout", (".gds", ".oas"), "klayout")
NETLIST = ViewType("netlist", (".spice", ".cdl"), "text")
OLSIM = ViewType("olsim", (".olsim",), "olsim")   # simulation setup (openlayout.olsim)
VIEW_TYPES = [SCHEMATIC, SYMBOL, LAYOUT, NETLIST, OLSIM]
CREATABLE = [SCHEMATIC, SYMBOL, LAYOUT, OLSIM]


def view_type(name: str) -> ViewType:
    for vt in VIEW_TYPES:
        if vt.name == name:
            return vt
    raise WorkareaError(f"unknown view type '{name}'")


def check_name(kind: str, name: str) -> None:
    if not NAME_RE.match(name or ""):
        raise WorkareaError(f"invalid {kind} name '{name}': use letters, digits and _, starting with a letter")


@dataclass
class View:
    cell: "Cell"
    type: ViewType
    path: Path
    gds_cell: str | None = None  # cell inside a multi-cell layout file (library layouts)

    @property
    def name(self) -> str:
        return self.type.name

    @property
    def readonly(self) -> bool:
        return self.cell.library.readonly

    def __repr__(self) -> str:
        return f"<View {self.cell.library.name}/{self.cell.name}/{self.name}>"


@dataclass
class Cell:
    library: "Library"
    name: str

    @property
    def path(self) -> Path:
        return self.library.path / self.name

    @property
    def key(self) -> str:
        return f"{self.library.name}/{self.name}"

    def views(self) -> list[View]:
        found = []
        for vt in VIEW_TYPES:
            for suffix in vt.suffixes:
                p = self.path / f"{self.name}{suffix}"
                if p.is_file():
                    found.append(View(self, vt, p))
                    break
        if self.library.layout_gds and not any(v.type is LAYOUT for v in found):
            found.append(View(self, LAYOUT, self.library.layout_gds, gds_cell=self.name))
        return found

    def view(self, name: str) -> View | None:
        return next((v for v in self.views() if v.name == name), None)

    def __repr__(self) -> str:
        return f"<Cell {self.key}>"


@dataclass
class Library:
    name: str
    path: Path
    source: Path  # the libs.def that defines it
    readonly: bool = False
    description: str = ""
    layout_gds: Path | None = None

    @property
    def exists(self) -> bool:
        return self.path.is_dir()

    def cells(self) -> list[Cell]:
        if not self.exists:
            return []
        return [Cell(self, d.name) for d in sorted(self.path.iterdir(), key=lambda p: p.name.lower())
                if d.is_dir() and not d.name.startswith(".")]

    def cell(self, name: str) -> Cell | None:
        return Cell(self, name) if (self.path / name).is_dir() else None

    def __repr__(self) -> str:
        return f"<Library {self.name}{' (read-only)' if self.readonly else ''}>"


def _expand(text: str) -> str:
    return os.path.expandvars(os.path.expanduser(text))


def read_libs_def(path: Path, _seen: set | None = None) -> list[Library]:
    """Parse a libs.def file (DEFINE/INCLUDE lines, $VARS, paths relative to the file)."""
    seen = _seen if _seen is not None else set()
    path = path.resolve()
    if path in seen or not path.is_file():
        return []
    seen.add(path)
    libs = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        kw, *args = line.split()
        if kw == "DEFINE" and len(args) >= 2:
            lib_path = (path.parent / _expand(args[1])).resolve()
            libs.append(_library(args[0], lib_path, path))
        elif kw == "INCLUDE" and args:
            libs.extend(read_libs_def(path.parent / _expand(args[0]), seen))
    return libs


def _library(name: str, path: Path, source: Path) -> Library:
    lib = Library(name=name, path=path, source=source)
    meta_file = path / LIB_META
    if meta_file.is_file():
        meta = json.loads(meta_file.read_text())
        lib.readonly = bool(meta.get("readonly", False))
        lib.description = meta.get("description", "")
        if meta.get("layout_gds"):
            lib.layout_gds = Path(_expand(meta["layout_gds"]))
    return lib


class Workarea:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        if not (self.root / LIBS_DEF).is_file():
            raise WorkareaError(f"{self.root} is not a workarea (no {LIBS_DEF})")
        self._libs: list[Library] | None = None

    # ---- discovery / creation -------------------------------------------------------------
    @staticmethod
    def find(start: str | Path = ".") -> "Workarea | None":
        d = Path(start).expanduser().resolve()
        for p in (d, *d.parents):
            if (p / LIBS_DEF).is_file():
                return Workarea(p)
        return None

    @staticmethod
    def create(root: str | Path, first_library: str | None = None) -> "Workarea":
        root = Path(root).expanduser().resolve()
        if (root / LIBS_DEF).exists():
            raise WorkareaError(f"{root} is already a workarea")
        template = Path(os.environ["OPENLAYOUT_HOME"]) / "templates" / "workarea"
        root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(template, root, dirs_exist_ok=True)
        wa = Workarea(root)
        wa.new_library(first_library or root.name)
        return wa

    # ---- libraries ------------------------------------------------------------------------
    @property
    def libs_def(self) -> Path:
        return self.root / LIBS_DEF

    def reload(self) -> None:
        self._libs = None

    def libraries(self) -> list[Library]:
        if self._libs is None:
            self._libs = read_libs_def(self.libs_def)
        return self._libs

    def library(self, name: str) -> Library | None:
        return next((lib for lib in self.libraries() if lib.name == name), None)

    def cell_for_path(self, path: str | Path, cell_name: str | None = None) -> Cell | None:
        """The cell a file belongs to: <lib>/<cell>/<file>, or `cell_name` inside a library's GDS."""
        p = Path(path).expanduser().resolve()
        for lib in self.libraries():
            if lib.layout_gds and cell_name and p == lib.layout_gds.resolve():
                return lib.cell(cell_name)
            try:
                rel = p.relative_to(lib.path.resolve())
            except ValueError:
                continue
            if rel.parts:
                return lib.cell(rel.parts[0])
        return None

    def new_library(self, name: str) -> Library:
        check_name("library", name)
        if self.library(name):
            raise WorkareaError(f"library '{name}' already exists")
        (self.root / "libraries" / name).mkdir(parents=True, exist_ok=True)
        with self.libs_def.open("a") as f:
            f.write(f"DEFINE {name:<16} libraries/{name}\n")
        self.reload()
        return self.library(name)

    # ---- cells and views ------------------------------------------------------------------
    def _writable(self, lib: Library) -> None:
        if lib.readonly:
            raise WorkareaError(f"library '{lib.name}' is read-only")

    def new_view(self, lib: Library, cell_name: str, vt: ViewType) -> View:
        self._writable(lib)
        check_name("cell", cell_name)
        cell = Cell(lib, cell_name)
        if cell.view(vt.name):
            raise WorkareaError(f"{lib.name}/{cell_name} already has a {vt.name} view")
        cell.path.mkdir(parents=True, exist_ok=True)
        path = cell.path / f"{cell_name}{vt.suffixes[0]}"
        if vt is SCHEMATIC:
            path.write_text(XSCHEM_HEADER + "K {}\nV {}\nS {}\nE {}\n")
        elif vt is SYMBOL:
            # Like Virtuoso's "from cellview": with a schematic, build the symbol from its pins;
            # otherwise start from an empty body with the red selection box (outline only).
            from .symbolgen import BLANK, schematic_pins, symbol_text
            sch = cell.view("schematic")
            pins = schematic_pins(sch.path) if sch else []
            path.write_text(symbol_text(pins) if pins else BLANK)
        elif vt is LAYOUT:
            run_klayout_script("new_layout.py", file=path, cell=cell_name)
        elif vt is OLSIM:
            # a setup whose test simulates this cell's schematic (the testbench)
            from .olsim.setup import default_setup
            default_setup(lib.name, cell_name).save(path)
        else:
            raise WorkareaError(f"cannot create {vt.name} views")
        return View(cell, vt, path)

    def copy_cell(self, cell: Cell, dst_lib: Library, dst_name: str) -> Cell:
        self._writable(dst_lib)
        check_name("cell", dst_name)
        dst = Cell(dst_lib, dst_name)
        if dst.path.exists():
            raise WorkareaError(f"{dst.key} already exists")
        dst.path.mkdir(parents=True)
        for v in cell.views():
            if v.gds_cell:  # layout lives in a shared library GDS: extract just this cell
                run_klayout_script("extract_cell.py", src=v.path, cell=v.gds_cell,
                                   file=dst.path / f"{dst_name}.gds", new_name=dst_name)
                continue
            target = dst.path / f"{dst_name}{v.path.suffix}"
            shutil.copy2(v.path, target)
            if v.type is LAYOUT and cell.name != dst_name:
                run_klayout_script("rename_cell.py", file=target, cell=cell.name, new_name=dst_name)
        link = cell.path / f"{cell.name}{LINK_SUFFIX}"
        if link.is_file():
            shutil.copy2(link, dst.path / f"{dst_name}{LINK_SUFFIX}")
        return dst

    def rename_cell(self, cell: Cell, new_name: str) -> Cell:
        self._writable(cell.library)
        check_name("cell", new_name)
        new = Cell(cell.library, new_name)
        if new.path.exists():
            raise WorkareaError(f"{new.key} already exists")
        views = cell.views()
        cell.path.rename(new.path)
        for v in views:
            old_file = new.path / v.path.name
            new_file = new.path / f"{new_name}{v.path.suffix}"
            old_file.rename(new_file)
            if v.type is LAYOUT:
                run_klayout_script("rename_cell.py", file=new_file, cell=cell.name, new_name=new_name)
        link = new.path / f"{cell.name}{LINK_SUFFIX}"
        if link.is_file():
            link.rename(new.path / f"{new_name}{LINK_SUFFIX}")
        return new

    def delete(self, target: Cell | View) -> Path:
        """Move a cell or view to <workarea>/.trash/<timestamp>/ (recoverable)."""
        cell = target if isinstance(target, Cell) else target.cell
        self._writable(cell.library)
        if isinstance(target, View) and target.gds_cell:
            raise WorkareaError("library layouts cannot be deleted")
        trash = self.root / ".trash" / time.strftime("%Y%m%d-%H%M%S") / cell.library.name
        trash.mkdir(parents=True, exist_ok=True)
        src = target.path
        dst = trash / (cell.name if isinstance(target, Cell) else f"{cell.name}/{src.name}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        if isinstance(target, View) and not any(cell.path.iterdir()):
            cell.path.rmdir()
        return dst

    # ---- per-cell run state (netlist / sim / drc / lvs results) ----------------------------
    @property
    def state_file(self) -> Path:
        return self.root / STATE_DIR / "state.json"

    def state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return {}

    def set_state(self, cell: Cell, step: str, ok: bool, detail: str = "") -> None:
        state = self.state()
        state.setdefault(cell.key, {})[step] = {"ok": ok, "time": time.time(), "detail": detail}
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=1))

    def cell_state(self, cell: Cell) -> dict:
        return self.state().get(cell.key, {})

    # ---- hub session (how the tools find the running hub) ----------------------------------
    @property
    def session_file(self) -> Path:
        return self.root / STATE_DIR / "session.json"

    def session(self) -> dict:
        try:
            return json.loads(self.session_file.read_text())
        except (OSError, ValueError):
            return {}

    # ---- derived paths --------------------------------------------------------------------
    def netlist_dir(self) -> Path:
        return self.root / "sim" / "netlist"

    def run_dir(self, cell: Cell) -> Path:
        return self.root / "sim" / cell.library.name / cell.name

    def verify_dir(self, cell: Cell) -> Path:
        """DRC / LVS results of a cell (kept out of the library, which may be read-only)."""
        return self.root / "verify" / cell.library.name / cell.name


XSCHEM_HEADER = "v {xschem version=3.4.8RC file_version=1.3}\nG {}\n"


def run_klayout_script(script: str, **params) -> str:
    """Run one of the bundled KLayout batch scripts with -rd parameters."""
    cmd = ["klayout", "-b", "-r", str(SCRIPTS / script)]
    for k, v in params.items():
        cmd += ["-rd", f"{k}={v}"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or "ERROR" in res.stdout + res.stderr:
        raise WorkareaError(f"klayout {script} failed: {(res.stdout + res.stderr).strip()[-500:]}")
    return res.stdout
