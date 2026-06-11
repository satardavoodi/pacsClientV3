"""Verify the FROZEN PYZ bytecode (what actually runs) carries the current MPR
geometry fixes — NOT just the on-disk engine/modules .py (which under
module_collection_mode 'pyz+py' is not the import source).

Usage:  python verify_mpr_in_pyz.py <path-to-AIPacs.exe>

Exit 0 + PYZ_MPR_OK when every marker is present in the marshalled code of the
target modules; exit 2 + PYZ_MPR_STALE listing the misses otherwise.
"""
from __future__ import annotations

import marshal
import sys
import zlib
from pathlib import Path

# (module key in the PYZ, marker substrings that MUST appear in its code names/consts)
TARGETS = {
    "modules.mpr.zeta_mpr.mpr_viewer._mpr_orientation": ("_view_axes", "_anat_look_axis", "_anatomical_camera"),
    "modules.mpr.zeta_mpr.mpr_viewer._mpr_crosshair_render": ("_force_crosshair_on_top",),
    "modules.mpr.zeta_mpr.mpr_viewer._mpr_views": ("_apply_native_plane_interpolation",),
    "modules.mpr.zeta_mpr.mpr_viewer.widget": ("layout_views", "slab_mode"),
}


def _strings_in_code(code, acc: set) -> None:
    for c in code.co_names:
        acc.add(c)
    for c in code.co_varnames:
        acc.add(c)
    for const in code.co_consts:
        if isinstance(const, str):
            acc.add(const)
        elif hasattr(const, "co_code"):
            _strings_in_code(const, acc)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: verify_mpr_in_pyz.py <AIPacs.exe>")
        return 64
    exe = Path(sys.argv[1])
    if not exe.exists():
        print(f"PYZ_MPR_ERROR exe not found: {exe}")
        return 64

    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    car = CArchiveReader(str(exe))
    # Locate the PYZ entry inside the CArchive (typename 'z' or name PYZ-00.pyz).
    pyz_name = None
    toc = car.toc
    names = list(toc) if hasattr(toc, "__iter__") else []
    for entry in names:
        nm = entry if isinstance(entry, str) else getattr(entry, "name", None)
        if nm and "PYZ" in str(nm):
            pyz_name = nm
            break
    if pyz_name is None:
        # Fallback: some versions key by 'PYZ-00.pyz'
        pyz_name = "PYZ-00.pyz"

    data = car.extract(pyz_name)
    if isinstance(data, tuple):
        data = data[1]
    tmp = exe.parent / "_pyz_extract.tmp"
    tmp.write_bytes(data)
    try:
        pyz = ZlibArchiveReader(str(tmp))
        misses = []
        checked = 0
        for mod, markers in TARGETS.items():
            try:
                raw = pyz.extract(mod)
            except Exception as exc:  # noqa: BLE001
                misses.append(f"{mod}: NOT IN PYZ ({exc!r})")
                continue
            blob = raw[1] if isinstance(raw, tuple) else raw
            if isinstance(blob, (bytes, bytearray)):
                try:
                    blob = zlib.decompress(blob)
                except Exception:
                    pass
                code = marshal.loads(blob)
            else:
                code = blob  # already a code object
            checked += 1
            acc: set = set()
            _strings_in_code(code, acc)
            for m in markers:
                if m not in acc:
                    misses.append(f"{mod}: MISSING marker '{m}'")
        if misses:
            print("PYZ_MPR_STALE")
            for m in misses:
                print("  " + m)
            return 2
        print(f"PYZ_MPR_OK  ({checked} modules, all markers present in frozen bytecode)")
        return 0
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
