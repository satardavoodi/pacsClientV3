#!/usr/bin/env python3
"""Replace bare print() calls with logger.debug() in viewer files.

Targets: widget_viewer.py, _vc_*.py files in patient_ui/
Rules:
  - print(f"...ERROR...") or print(f"...FAILED...") → logger.error(...)
  - print(f"...WARNING...") or print(f"...WARN...") → logger.warning(...)
  - print(f"...") → logger.debug(...)
  - Commented-out print() lines → removed entirely
  - Preserves indentation
  - Does NOT touch logger.* calls or non-print lines

Usage: python tools/dev/_replace_prints_to_logger.py [--dry-run]
"""
import os
import re
import sys

BASE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "PacsClient", "pacs", "patient_tab", "ui", "patient_ui",
)

TARGET_FILES = [
    "widget_viewer.py",
    "_vc_backend.py",
    "_vc_cache.py",
    "_vc_layout.py",
    "_vc_load.py",
    "_vc_progressive.py",
    "_vc_switch.py",
    "_vc_warmup.py",
]

# Regex to match bare print() calls (active code, not comments)
ACTIVE_PRINT_RE = re.compile(
    r'^(\s+)(print\((?:f?["\']|f?""")(.+?)(?:["\']|""")\))\s*$'
)
# Regex to match commented-out print() lines
COMMENTED_PRINT_RE = re.compile(
    r'^\s+#\s*print\(.+\)\s*$'
)

def classify_level(msg_content: str) -> str:
    """Determine log level from message content."""
    upper = msg_content.upper()
    if any(kw in upper for kw in ("ERROR", "FAILED", "â\x8c\x8c", "FATAL")):
        return "error"
    if any(kw in upper for kw in ("WARNING", "WARN", "â\x9a\xa0")):
        return "warning"
    return "debug"


def convert_print_to_logger(line: str) -> str | None:
    """Convert a print() line to logger call. Returns None to remove line."""
    # Skip commented-out prints
    if COMMENTED_PRINT_RE.match(line):
        return None  # signal to remove

    m = ACTIVE_PRINT_RE.match(line)
    if not m:
        return line  # not a print line, keep as-is

    indent = m.group(1)
    full_print = m.group(2)
    msg_content = m.group(3)
    level = classify_level(msg_content)

    # Extract the string content including f-prefix
    # Reconstruct as logger call
    # Find the exact string arg in the print call
    inner_match = re.search(r'print\((f?["\'].*["\']|f?""".*""")\)', full_print, re.DOTALL)
    if not inner_match:
        return line  # can't parse, keep original

    string_arg = inner_match.group(1)
    return f"{indent}logger.{level}({string_arg})\n"


def process_file(filepath: str, dry_run: bool = False) -> tuple[int, int]:
    """Process a single file. Returns (replaced_count, removed_count)."""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    replaced = 0
    removed = 0

    for line in lines:
        # Check if it's a print line
        if re.match(r'^\s+#\s*print\(', line):
            removed += 1
            continue  # remove commented-out prints
        
        if re.match(r'^\s+print\(', line):
            result = convert_print_to_logger(line)
            if result is None:
                removed += 1
                continue
            if result != line:
                replaced += 1
                new_lines.append(result)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if not dry_run and (replaced > 0 or removed > 0):
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    return replaced, removed


def main():
    dry_run = "--dry-run" in sys.argv
    total_replaced = 0
    total_removed = 0

    for fname in TARGET_FILES:
        filepath = os.path.normpath(os.path.join(BASE_DIR, fname))
        if not os.path.exists(filepath):
            print(f"  SKIP {fname} (not found)")
            continue
        replaced, removed = process_file(filepath, dry_run=dry_run)
        total_replaced += replaced
        total_removed += removed
        if replaced or removed:
            action = "WOULD" if dry_run else "DID"
            print(f"  {action} {fname}: {replaced} replaced, {removed} removed")
        else:
            print(f"  {fname}: no changes")

    print(f"\nTotal: {total_replaced} replaced, {total_removed} removed")
    if dry_run:
        print("(dry-run mode — no files changed)")


if __name__ == "__main__":
    main()
