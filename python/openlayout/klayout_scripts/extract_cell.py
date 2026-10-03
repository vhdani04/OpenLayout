# Copy one cell (with its hierarchy) out of a multi-cell layout into a new file.
#   -rd src=<library.gds> -rd cell=<name> -rd file=<out.gds> -rd new_name=<top cell name in out>
import pya

src_layout = pya.Layout()
src_layout.read(src)
src_cell = src_layout.cell(cell)
if src_cell is None:
    raise RuntimeError(f"ERROR: cell {cell} not found in {src}")

out = pya.Layout()
out.dbu = src_layout.dbu
out.technology_name = "asap7"
top = out.create_cell(new_name)
top.copy_tree(src_cell)
out.write(file)
