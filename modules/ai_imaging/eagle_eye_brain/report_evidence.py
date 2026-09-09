"""Small local report montage; run only in the analysis/report worker."""
import base64
from pathlib import Path


def segmentation_png(directory, *, medial_temporal=False):
    import numpy as np
    import SimpleITK as sitk
    from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    directory = Path(directory)
    if QApplication.instance() is None or not (directory / "labels.nii.gz").is_file():
        return None
    source = sitk.ReadImage(str(directory / "resampled.nii.gz"))
    labels = sitk.ReadImage(str(directory / "labels.nii.gz"))
    if (source.GetSize() != labels.GetSize()
            or any(not np.allclose(getattr(source, key)(), getattr(labels, key)(), atol=1e-4)
                   for key in ("GetOrigin", "GetSpacing", "GetDirection"))):
        from .contracts import BrainError
        raise BrainError("Report image and segmentation geometry disagree.")
    # Axis-aligned LPS grid makes report orientation explicit even for oblique input.
    reference = sitk.DICOMOrient(source, "LPS")
    direction = np.asarray(reference.GetDirection()).reshape(3, 3)
    if not np.allclose(direction, np.eye(3), atol=1e-4):
        import itertools
        corners = np.asarray([source.TransformIndexToPhysicalPoint(tuple(int(i) for i in index))
                              for index in itertools.product(*[(0, n - 1) for n in source.GetSize()])])
        origin = corners.min(axis=0)
        spacing = max(min(source.GetSpacing()), 0.5)
        size = np.ceil((corners.max(axis=0) - origin) / spacing).astype(int) + 1
        grid = sitk.Image([int(n) for n in size], sitk.sitkFloat32)
        grid.SetOrigin(tuple(origin))
        grid.SetSpacing((spacing,) * 3)
        reference = sitk.Resample(source, grid, sitk.Transform(3, sitk.sitkIdentity),
                                  sitk.sitkLinear, 0, sitk.sitkFloat32)
    reference_labels = sitk.Resample(labels, reference, sitk.Transform(3, sitk.sitkIdentity),
                                     sitk.sitkNearestNeighbor, 0, sitk.sitkUInt16)
    a, lab = sitk.GetArrayFromImage(reference), sitk.GetArrayFromImage(reference_labels)
    foreground = lab > 0
    if not foreground.any():
        return None
    low, high = np.percentile(a[foreground], (1, 99))
    if high <= low:
        return None
    gray = np.clip((a - low) / (high - low), 0, 1)
    coordinates = np.where(foreground)
    z, y, x = [int((indices.min() + indices.max()) / 2) for indices in coordinates]
    sx, sy, sz = reference.GetSpacing()
    planes = [(gray[z], lab[z], "Axial", "R", "L", "A", "P", sx, sy),
              (gray[:, y, :][::-1], lab[:, y, :][::-1], "Coronal", "R", "L", "S", "I", sx, sz),
              (gray[:, :, x][::-1], lab[:, :, x][::-1], "Sagittal", "A", "P", "S", "I", sy, sz)]
    if medial_temporal:
        import json
        names = json.loads((directory / "label_names.json").read_text(encoding="utf-8"))
        ids = [int(key) for key, value in names.items()
               if value in ("left hippocampus", "right hippocampus")]
        hippocampi = np.isin(lab, ids)
        if not hippocampi.any():
            return None
        occupied_y = np.flatnonzero(hippocampi.any(axis=(0, 2)))
        positions = np.unique(np.quantile(occupied_y, (.25, .5, .75)).astype(int))
        if len(positions) != 3:
            return None
        focus_labels = np.where(hippocampi, lab, 0)
        hz, _, hx = np.where(hippocampi)
        # Display-only crop around both hippocampi; never change input or volume masks.
        z0, z1 = max(0, int(hz.min()) - int(20 / sz)), min(lab.shape[0], int(hz.max()) + int(20 / sz) + 1)
        x0, x1 = max(0, int(hx.min()) - int(20 / sx)), min(lab.shape[2], int(hx.max()) + int(20 / sx) + 1)
        planes = [(gray[z0:z1, pos, x0:x1][::-1], focus_labels[z0:z1, pos, x0:x1][::-1], f"Coronal y={pos}",
                   "R", "L", "S", "I", sx, sz) for pos in positions]
    canvas = QImage(1050, 650, QImage.Format.Format_RGB32)
    canvas.fill(QColor("black"))
    painter = QPainter(canvas)
    try:
        painter.setFont(QFont("Arial", 11))
        for column, (pixels, mask, name, left, right, top, bottom, dx, dy) in enumerate(planes):
            base = np.repeat(pixels[..., None], 3, axis=2)
            color = np.stack([((mask * k) % 191 + 64) / 255 for k in (31, 67, 97)], axis=-1)
            overlay = np.where((mask > 0)[..., None], .65 * base + .35 * color, base)
            for row, rgb in enumerate((base, overlay)):
                image_array = np.ascontiguousarray(rgb * 255, dtype=np.uint8)
                image = QImage(image_array.data, image_array.shape[1], image_array.shape[0],
                               image_array.strides[0], QImage.Format.Format_RGB888).copy()
                width, height = image.width() * dx, image.height() * dy
                scale = min(285 / width, 245 / height)
                cx, cy = column * 350 + 175, row * 325 + 171
                painter.drawImage(QRectF(cx - width * scale / 2, cy - height * scale / 2,
                                        width * scale, height * scale), image)
                painter.setPen(QColor("white"))
                painter.drawText(QRectF(column * 350, row * 325 + 5, 350, 25),
                                 Qt.AlignmentFlag.AlignCenter, name + (" T1" if row == 0 else " labels"))
                for text, rect in [(left, (column * 350 + 4, cy - 12, 25, 25)),
                                   (right, (column * 350 + 321, cy - 12, 25, 25)),
                                   (top, (cx - 12, row * 325 + 29, 25, 25)),
                                   (bottom, (cx - 12, row * 325 + 295, 25, 25))]:
                    painter.drawText(QRectF(*rect), Qt.AlignmentFlag.AlignCenter, text)
    finally:
        painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not canvas.save(buffer, "PNG"):
        raise RuntimeError("Report evidence export failed")
    return base64.b64encode(bytes(buffer.data())).decode("ascii")
