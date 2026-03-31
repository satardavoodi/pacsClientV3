"""Temporary script to edit viewer controller init."""
import os

filepath = r'c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\patient_tab\ui\patient_ui\patient_widget_viewer_controller.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

target_start = '        except Exception:\n            pass\n        print(\n'
idx = content.find(target_start, content.find('slice_focus_mode'))
end_marker = '    def _ensure_grid_config_exists(self):'
end_idx = content.find(end_marker, idx)

if idx < 0 or end_idx < 0:
    print(f"ERROR: Could not find markers. idx={idx}, end_idx={end_idx}")
    exit(1)

old_block = content[idx:end_idx]
print(f"Found old block at {idx}..{end_idx} ({len(old_block)} chars)")

lines = [
    '        except Exception:',
    '            pass',
    '',
    '        # -- Progressive series loading (incremental display during download) --',
    '        self._progressive_series = {}  # series_number -> {total, last_grow_count}',
    '        self._progressive_grow_timer = QTimer()',
    '        self._progressive_grow_timer.setSingleShot(True)',
    '        self._progressive_grow_timer.setInterval(500)',
    '        self._progressive_grow_timer.timeout.connect(self._flush_progressive_grow)',
    '        self._progressive_grow_batch_size = max(',
    '            5, int(os.getenv("AIPACS_PROGRESSIVE_GROW_BATCH", "10") or "10")',
    '        )',
    '',
]
new_block = '\n'.join(lines) + '\n'

content = content[:idx] + new_block + content[end_idx:]

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('Done - replaced block successfully')
