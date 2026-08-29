"""One-off: summarise a finished Eagle Eye session from its stored artifacts.

Prints the health flags that decide whether a run is worth judging at all
(parsed / truncated / token headroom), the candidate list by level, and what
pass 2 did with each one.
"""
import json
import pathlib
import sys
from collections import Counter, defaultdict

root = pathlib.Path(sys.argv[1])


def load(name):
    path = root / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


result = load("llm_result.json")
one = load("llm_stage1_structured.json")
two = load("llm_stage2_structured.json")

print("pipeline %s   models %s" % (result.get("pipeline_version"),
                                   result.get("stage_models")))
for doc, label in ((one, "stage1"), (two, "stage2")):
    ceiling = doc.get("max_output_tokens") or 0
    used = doc.get("completion_tokens") or 0
    head = ("%.2fx" % (ceiling / used)) if used else "-"
    print("%-7s %-24s parsed=%-5s truncated=%-5s %5d/%-6d headroom %s" % (
        label, doc.get("model", ""), doc.get("parsed"), doc.get("truncated"),
        used, ceiling, head))

findings = ((one.get("data") or {}).get("findings")) or []
print("\ncandidates: %d" % len(findings))
by_level = defaultdict(list)
for item in findings:
    by_level[str(item.get("level"))].append(
        "%s(%s)" % (item.get("candidate"), (item.get("confidence") or "?")[0]))
for level in sorted(by_level):
    print("  %-8s %s" % (level, ", ".join(by_level[level])))

checks = ((two.get("data") or {}).get("verifications")) or []
print("\nverifications: %d" % len(checks))
for status, count in sorted(Counter(str(c.get("status")) for c in checks).items()):
    print("  %-14s %d" % (status, count))
survivors = [c for c in checks
             if str(c.get("status")) in ("CONFIRMED", "REFINED", "DOWNGRADED", "ADDED")]
print("\nsurvived: %d" % len(survivors))
for item in survivors:
    print("  [%s] %s" % (item.get("status"), item.get("candidate")))
