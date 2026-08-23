"""One-off: prove the YBR fix changes NOTHING for studies that already worked.

Decodes one instance from many local series twice — once with the fix disabled,
once enabled — in two subprocesses, and compares the arrays byte-for-byte.
Any study whose bytes change is reported with its photometric interpretation.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
DB = os.path.join(ROOT, "user_data", "database", "dicom.db")
LIMIT = int(os.environ.get("SWEEP_LIMIT", "220"))


def sample_files():
    con = sqlite3.connect("file:///" + DB.replace("\\", "/") + "?mode=ro", uri=True)
    rows = con.execute(
        "SELECT series_path FROM series WHERE series_path IS NOT NULL "
        "ORDER BY series_pk DESC").fetchall()
    con.close()
    out = []
    for (sp,) in rows:
        if len(out) >= LIMIT:
            break
        try:
            names = sorted(os.listdir(sp))
        except OSError:
            continue
        for n in names:
            p = os.path.join(sp, n)
            if os.path.isfile(p):
                out.append(p)
                break
    return out


def child():
    import numpy as np
    import pydicom
    sys.path.insert(0, ROOT)
    from modules.viewer.fast.decode_service import _decode_worker
    result = {}
    for path in json.loads(sys.stdin.read()):
        try:
            hdr = pydicom.dcmread(path, stop_before_pixels=True, force=True)
            arr = _decode_worker(
                path, int(getattr(hdr, "Rows", 0) or 0),
                int(getattr(hdr, "Columns", 0) or 0), 1.0, 0.0,
                str(getattr(hdr, "PhotometricInterpretation", "")),
                int(getattr(hdr, "SamplesPerPixel", 1) or 1))
            a = np.ascontiguousarray(arr)
            result[path] = [hashlib.sha1(a.tobytes()).hexdigest(),
                            str(getattr(hdr, "PhotometricInterpretation", "")),
                            int(getattr(hdr, "SamplesPerPixel", 1) or 1)]
        except Exception as exc:              # noqa: BLE001
            result[path] = ["ERR:%s" % type(exc).__name__, "?", 0]
    print(json.dumps(result))


def run(files, env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    env["AIPACS_SWEEP_CHILD"] = "1"
    proc = subprocess.run(
        [PY, "-W", "ignore", os.path.abspath(__file__)],
        input=json.dumps(files), capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        print(proc.stderr[-3000:])
        raise SystemExit(proc.returncode)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main():
    files = sample_files()
    print("sampled %d instances (one per series)" % len(files))
    off = run(files, {"AIPACS_DICOM_YBR422_FIX": "0", "AIPACS_DICOM_YBR_TO_RGB": "0"})
    on = run(files, {"AIPACS_DICOM_YBR422_FIX": "1", "AIPACS_DICOM_YBR_TO_RGB": "1"})

    changed, same, errs = [], 0, 0
    for path in files:
        a, b = off.get(path), on.get(path)
        if a is None or b is None:
            continue
        if a[0].startswith("ERR") or b[0].startswith("ERR"):
            errs += 1
            continue
        if a[0] == b[0]:
            same += 1
        else:
            changed.append((path, b[1], b[2]))

    print("identical before/after : %d" % same)
    print("changed by the fix     : %d" % len(changed))
    print("decode errors (both)   : %d" % errs)
    by_photo = {}
    for _p, photo, spp in changed:
        by_photo[(photo, spp)] = by_photo.get((photo, spp), 0) + 1
    for key, count in sorted(by_photo.items()):
        print("   changed: photometric=%-14s spp=%d  n=%d" % (key[0], key[1], count))
    for path, photo, spp in changed[:10]:
        print("      %s  (%s spp=%d)" % (path.replace(ROOT, "."), photo, spp))


if __name__ == "__main__":
    if os.environ.get("AIPACS_SWEEP_CHILD") == "1":
        child()
    else:
        main()
