"""
Recovery script: restore the corrupted _vc_progressive.py by replacing the
wrong except block (lines 479-503) with the original _threaded_load except/finally,
the thread.start() call, and the _flush_progressive_grow + _flush_progressive_grow_impl
function definitions.

The timer-storm fix is applied to _flush_progressive_grow_impl during restoration.
"""
import sys

path = r"c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\patient_tab\ui\patient_ui\_vc_progressive.py"

with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Total lines before: {len(lines)}")

# Verify landmarks
assert "QTimer.singleShot(0, _display_activate_and_mark_done)" in lines[477], \
    f"Unexpected line 478: {lines[477]!r}"
assert "except Exception as exc:" in lines[478], \
    f"Unexpected line 479: {lines[478]!r}"
# Find the "            else:" line that starts the Advanced (VTK) mode
else_idx = None
for i in range(479, min(520, len(lines))):
    stripped = lines[i].rstrip("\r\n")
    if stripped == "            else:":
        else_idx = i
        break
assert else_idx is not None, "Could not find '            else:' after line 479"
print(f"Found 'else:' at line {else_idx + 1}")

# Lines 478 (0-indexed) through else_idx-1 (inclusive) are the corrupted block.
# Replace them with the original _threaded_load except/finally + thread.start
# + _flush_progressive_grow + _flush_progressive_grow_impl (with timer-storm fix)

# Build replacement lines
replacement = """\
                except Exception as exc:
                    self.logger.warning("progressive: threaded fallback failed: %s", exc)
                finally:
                    inflight = getattr(self, '_progressive_display_inflight', None)
                    if inflight is not None:
                        inflight.discard(series_number)

            thread = threading.Thread(
                target=_threaded_load,
                name="progressive-load-" + str(series_number),
                daemon=True,
            )
            thread.start()

    def _flush_progressive_grow(self):
        \"\"\"Timer callback: grow all progressive viewers with newly downloaded images.\"\"\"
        try:
            self._flush_progressive_grow_impl()
        except Exception as exc:
            self.logger.error(
                "progressive: unhandled error in _flush_progressive_grow: %s",
                exc, exc_info=True,
            )

    def _flush_progressive_grow_impl(self):
        \"\"\"Inner implementation called by _flush_progressive_grow.\"\"\"
        is_fast = self._is_fast_viewer_mode()

        for sn, info in list(self._progressive_series.items()):
            pending = info.get("pending_downloaded", 0)
            last_grow = info.get("last_grow_count", 0)
            if pending <= last_grow:
                continue  # nothing new to process
            total = info.get("total", 0)
            viewers = self._find_progressive_viewers(sn)
            if not viewers:
                continue

            if is_fast:
                # Fast mode: refresh backend file list + update available count
                # (no VTK volume reconstruction needed).
                # Guard: prevent exceptions from escaping the QTimer callback.
                # One-time-per-series traceback log avoids 150ms log spam.
                try:
                    self._grow_progressive_fast(sn, pending, viewers)
                    # Clear flags on success so a future re-occurrence is fully logged
                    info.pop("_grow_error_logged", None)
                    info.pop("_grow_error_count", None)
                except Exception as exc:
                    err_count = info.get("_grow_error_count", 0) + 1
                    info["_grow_error_count"] = err_count
                    _GROW_ERROR_MAX = 5
                    if not info.get("_grow_error_logged"):
                        info["_grow_error_logged"] = True
                        self.logger.error(
                            "progressive: _grow_progressive_fast failed series=%s: %s",
                            sn, exc, exc_info=True,
                        )
                    else:
                        self.logger.warning(
                            "progressive: _grow_progressive_fast still failing series=%s (%d/%d): %s",
                            sn, err_count, _GROW_ERROR_MAX, exc,
                        )
                    if err_count >= _GROW_ERROR_MAX:
                        # Bounded retry: after N consecutive failures, equalize
                        # pending to last_grow_count so the safety-net below
                        # does NOT re-arm the timer.  Prevents infinite storm.
                        info["pending_downloaded"] = info.get("last_grow_count", 0)
                        self.logger.error(
                            "progressive: grow retry exhausted series=%s after %d failures, "
                            "stopping timer re-arm",
                            sn, err_count,
                        )
"""

# Convert to lines list, preserving the file's line ending style
# Check if file uses CRLF
uses_crlf = "\r\n" in lines[0] if lines else False
line_ending = "\r\n" if uses_crlf else "\n"

replacement_lines = []
for line in replacement.split("\n"):
    # Don't add trailing empty line from the triple-quote
    replacement_lines.append(line + line_ending)
# Remove last empty line artifact
if replacement_lines and replacement_lines[-1].strip() == "":
    replacement_lines.pop()

# Reconstruct the file:
# lines[0:478]  = everything up through QTimer.singleShot line
# replacement   = restored except/finally + function defs
# lines[else_idx:]  = "            else:" onward (intact Advanced mode + safety net + _grow_progressive_fast)
new_lines = lines[:478] + replacement_lines + lines[else_idx:]

print(f"Total lines after: {len(new_lines)}")

# Verify some landmarks in the new file
new_content = "".join(new_lines)
assert "_flush_progressive_grow_impl" in new_content, "Missing _flush_progressive_grow_impl"
assert "_flush_progressive_grow" in new_content, "Missing _flush_progressive_grow"
assert "threaded fallback failed" in new_content, "Missing threaded fallback except"
assert "_progressive_display_inflight" in new_content, "Missing inflight cleanup"
assert "thread.start()" in new_content, "Missing thread.start()"
assert "_GROW_ERROR_MAX = 5" in new_content, "Missing timer-storm fix"
assert "_grow_error_count" in new_content, "Missing error count"

# Count function defs
flush_count = new_content.count("def _flush_progressive_grow(self)")
flush_impl_count = new_content.count("def _flush_progressive_grow_impl(self)")
grow_fast_count = new_content.count("def _grow_progressive_fast(self")
print(f"_flush_progressive_grow defs: {flush_count}")
print(f"_flush_progressive_grow_impl defs: {flush_impl_count}")
print(f"_grow_progressive_fast defs: {grow_fast_count}")

assert flush_count == 1, f"Expected 1 _flush_progressive_grow def, got {flush_count}"
assert flush_impl_count == 1, f"Expected 1 _flush_progressive_grow_impl def, got {flush_impl_count}"
assert grow_fast_count == 1, f"Expected 1 _grow_progressive_fast def, got {grow_fast_count}"

with open(path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("\nRecovery + timer-storm fix applied successfully!")
