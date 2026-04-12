"""H5b/H5c: Add exception guards to unguarded QTimer callback slots in _vw_scroll.py.

H5b: _reenable_gc — direct QTimer.timeout slot, no try/except wrapper
H5c: _flush_pending_wheel_slice — tail code after try/except around set_slice is unguarded

Pattern: wrapper + _impl (same as _on_lazy_slice_ready in _vw_backend.py)
"""
import sys
from pathlib import Path

FILE = Path(r"c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\patient_tab\ui\patient_ui\vtk_widget\_vw_scroll.py")

content = FILE.read_text(encoding="utf-8")
original = content

# ── H5b: Guard _reenable_gc ──────────────────────────────────────────────
# Find the method and replace with wrapper+impl pattern
old_gc = "    def _reenable_gc(self):"
idx_gc = content.find(old_gc)
if idx_gc < 0:
    print("ERROR: Could not find _reenable_gc")
    sys.exit(1)

# Find the end of the method (next method at same indent level)
idx_restore = content.find("\n    def _restore_reslice_quality", idx_gc)
if idx_restore < 0:
    print("ERROR: Could not find _restore_reslice_quality")
    sys.exit(1)

gc_method = content[idx_gc:idx_restore]
print(f"[H5b] Found _reenable_gc ({len(gc_method)} chars)")

# Extract the docstring (between first """ and second """)
doc_start = gc_method.find('"""')
doc_end = gc_method.find('"""', doc_start + 3)
old_docstring = gc_method[doc_start:doc_end + 3]

# Extract the body (everything after the docstring)
body_start = doc_end + 3
gc_body = gc_method[body_start:]

# Build new wrapper + impl
new_gc = '''    def _reenable_gc(self):
        """Re-enable garbage collection after scroll burst ends.

        v2.2.9.3 / H5b: Outer guard -- this is a direct QTimer.timeout slot.
        Any unhandled exception propagates through the Qt event loop and causes
        the fatal 'Qt has caught an exception' crash.
        """
        try:
            self._reenable_gc_impl()
        except Exception as exc:
            logger.error(
                "[GC_REENABLE] unhandled exception viewer=%s: %s",
                getattr(self, "id_vtk_widget", "?"), exc, exc_info=True,
            )

    def _reenable_gc_impl(self):
        """Re-enable GC after scroll burst. See _reenable_gc wrapper."""
'''

# Re-indent the body: it's already at 8-space indent, keep as is
# But we need to handle the if/try blocks properly
# The body starts with \n        if self._gc_suppressed:
# Just append it directly
new_gc += gc_body

content = content[:idx_gc] + new_gc + content[idx_restore:]
print("[H5b] _reenable_gc wrapper applied")

# ── H5c: Guard _flush_pending_wheel_slice ─────────────────────────────────
old_flush = "    def _flush_pending_wheel_slice(self):"
idx_flush = content.find(old_flush)
if idx_flush < 0:
    print("ERROR: Could not find _flush_pending_wheel_slice")
    sys.exit(1)

# Find the end (next method)
idx_post = content.find("\n    def _post_scroll_sync_render", idx_flush)
if idx_post < 0:
    print("ERROR: Could not find _post_scroll_sync_render")
    sys.exit(1)

flush_method = content[idx_flush:idx_post]
print(f"[H5c] Found _flush_pending_wheel_slice ({len(flush_method)} chars)")

# Extract docstring
flush_doc_start = flush_method.find('"""')
flush_doc_end = flush_method.find('"""', flush_doc_start + 3)
flush_body = flush_method[flush_doc_end + 3:]

new_flush = '''    def _flush_pending_wheel_slice(self):
        """Render the latest coalesced scroll position (throttle callback).

        v2.2.9.3 / H5c: Outer guard -- this is a direct QTimer.timeout slot.
        The tail code (adaptive gap, timer restart, post-scroll scheduling)
        was previously outside the try/except around set_slice.
        """
        try:
            self._flush_pending_wheel_slice_impl()
        except Exception as exc:
            logger.error(
                "[SCROLL_COALESCE] unhandled exception in flush viewer=%s: %s",
                getattr(self, "id_vtk_widget", "?"), exc, exc_info=True,
            )

    def _flush_pending_wheel_slice_impl(self):
        """Flush impl. See _flush_pending_wheel_slice wrapper."""
'''
new_flush += flush_body

content = content[:idx_flush] + new_flush + content[idx_post:]
print("[H5c] _flush_pending_wheel_slice wrapper applied")

# ── Write ─────────────────────────────────────────────────────────────────
FILE.write_text(content, encoding="utf-8")
print(f"\nPatched {FILE.name} successfully.")
print(f"  Original size: {len(original)}")
print(f"  New size:      {len(content)}")
print(f"  Delta:         +{len(content) - len(original)} chars")
