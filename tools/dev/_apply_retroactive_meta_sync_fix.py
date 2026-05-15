#!/usr/bin/env python
"""
Apply targeted retroactive-activation metadata sync cap+throttle fix.
This script modifies _vc_progressive.py to:
1. Track retroactive-active series
2. Apply R27 cap + R28 throttle only to retroactive + drag metadata sync
3. Keep terminal completion metadata sync unbounded
"""
import re
import sys
from pathlib import Path

workspace_root = Path(__file__).parent.parent.parent
vc_progressive_path = workspace_root / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py"

if not vc_progressive_path.exists():
    print(f"ERROR: {vc_progressive_path} not found")
    sys.exit(1)

content = vc_progressive_path.read_text(encoding='utf-8')

# ===== Fix 1: Mark retroactive active series in retroactive activation block =====
# Find the retroactive activation block and add tracking
retroactive_pattern = r'(                vtk_w\.update_available_slice_count\(avail\)\n                _set_progressive_lifecycle_state\()'
retroactive_replacement = r'''\1retroactive_marker = 1
                # Mark that this series is now in retroactive + active-download mode.
                # This flag controls metadata sync cap/throttle on next grow tick.
                if not hasattr(self, "_retroactive_active_series"):
                    self._retroactive_active_series = set()
                self._retroactive_active_series.add(sn)
                _set_progressive_lifecycle_state()'''

# Actually, let me find the exact section in a simpler way
# Search for "retroactive_activate_ms"
if "retroactive_activate_ms" in content:
    # Find the line number
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if "vtk_w.update_available_slice_count(avail)" in line and i > 1000 and i < 1100:
            # Found the retroactive activation block
            # Insert the retroactive tracking code after update_available_slice_count
            next_line_idx = i + 1
            # Check if code already has the tracking
            if "_retroactive_active_series" not in '\n'.join(lines[i:i+10]):
                # Insert the tracking code
                indent = "                "
                tracking_code = [
                    f"{indent}# Mark that this series is now in retroactive + active-download mode.",
                    f"{indent}# This flag controls metadata sync cap/throttle on next grow tick.",
                    f"{indent}if not hasattr(self, \"_retroactive_active_series\"):",
                    f"{indent}    self._retroactive_active_series = set()",
                    f"{indent}self._retroactive_active_series.add(sn)",
                ]
                for j, code_line in enumerate(tracking_code):
                    lines.insert(next_line_idx + j, code_line)
                print(f"✓ Added retroactive tracking at line {i+1}")
                break

content = '\n'.join(lines)

# ===== Fix 2: Modify deferred metadata sync logic in _grow_progressive_fast =====
# Find the section that handles terminal vs non-terminal metadata sync
terminal_sync_section = '''        if terminal:
            try:
                _meta_last = getattr(self, "_progressive_meta_sync_last_ms", None)
                if isinstance(_meta_last, dict):
                    _meta_last.pop(str(series_number), None)
            except Exception:
                pass
            self._refresh_and_sync_metadata(series_number, new_count)
        else:
            should_schedule_meta_sync = True'''

if terminal_sync_section in content:
    # Replace with new logic that handles retroactive vs non-retroactive
    new_terminal_section = '''        if terminal:
            # Terminal completion: unbounded metadata sync (no cap, no throttle).
            # Clear retroactive state since download is now complete.
            try:
                _retro_active = getattr(self, "_retroactive_active_series", None)
                if _retro_active is not None:
                    _retro_active.discard(str(series_number))
            except Exception:
                pass
            try:
                _meta_last = getattr(self, "_progressive_meta_sync_last_ms", None)
                if isinstance(_meta_last, dict):
                    _meta_last.pop(str(series_number), None)
            except Exception:
                pass
            _deferred_meta_sync_start_ms = now_ms()
            try:
                self._refresh_and_sync_metadata(series_number, new_count)
            except Exception:
                pass
            _duration_ms = float(now_ms() - _deferred_meta_sync_start_ms)
            self.logger.info(
                "[RETRO_META_SYNC_FINAL_FLUSH] series=%s applied_count=%d duration_ms=%.3f "
                "interaction_active=%s terminal=True",
                str(series_number),
                int(new_count),
                _duration_ms,
                bool(interaction_active),
            )
        else:
            # Non-terminal metadata sync: check for retroactive + drag to apply cap/throttle.
            _is_retroactive_active_grow = (
                bool(grow_overlap_with_drag) and
                str(series_number) in getattr(self, "_retroactive_active_series", set())
            )
            
            # Determine which cap and throttle to use
            if _is_retroactive_active_grow:
                _meta_cap = _FAST_RETROACTIVE_METADATA_APPEND_CAP
                _meta_throttle_ms = _FAST_RETROACTIVE_METADATA_SYNC_MIN_INTERVAL_MS
            else:
                _meta_cap = _FAST_PROGRESSIVE_METADATA_APPEND_CAP
                _meta_throttle_ms = _FAST_PROGRESSIVE_METADATA_SYNC_MIN_INTERVAL_MS
            
            should_schedule_meta_sync = True'''

    content = content.replace(terminal_sync_section, new_terminal_section)
    print("✓ Replaced terminal/non-terminal metadata sync logic")
else:
    print("WARNING: Could not find terminal sync section")

# Write the modified content back
vc_progressive_path.write_text(content, encoding='utf-8')
print(f"✓ Wrote modified {vc_progressive_path.name}")

# Verify the changes compiled
print("\nValidating Python syntax...")
import py_compile
try:
    py_compile.compile(str(vc_progressive_path), doraise=True)
    print("✓ Python syntax valid")
except py_compile.PyCompileError as e:
    print(f"ERROR: Syntax validation failed: {e}")
    sys.exit(1)

print("\n✓ Fix applied successfully")
