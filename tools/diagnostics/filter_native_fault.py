"""
filter_native_fault.py — make native_fault.log readable.

faulthandler logs EVERY native fault it sees, including the **benign first-chance**
`0x8001010d` (RPC_E_WRONGTHREAD) that Qt/qasync raises ~once per startup and the app
always survives. Across many sessions those benign dumps bury the faults that matter
(`0xC0000005` access violation, `0xC0000409` fail-fast, stack overflow), which made the
other-PC crash review harder than it should have been.

This tool is **offline and READ-ONLY**: it parses `native_fault.log`, drops the benign
dump blocks, and writes a clean `native_fault_crashes.log` containing only real crashes.
It never modifies `native_fault.log` and changes nothing about the running app.

Usage:
    .venv\\Scripts\\python.exe tools\\diagnostics\\filter_native_fault.py
    ... --logs-dir "C:\\path\\to\\logs" --benign 0x8001010d
    ... --in <file> --out <file>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_HDR = re.compile(r"Windows fatal exception:\s*(.+)", re.IGNORECASE)
# Benign first-chance faults to drop by default (app survives them).
_DEFAULT_BENIGN = {"0x8001010d"}


def _code_of(header_text: str) -> str:
    """Normalize a 'Windows fatal exception: ...' description to a comparable code."""
    h = header_text.strip().lower()
    m = re.search(r"code\s*(0x[0-9a-f]+)", h)
    if m:
        return m.group(1)
    if "access violation" in h:
        return "0xc0000005"      # access violation
    if "stack overflow" in h:
        return "stack_overflow"
    if "in page error" in h:
        return "in_page_error"
    return h[:48] or "unknown"


def parse_blocks(text: str):
    """Split native_fault.log into (code, block_text) dump blocks.

    A faulthandler dump ends with a 'Windows fatal exception: ...' line (the thread
    stacks precede it), so blocks are delimited by those lines.
    """
    lines = text.splitlines(keepends=True)
    fault_idxs = [i for i, ln in enumerate(lines) if _HDR.search(ln)]
    blocks = []
    start = 0
    for fi in fault_idxs:
        code = _code_of(_HDR.search(lines[fi]).group(1))
        blocks.append((code, "".join(lines[start:fi + 1])))
        start = fi + 1
    tail = "".join(lines[start:])
    if tail.strip():
        blocks.append((None, tail))  # trailing stacks with no fault line yet — keep
    return blocks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Filter benign faults out of native_fault.log (read-only).")
    ap.add_argument("--logs-dir", default=None, help="logs directory (default: <repo>/user_data/logs)")
    ap.add_argument("--in", dest="infile", default=None, help="input native_fault.log path")
    ap.add_argument("--out", dest="outfile", default=None, help="output crashes-only path")
    ap.add_argument("--benign", nargs="*", default=sorted(_DEFAULT_BENIGN),
                    help="exception codes to drop (default: 0x8001010d)")
    a = ap.parse_args(argv)

    if a.infile:
        src = Path(a.infile)
    else:
        logs = Path(a.logs_dir) if a.logs_dir else (Path(__file__).resolve().parents[2] / "user_data" / "logs")
        src = logs / "native_fault.log"
    if not src.exists():
        print(f"[filter] native_fault.log not found: {src}", file=sys.stderr)
        return 2
    out = Path(a.outfile) if a.outfile else src.with_name("native_fault_crashes.log")
    benign = {b.strip().lower() for b in a.benign}

    text = src.read_text(encoding="utf-8", errors="replace")
    blocks = parse_blocks(text)

    counts: dict = {}
    kept_blocks = []
    dropped = 0
    for code, block in blocks:
        key = code if code is not None else "(incomplete)"
        counts[key] = counts.get(key, 0) + 1
        if code is not None and code in benign:
            dropped += 1
            continue
        kept_blocks.append(block)

    out.write_text("".join(kept_blocks), encoding="utf-8")

    total = len(blocks)
    kept = len(kept_blocks)
    print("=" * 64)
    print(f"native_fault filter — source: {src.name}  ({src.stat().st_size} bytes)")
    print("=" * 64)
    print(f"Total fault dumps : {total}")
    for code in sorted(counts, key=lambda c: -counts[c]):
        mark = "  (benign — dropped)" if code in benign else ""
        print(f"  {code:<16} : {counts[code]}{mark}")
    print(f"Dropped (benign)  : {dropped}")
    print(f"Kept (real/other) : {kept}")
    print(f"Wrote crashes-only -> {out}")
    real = kept - counts.get("(incomplete)", 0)
    print(f"\nREAL CRASH DUMPS remaining: {max(real, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
