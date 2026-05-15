"""One-shot fix for _pw_viewers.py indentation corrupted by diff patches."""
import re

path = (
    r"e:\ai-pacs\ai-pacs codes\ai-pacs beta version"
    r"\PacsClient\pacs\patient_tab\ui\patient_ui\patient_widget_core\_pw_viewers.py"
)

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ── Fix 1: _create_lightweight_vtk_placeholder ──────────────────────────────
# The configured/override block was indented 16 spaces (inside a fake sub-block)
# instead of 12 spaces (body of the try).

old1 = (
    "            # \u2500\u2500 FAST mode: allocate VTK-free container \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    "                configured = str(load_viewer_backend(default=BACKEND_PYDICOM_QT) or BACKEND_PYDICOM_QT).strip()\n"
    "                override = str(getattr(self, \"viewer_backend_override\", \"\") or \"\").strip()\n"
    "                if override and configured in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT):\n"
    "                    requested_backend = override\n"
    "                else:\n"
    "                    _res = resolve_viewer_backend(metadata=None, settings=configured)\n"
    "                    requested_backend = str(_res.get(\"requested_backend\", BACKEND_PYDICOM_QT) or BACKEND_PYDICOM_QT)\n"
    "                if requested_backend == BACKEND_PYDICOM_QT:\n"
    "                from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import QtFastContainer\n"
    "                container = QtFastContainer(height_viewer=height, patient_widget=self)\n"
    "                container._is_placeholder = True\n"
    "                return container"
)

new1 = (
    "            # \u2500\u2500 FAST mode: allocate VTK-free container \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    "            configured = str(load_viewer_backend(default=BACKEND_PYDICOM_QT) or BACKEND_PYDICOM_QT).strip()\n"
    "            override = str(getattr(self, \"viewer_backend_override\", \"\") or \"\").strip()\n"
    "            if override and configured in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT):\n"
    "                requested_backend = override\n"
    "            else:\n"
    "                _res = resolve_viewer_backend(metadata=None, settings=configured)\n"
    "                requested_backend = str(_res.get(\"requested_backend\", BACKEND_PYDICOM_QT) or BACKEND_PYDICOM_QT)\n"
    "            if requested_backend == BACKEND_PYDICOM_QT:\n"
    "                from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import QtFastContainer\n"
    "                container = QtFastContainer(height_viewer=height, patient_widget=self)\n"
    "                container._is_placeholder = True\n"
    "                return container"
)

if old1 in content:
    content = content.replace(old1, new1, 1)
    print("Fixed _create_lightweight_vtk_placeholder")
else:
    print("WARN: block1 not found — searching for partial match")
    # Show lines around the problem area for diagnosis
    for i, line in enumerate(content.splitlines(), 1):
        if "allocate VTK-free" in line or ("configured = str(load_viewer" in line and "placeholder" not in line):
            print(f"  L{i}: {repr(line)}")

# ── Fix 2: creator_vtk_widget ────────────────────────────────────────────────
old2 = (
    "            # \u2500\u2500 FAST mode: VTK-free container \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    "                # Use load_viewer_backend() directly \u2014 _get_requested_viewer_backend is on\n"
    "                # ViewerController (not PatientWidget), so hasattr() was always False and\n"
    "                # the code always fell through to VTKWidget() even in FAST mode.\n"
    "                configured = str(load_viewer_backend(default=BACKEND_PYDICOM_QT) or BACKEND_PYDICOM_QT).strip()\n"
    "                override = str(getattr(self, \"viewer_backend_override\", \"\") or \"\").strip()\n"
    "                if override and configured in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT):\n"
    "                    requested_backend = override\n"
    "                else:\n"
    "                    res = resolve_viewer_backend(metadata=None, settings=configured)\n"
    "                    requested_backend = str(res.get(\"requested_backend\", BACKEND_PYDICOM_QT) or BACKEND_PYDICOM_QT)\n"
    "            if requested_backend == BACKEND_PYDICOM_QT:"
)

new2 = (
    "            # \u2500\u2500 FAST mode: VTK-free container \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    "            # Use load_viewer_backend() directly \u2014 _get_requested_viewer_backend is on\n"
    "            # ViewerController (not PatientWidget), so hasattr() was always False and\n"
    "            # the code always fell through to VTKWidget() even in FAST mode.\n"
    "            configured = str(load_viewer_backend(default=BACKEND_PYDICOM_QT) or BACKEND_PYDICOM_QT).strip()\n"
    "            override = str(getattr(self, \"viewer_backend_override\", \"\") or \"\").strip()\n"
    "            if override and configured in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT):\n"
    "                requested_backend = override\n"
    "            else:\n"
    "                res = resolve_viewer_backend(metadata=None, settings=configured)\n"
    "                requested_backend = str(res.get(\"requested_backend\", BACKEND_PYDICOM_QT) or BACKEND_PYDICOM_QT)\n"
    "            if requested_backend == BACKEND_PYDICOM_QT:"
)

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("Fixed creator_vtk_widget")
else:
    print("WARN: block2 not found — searching for partial match")
    for i, line in enumerate(content.splitlines(), 1):
        if "VTK-free container" in line or ("configured = str(load_viewer" in line):
            print(f"  L{i}: {repr(line)}")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
