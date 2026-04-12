"""
One-shot patch: add _GROW_ERROR_MAX retry counter to _flush_progressive_grow_impl
to prevent infinite timer re-arm storm when _grow_progressive_fast keeps failing.
"""
import re, sys

path = r"c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\patient_tab\ui\patient_ui\_vc_progressive.py"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ── Replacement 1: Add "info.pop(_grow_error_count)" after the existing info.pop(_grow_error_logged) on success path ──
old1 = '                    info.pop("_grow_error_logged", None)'
new1 = '                    info.pop("_grow_error_logged", None)\n                    info.pop("_grow_error_count", None)'

assert content.count(old1) == 1, f"Expected 1 occurrence of old1, found {content.count(old1)}"
content = content.replace(old1, new1, 1)

# ── Replacement 2: In the except block, add error count + bounded retry logic ──
# Find the "except Exception as exc:" followed by the logging block
# We replace the entire except body up to (but not including) the line starting with "            else:"

# Locate the except block start
except_marker = '                except Exception as exc:\n'
except_idx = content.index(except_marker)

# Find the "            else:" line that ends the if-is_fast block (NOT the else inside the except)
# It's the line that starts with exactly "            else:" with 12 spaces
# after the comment about "scrolling is unaffected"
unaffected_marker = "scrolling is unaffected"
unaffected_idx = content.index(unaffected_marker, except_idx)
# Find the next newline after that line
next_nl = content.index("\n", unaffected_idx)
# The else: line is after that newline
else_line_start = next_nl + 1

old_except_body = content[except_idx:else_line_start]
print("OLD except body:")
print(repr(old_except_body[:200]))
print("...")

new_except_body = (
    '                except Exception as exc:\n'
    '                    err_count = info.get("_grow_error_count", 0) + 1\n'
    '                    info["_grow_error_count"] = err_count\n'
    '                    _GROW_ERROR_MAX = 5\n'
    '                    if not info.get("_grow_error_logged"):\n'
    '                        info["_grow_error_logged"] = True\n'
    '                        self.logger.error(\n'
    '                            "progressive: _grow_progressive_fast failed series=%s: %s",\n'
    '                            sn, exc, exc_info=True,\n'
    '                        )\n'
    '                    else:\n'
    '                        self.logger.warning(\n'
    '                            "progressive: _grow_progressive_fast still failing series=%s (%d/%d): %s",\n'
    '                            sn, err_count, _GROW_ERROR_MAX, exc,\n'
    '                        )\n'
    '                    if err_count >= _GROW_ERROR_MAX:\n'
    '                        # Bounded retry: after N consecutive failures, equalize\n'
    '                        # pending to last_grow_count so the safety-net below\n'
    '                        # does NOT re-arm the timer.  Prevents infinite storm.\n'
    '                        info["pending_downloaded"] = info.get("last_grow_count", 0)\n'
    '                        self.logger.error(\n'
    '                            "progressive: grow retry exhausted series=%s after %d failures, "\n'
    '                            "stopping timer re-arm",\n'
    '                            sn, err_count,\n'
    '                        )\n'
)

content = content[:except_idx] + new_except_body + content[else_line_start:]

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("\nPatch applied successfully!")
print("Verify: _grow_error_count count =", content.count("_grow_error_count"))
print("Verify: _GROW_ERROR_MAX   count =", content.count("_GROW_ERROR_MAX"))
