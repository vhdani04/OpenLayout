# Rename a cell inside a layout file in place.   -rd file=<path> -rd cell=<old> -rd new_name=<new>
import pya

layout = pya.Layout()
layout.read(file)
c = layout.cell(cell)
if c is None:
    raise RuntimeError(f"ERROR: cell {cell} not found in {file}")
c.name = new_name
layout.write(file)
