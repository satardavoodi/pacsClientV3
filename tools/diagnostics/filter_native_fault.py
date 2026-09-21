"""
filter_native_fault.py — filter native diagnostic records without losing their stacks.

Fault headers START records, followed by thread stacks. The default exclusion
0x8001010d reduces frequently observed non-terminal COM noise, but a code alone
does not establish that an event was harmless or that a retained event killed a
process. Correlate with Windows events and process lifecycle evidence.

This tool reads the source without modifying it and writes a separate filtered
report. The historical output filename native_fault_crashes.log is retained for
compatibility, not as a claim that every retained record is a terminal crash.
Session headers are preserved as unclassified context: a shared multi-process
log's preceding header is NOT authoritative attribution for the next dump.

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

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from PacsClient.utils.native_fault_log import discover_native_fault_logs, native_fault_log_pid

_HDR = re.compile(r"^Windows fatal exception:\s*(.+)", re.IGNORECASE)
_PYTHON_HDR = re.compile(r"^Fatal Python error:\s*(.+)", re.IGNORECASE)
_TIMEOUT_HDR = re.compile(r"^Timeout \([^\r\n]*\)!", re.IGNORECASE)
_SESSION_HDR = re.compile(r"^=== session start\b")
_SOURCE_HDR = re.compile(r"^=== source file\b")
# Historical default exclusion; not proof of event harmlessness.
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
    """Return (code, original_text) records with header-before-stack boundaries.

    None denotes context/unclassified text, not a proved incomplete crash. Keep
    watchdog and Python-fatal headers separate so excluding COM cannot discard
    their following stacks. Preserve all input characters when nothing is filtered.
    Interleaved writers cannot be untangled here; never infer a PID from context.
    """
    blocks = []
    buffer = []
    code = None
    for line in text.splitlines(keepends=True):
        windows = _HDR.match(line)
        python = _PYTHON_HDR.match(line)
        timeout = _TIMEOUT_HDR.match(line)
        session = _SESSION_HDR.match(line) or _SOURCE_HDR.match(line)
        if windows or python or timeout or session:
            if buffer:
                blocks.append((code, "".join(buffer)))
                buffer = []
            if windows:
                code = _code_of(windows.group(1))
            elif python:
                code = "python:" + python.group(1).strip().lower()
            elif timeout:
                code = "watchdog_timeout"
            else:
                code = None
        buffer.append(line)
    if buffer:
        blocks.append((code, "".join(buffer)))
    return blocks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Filter selected native records into a separate report; preserve the source.")
    ap.add_argument("--logs-dir", default=None, help="logs directory (default: <repo>/user_data/logs)")
    ap.add_argument("--in", dest="infile", default=None, help="one explicit native source; default discovers legacy and process logs")
    ap.add_argument("--out", dest="outfile", default=None, help="separate filtered-report path")
    ap.add_argument("--benign", nargs="*", default=sorted(_DEFAULT_BENIGN),
                    help="exception codes to exclude, not certified benign (default: 0x8001010d; empty list keeps all)")
    a = ap.parse_args(argv)

    if a.infile:
        src = Path(a.infile)
        sources = [src] if src.exists() else []
        logs = src.parent
    else:
        logs = Path(a.logs_dir) if a.logs_dir else (Path(__file__).resolve().parents[2] / "user_data" / "logs")
        try:
            sources = discover_native_fault_logs(logs)
        except (OSError, ValueError):
            print("[filter] native-source discovery failed", file=sys.stderr)
            return 2
    if not sources:
        print("[filter] native source not found", file=sys.stderr)
        return 2
    out = Path(a.outfile) if a.outfile else logs / "native_fault_crashes.log"
    if (out.name == "native_fault.log" or native_fault_log_pid(out) is not None
            or any(out.resolve() == src.resolve() or (out.exists() and out.samefile(src)) for src in sources)):
        print("[filter] output must not refer to the source log", file=sys.stderr)
        return 2
    benign = {b.strip().lower() for b in a.benign}

    blocks = []
    for src in sources:
        if len(sources) > 1:
            blocks.append((None, f"\n=== source file {src.name} ===\n"))
        blocks.extend(parse_blocks(src.read_text(encoding="utf-8", errors="replace")))

    counts: dict = {}
    kept_blocks = []
    dropped = 0
    for code, block in blocks:
        key = code if code is not None else "(context/unclassified)"
        counts[key] = counts.get(key, 0) + 1
        if code is not None and code in benign:
            dropped += 1
            continue
        kept_blocks.append(block)

    out.write_text("".join(kept_blocks), encoding="utf-8")

    total = len(blocks)
    kept = len(kept_blocks)
    print("=" * 64)
    print(f"native_fault filter — {len(sources)} source file(s)")
    print("=" * 64)
    print(f"Total record blocks: {total}")
    for code in sorted(counts, key=lambda c: -counts[c]):
        mark = "  (excluded by policy)" if code in benign else ""
        print(f"  {code:<16} : {counts[code]}{mark}")
    print(f"Excluded records  : {dropped}")
    print(f"Retained blocks   : {kept}")
    print(f"Wrote filtered report -> {out}")
    print("\nRetained records require process/time correlation; they are not a terminal-crash count.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
