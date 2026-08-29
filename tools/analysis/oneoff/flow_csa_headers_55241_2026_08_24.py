"""Minimal Siemens SV10 CSA2 parser + full tag list, for the flow series of 55241.

Answers "did our pipeline damage the Siemens private headers?". Parses
(0029,1010) CSA Image Header Info and (0029,1020) CSA Series Header Info and
prints every flow/VENC/velocity/phase entry, plus the ASCCONV sAngio.sFlowArray
protocol values. Measured result on our export: FlowVenc=150.00000000,
FlowEncodingDirectionString=v150_through, VelocityEncodingDirectionN4 present,
PhaseContrastN4=YES -- i.e. INTACT.
"""

import io, re, struct, sys
import pydicom
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import warnings; warnings.filterwarnings("ignore")

def parse_csa(buf):
    """Minimal SV10 CSA2 parser -> {name: [values]}"""
    out = {}
    if not buf or buf[:4] != b"SV10":
        return out
    n_tags = struct.unpack("<I", buf[8:12])[0]
    if not (0 < n_tags < 4096):
        return out
    pos = 16
    for _ in range(n_tags):
        if pos + 84 > len(buf):
            break
        name = buf[pos:pos+64].split(b"\x00")[0].decode("ascii", "replace")
        n_items = struct.unpack("<I", buf[pos+76:pos+80])[0]
        pos += 84
        vals = []
        for _i in range(n_items):
            if pos + 16 > len(buf):
                break
            lens = struct.unpack("<4I", buf[pos:pos+16])
            pos += 16
            ln = lens[1]
            if ln:
                v = buf[pos:pos+ln].split(b"\x00")[0].decode("ascii", "replace")
                if v:
                    vals.append(v)
            pos += (ln + 3) // 4 * 4
        out[name] = vals
    return out

BASE = Path(r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\patients\dicom\1.3.12.2.1107.5.2.46.174759.30000026082304314150700000025")

for sn in (45, 46, 47):
    f = sorted((BASE/str(sn)).glob("*.dcm"))[0]
    ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
    print("=" * 90)
    print("SERIES %d  %s   (%s)" % (sn, ds.get("SeriesDescription"), f.name))
    for tag, label in (((0x0029,0x1010), "CSA IMAGE"), ((0x0029,0x1020), "CSA SERIES")):
        el = ds.get(tag)
        if el is None or not el.value:
            print("  %s : ABSENT" % label); continue
        csa = parse_csa(bytes(el.value))
        print("  %s : %d bytes -> %d parsed entries" % (label, len(el.value), len(csa)))
        interesting = [k for k in csa if re.search(r"flow|venc|velocit|phase|bandwidth|Direction", k, re.I)]
        for k in sorted(interesting):
            if csa[k]:
                print("      %-34s = %s" % (k, csa[k][:6]))
    # ASCCONV VENC
    el = ds.get((0x0029,0x1020))
    if el is not None and el.value:
        txt = bytes(el.value).decode("latin-1", "replace")
        for m in re.finditer(r"(sAngio\.sFlowArray\.asElm\[\d+\]\.\w+|sAngio\.sFlowArray\.lSize)\s*=\s*(\S+)", txt):
            print("      ASCCONV %-42s = %s" % (m.group(1), m.group(2)))
print()
print("=" * 90)
f = sorted((BASE/"47").glob("*.dcm"))[0]
ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
els = list(ds)
print("FULL TAG LIST of series 47 instance 1  (%d top-level elements)" % len(els))
for e in els:
    v = e.value
    s = ("<%d bytes>" % len(v)) if isinstance(v, bytes) else str(v)
    print("  %s  %-4s %-42s %s" % (e.tag, e.VR, (e.name or "")[:42], s[:70]))
