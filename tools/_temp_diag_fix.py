"""Temporary script to fix diagnostic prints to use file output."""
import re

filepath = "PacsClient/pacs/patient_tab/ui/patient_ui/widget_viewer.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace the WHEEL_DIAG print with file write
old_wheel = (
    '        # TEMP DIAG: Print to console so we can see if wheelEvent is called\n'
    "        print(f\"[WHEEL_DIAG] viewer={getattr(self, 'id_vtk_widget', '?')}"
    " backend={getattr(self, '_active_backend', '?')}"
    " qt_bridge={getattr(self, '_qt_bridge_active', '?')}"
    " iv={'Y' if self.image_viewer else 'N'}"
    " slider={'Y' if self.slider else 'N'}"
    ' delta={event.angleDelta().y()}", flush=True)'
)
new_wheel = (
    '        # TEMP DIAG: Write to file so we can see if wheelEvent is called\n'
    '        try:\n'
    '            import tempfile as _tf, os as _os\n'
    "            with open(_os.path.join(_tf.gettempdir(), 'aipacs_wheel_diag.log'), 'a') as _df:\n"
    "                _df.write(f\"[WHEEL_DIAG] viewer={getattr(self, 'id_vtk_widget', '?')}"
    " backend={getattr(self, '_active_backend', '?')}"
    " qt_bridge={getattr(self, '_qt_bridge_active', '?')}"
    " iv={'Y' if self.image_viewer else 'N'}"
    " slider={'Y' if self.slider else 'N'}"
    ' delta={event.angleDelta().y()}\\n")\n'
    '        except Exception:\n'
    '            pass'
)
if old_wheel in content:
    content = content.replace(old_wheel, new_wheel, 1)
    print("Replaced WHEEL_DIAG")
else:
    print("WARNING: WHEEL_DIAG pattern not found!")

# 2. Replace the INIT_DIAG print with file write
old_init = (
    '            # TEMP DIAG: log backend choice\n'
    '            print(f"[INIT_DIAG] start_process_series'
    ' backend={self._active_backend}'
    ' qt_bridge={self._qt_bridge_active}'
    ' viewer={id_vtk_widget}", flush=True)'
)
new_init = (
    '            # TEMP DIAG: log backend choice to file\n'
    '            try:\n'
    '                import tempfile as _tf, os as _os\n'
    "                with open(_os.path.join(_tf.gettempdir(), 'aipacs_wheel_diag.log'), 'a') as _df:\n"
    '                    _df.write(f"[INIT_DIAG] start_process_series'
    ' backend={self._active_backend}'
    ' qt_bridge={self._qt_bridge_active}'
    ' viewer={id_vtk_widget}\\n")\n'
    '            except Exception:\n'
    '                pass'
)
if old_init in content:
    content = content.replace(old_init, new_init, 1)
    print("Replaced INIT_DIAG")
else:
    print("WARNING: INIT_DIAG pattern not found!")

# 3. Replace the BIND_DIAG print with file write
old_bind = (
    "        # TEMP DIAG: show backend resolution result\n"
    "        print(f\"[BIND_DIAG] source={source}"
    " requested={requested_backend}"
    " resolved={resolution.get('backend')}"
    " safe_forced={resolution.get('safe_backend_forced')}"
    ' force_vtk={force_vtk}", flush=True)'
)
new_bind = (
    "        # TEMP DIAG: show backend resolution result\n"
    "        try:\n"
    "            import tempfile as _tf, os as _os\n"
    "            with open(_os.path.join(_tf.gettempdir(), 'aipacs_wheel_diag.log'), 'a') as _df:\n"
    "                _df.write(f\"[BIND_DIAG] source={source}"
    " requested={requested_backend}"
    " resolved={resolution.get('backend')}"
    " safe_forced={resolution.get('safe_backend_forced')}"
    ' force_vtk={force_vtk}\\n")\n'
    "        except Exception:\n"
    "            pass"
)
if old_bind in content:
    content = content.replace(old_bind, new_bind, 1)
    print("Replaced BIND_DIAG")
else:
    print("WARNING: BIND_DIAG pattern not found!")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Done!")
