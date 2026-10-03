# Create an empty ASAP7 layout with a single top cell.   -rd file=<path.gds> -rd cell=<name>
import pya

layout = pya.Layout()
layout.dbu = pya.Technology.technology_by_name("asap7").dbu
layout.technology_name = "asap7"
layout.create_cell(cell)
layout.write(file)
