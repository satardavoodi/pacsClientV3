"""
Insert FAST mode fast-path at the top of VTKWidget.wheelEvent in _vw_scroll.py.

When _qt_bridge_active is True, skip the heavy VTK scroll machinery 
(GC suppression, coalesce timer, adaptive step, pending-wheel tracking)
and go directly through the Qt bridge pipeline.
"""
import os

TARGET = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "PacsClient", "pacs", "patient_tab", "ui", "patient_ui",
    "vtk_widget", "_vw_scroll.py",
)
TARGET = os.path.normpath(TARGET)

MARKER = "# v2.2.9.3-diag: first 5 wheel events logged at INFO to confirm entry"

FAST_PATH = '''\
        # ── FAST mode (Qt bridge) fast-path ──────────────────────────────
        # When the Qt 2D backend is active, skip the entire VTK scroll
        # machinery (GC suppression, coalesce timer, adaptive step,
        # pending-wheel tracking).  Directly compute ±1 step, render via
        # the bridge, and update the slider.  This guarantees scroll works
        # regardless of VTK interactor / event-delivery edge cases.
        if self._qt_bridge_active and self.image_viewer is not None and self.slider is not None:
            delta = event.angleDelta().y()
            if delta == 0:
                event.accept()
                return
            max_s = self.get_count_of_slices()
            if max_s <= 1:
                event.accept()
                return
            step = -1 if delta > 0 else 1
            current = self.image_viewer.GetSlice()
            new_idx = max(0, min(current + step, max_s - 1))
            if new_idx != current:
                try:
                    self.image_viewer.set_slice(new_idx)
                    self.image_viewer.last_index_slice_saved = int(new_idx)
                except Exception as _e:
                    import logging as _lg
                    _lg.getLogger(__name__).warning("Qt fast-scroll set_slice failed: %s", _e)
                # Update slider without triggering valueChanged
                self.slider.blockSignals(True)
                self.slider.setValue(new_idx)
                self.slider.blockSignals(False)
                # Lock Sync callback (throttled)
                if self._on_slice_changed_cb is not None:
                    try:
                        self._on_slice_changed_cb(self)
                    except Exception:
                        pass
                # Reference lines
                try:
                    _pw = getattr(self, 'patient_widget', None)
                    if _pw is not None and hasattr(_pw, '_schedule_reference_line_update'):
                        _pw._schedule_reference_line_update()
                except Exception:
                    pass
            event.accept()
            return

'''

def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        text = f.read()

    if "FAST mode (Qt bridge) fast-path" in text:
        print("Already patched. Nothing to do.")
        return

    idx = text.find(MARKER)
    if idx < 0:
        print(f"ERROR: Could not find marker line in {TARGET}")
        return

    new_text = text[:idx] + FAST_PATH + text[idx:]

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_text)

    print(f"Inserted FAST mode fast-path ({FAST_PATH.count(chr(10))} lines) before marker.")
    print("Done.")

if __name__ == "__main__":
    main()
