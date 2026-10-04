# Summary of a KLayout report database (DRC / LVS results): one line per rule with markers.
#   klayout -b -r rdb_summary.py -rd rdb=cell.drc.lyrdb [-rd title=DRC] [-rd cell=NAME]
# The last line is machine readable: "RESULT <title> <cell> violations=<n> rules=<m>".
import pya

title = globals().get("title") or "DRC"
rdb_ = pya.ReportDatabase("")
rdb_.load(rdb)
cell_ = globals().get("cell") or rdb_.top_cell_name or "?"
counts = {}
for cat in rdb_.each_category():
    if cat.num_items() > 0:
        counts[cat.name()] = (cat.num_items(), cat.description)
total = sum(n for n, _ in counts.values())
if total:
    print(f"{title} {cell_}: {total} violation(s) of {len(counts)} rule(s)")
    for name in sorted(counts):
        n, desc = counts[name]
        print(f"  {name:28s} {n:6d}  {desc}")
else:
    print(f"{title} {cell_}: clean")
print(f"  results: {rdb}")
print(f"RESULT {title} {cell_} violations={total} rules={len(counts)}")
