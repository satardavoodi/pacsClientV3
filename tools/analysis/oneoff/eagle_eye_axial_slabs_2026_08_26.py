"""Is the model's level map consistent with the axial slice geometry?"""
import json
import sys
from pathlib import Path

s = Path(sys.argv[1])
m = json.load(open(s / "Axial" / "manifest.json", encoding="utf-8"))
zs = []
for c in m["captures"]:
    p = c["panes"]["axial_t2"]["position"]
    zs.append((c["index"], round(float(p[2]), 1)))

print("axial frames:", len(zs))
print("z span: %.1f -> %.1f mm (%.1f mm total)" % (zs[0][1], zs[-1][1], zs[0][1] - zs[-1][1]))
print()
print("idx      z      gap")
prev = None
for i, z in zs:
    gap = "" if prev is None else "%6.1f" % (prev - z)
    print("%3d  %8.1f  %s" % (i, z, gap))
    prev = z

gaps = [round(zs[i - 1][1] - zs[i][1], 1) for i in range(1, len(zs))]
uniq = sorted(set(gaps))
print()
print("distinct gaps:", uniq)
print("uniform spacing:", len(uniq) == 1)
