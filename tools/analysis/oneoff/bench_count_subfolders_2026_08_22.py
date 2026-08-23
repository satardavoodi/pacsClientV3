"""One-off: how expensive is count_subfolders_with_dicom, and does an
early-exit os.scandir walk return the SAME answer for every local study?

Read-only.  2026-08-22 server-search freeze.
"""
import io
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
SOURCE = Path(ROOT) / "user_data" / "patients" / "dicom"
EXTS = {".dcm", ".dicom"}


def current(folder_path):
    """Verbatim copy of the shipped implementation."""
    root = Path(folder_path)
    if not root.is_dir():
        return 0
    count = 0
    for sub in root.iterdir():
        if sub.is_dir():
            if any(p.is_file() and p.suffix.lower() in EXTS for p in sub.rglob('*')):
                count += 1
    return count


def _has_dicom(dir_path) -> bool:
    """Early-exit: direct children first (where series files actually live),
    then descend. Same verdict, no full recursive materialisation."""
    pending = [dir_path]
    while pending:
        current_dir = pending.pop()
        subdirs = []
        try:
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            if os.path.splitext(entry.name)[1].lower() in EXTS:
                                return True
                        elif entry.is_dir(follow_symlinks=False):
                            subdirs.append(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue
        pending.extend(subdirs)
    return False


def proposed(folder_path):
    count = 0
    try:
        with os.scandir(folder_path) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False) and _has_dicom(entry.path):
                        count += 1
                except OSError:
                    continue
    except (OSError, ValueError):
        return 0
    return count


def main():
    studies = []
    try:
        for name in sorted(os.listdir(SOURCE)):
            p = SOURCE / name
            if p.is_dir():
                studies.append(p)
    except OSError as exc:
        print("cannot list", SOURCE, exc)
        return
    print("local study folders: %d" % len(studies))
    sample = studies[:400]

    t0 = time.perf_counter()
    cur = [current(p) for p in sample]
    t_cur = time.perf_counter() - t0

    t0 = time.perf_counter()
    new = [proposed(p) for p in sample]
    t_new = time.perf_counter() - t0

    mismatches = [(str(p), a, b) for p, a, b in zip(sample, cur, new) if a != b]
    print("sampled: %d studies" % len(sample))
    print("  current : %8.1f ms total   %6.2f ms/study" % (t_cur * 1000, t_cur * 1000 / max(1, len(sample))))
    print("  proposed: %8.1f ms total   %6.2f ms/study" % (t_new * 1000, t_new * 1000 / max(1, len(sample))))
    print("  speedup : %.1fx" % (t_cur / t_new if t_new else 0.0))
    print("  verdict mismatches: %d" % len(mismatches))
    for path, a, b in mismatches[:10]:
        print("     %s  current=%s proposed=%s" % (path.replace(ROOT, "."), a, b))

    # Second pass = warm cache; the freeze happens on a COLD one, so report both.
    t0 = time.perf_counter()
    for p in sample:
        current(p)
    print("  current (warm): %8.1f ms" % ((time.perf_counter() - t0) * 1000))
    t0 = time.perf_counter()
    for p in sample:
        proposed(p)
    print("  proposed (warm): %8.1f ms" % ((time.perf_counter() - t0) * 1000))


if __name__ == "__main__":
    main()
