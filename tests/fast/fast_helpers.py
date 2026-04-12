"""
Shared test-data builders for tests/fast/ — pure synthetic DICOM metadata
(no real files).  Imported as `from helpers import ...` in test files.
"""


def _make_axial_instances(n: int = 40, pixel_spacing=None, rows=512, cols=512, z0=0.0, dz=1.0):
    """Axial series: IOP=[1,0,0, 0,1,0]; normal=(0,0,1)."""
    if pixel_spacing is None:
        pixel_spacing = [0.5, 0.5]
    return [
        {
            "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            "image_position_patient": [0.0, 0.0, z0 + k * dz],
            "pixel_spacing": pixel_spacing,
            "rows": rows,
            "columns": cols,
            "instance_number": k + 1,
        }
        for k in range(n)
    ]


def _make_sagittal_instances(n: int = 40, pixel_spacing=None, rows=512, cols=512, x0=0.0, dx=1.0):
    """Sagittal series: IOP=[0,1,0, 0,0,-1]; normal=(1,0,0)."""
    if pixel_spacing is None:
        pixel_spacing = [0.5, 0.5]
    return [
        {
            "image_orientation_patient": [0.0, 1.0, 0.0, 0.0, 0.0, -1.0],
            "image_position_patient": [x0 + k * dx, 0.0, 0.0],
            "pixel_spacing": pixel_spacing,
            "rows": rows,
            "columns": cols,
            "instance_number": k + 1,
        }
        for k in range(n)
    ]


def _make_coronal_instances(n: int = 40, pixel_spacing=None, rows=512, cols=512, y0=0.0, dy=1.0):
    """Coronal series: IOP=[1,0,0, 0,0,-1]; normal=(0,1,0)."""
    if pixel_spacing is None:
        pixel_spacing = [0.5, 0.5]
    return [
        {
            "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 0.0, -1.0],
            "image_position_patient": [0.0, y0 + k * dy, 0.0],
            "pixel_spacing": pixel_spacing,
            "rows": rows,
            "columns": cols,
            "instance_number": k + 1,
        }
        for k in range(n)
    ]
