"""Build-bound MPR orientation receipt; contains no patient identifiers.

Version 1 describes the unresampled decoder buffer (before the existing Y/X
display reversals). It is not a voxel-to-patient affine. The reader supplies
metadata in the exact order of the decoded pixels, including any size fallback.
Do not reconstruct this receipt from a directory, a viewport or InstanceNumber.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

FIELD_NAME = "AIPacsMPRStackGeometryV1"
_LENGTH = 52


def _grid(image):
    return tuple(image.GetSize()) + tuple(image.GetSpacing()) + tuple(image.GetOrigin())


def record_reader_geometry(reader, image):
    """Record the regular spatial lattice actually decoded; never alter pixels.

    The reader's metadata dictionaries must be enabled before Execute. Repeated
    positions/time points, mixed identities/planes, irregular spacing, unsupported
    shear and incomplete facts produce an explicit invalid receipt, not a guessed
    direction. Ordinary 2D viewing remains available.
    """
    receipt = np.zeros(_LENGTH, dtype=float)
    receipt[0] = 1
    if image.GetDimension() != 3:
        return
    receipt[2:11] = _grid(image)
    try:
        count = image.GetSize()[2]
        if count < 2 or len(reader.GetFileNames()) != count:
            raise ValueError("not a single-frame spatial stack")

        def text(index, tag):
            return reader.GetMetaData(index, tag).strip().strip("\0") if reader.HasMetaDataKey(index, tag) else ""

        def numbers(index, tag, size):
            value = np.asarray([float(v) for v in text(index, tag).split("\\")])
            if value.shape != (size,) or not np.all(np.isfinite(value)):
                raise ValueError("missing spatial facts")
            return value

        ipps, iops, identity, sops = [], [], [], []
        digest = hashlib.sha256()
        for k in range(count):
            if int(text(k, "0028|0008") or "1") != 1:
                raise ValueError("multiframe requires a qualified builder")
            ipp = numbers(k, "0020|0032", 3)
            iop = numbers(k, "0020|0037", 6)
            spacing = numbers(k, "0028|0030", 2)
            if (int(text(k, "0028|0010")), int(text(k, "0028|0011"))) != tuple(image.GetSize()[1::-1]):
                raise ValueError("inconsistent image matrix")
            if not np.allclose(spacing[::-1], image.GetSpacing()[:2], rtol=1e-4, atol=1e-5):
                raise ValueError("inconsistent pixel spacing")
            ids = tuple(text(k, tag) for tag in ("0020|000d", "0020|000e", "0020|0052"))
            sop = text(k, "0008|0018")
            if not ids[0] or not ids[1] or not sop:
                raise ValueError("missing stack identity")
            identity.append(ids)
            sops.append(sop)
            ipps.append(ipp)
            iops.append(iop)
            digest.update(json.dumps((ids, sop, ipp.tolist(), iop.tolist(), spacing.tolist()), separators=(",", ":")).encode())
        if len(set(identity)) != 1 or len(set(sops)) != count:
            raise ValueError("mixed or repeated frames")
        ipps, iops = np.asarray(ipps), np.asarray(iops)
        if not np.allclose(iops, iops[0], rtol=0, atol=1e-4):
            raise ValueError("varying planes")
        row, col = iops[0].reshape(2, 3)
        if not np.allclose([np.linalg.norm(row), np.linalg.norm(col), row @ col], [1, 1, 0], atol=1e-4):
            raise ValueError("invalid orientation")
        step = (ipps[-1] - ipps[0]) / (count - 1)
        length = np.linalg.norm(step)
        if length < 1e-5:
            raise ValueError("repeated positions")
        tolerance = max(.01, length * .005)
        if not np.allclose(ipps, ipps[0] + np.arange(count)[:, None] * step, rtol=0, atol=tolerance):
            raise ValueError("irregular spatial stack")
        if not np.isclose(length, image.GetSpacing()[2], rtol=.005, atol=.01):
            raise ValueError("decoder spacing mismatch")
        axis = step / length
        if abs(float(axis @ np.cross(row, col))) < 1 - 1e-5:
            raise ValueError("sheared stack requires a qualified builder")
        if not np.allclose(ipps[0], image.GetOrigin(), atol=.01, rtol=0):
            raise ValueError("decoder origin mismatch")
        receipt[11:20] = np.concatenate((row, col, axis))
        receipt[20:] = list(digest.digest())
        receipt[1] = 1
    except (ValueError, TypeError, RuntimeError, IndexError):
        pass
    image.SetMetaData(FIELD_NAME, json.dumps(receipt.tolist(), separators=(",", ":")))


def attach_values(vtk_image, values):
    """Copy the receipt with its pixels across conversion/IPC boundaries."""
    if values is None:
        return
    import vtkmodules.all as vtk
    array = vtk.vtkDoubleArray()
    array.SetName(FIELD_NAME)
    for value in values:
        array.InsertNextValue(float(value))
    vtk_image.GetFieldData().AddArray(array)


def copy_from_itk(itk_image, vtk_image):
    if itk_image.HasMetaDataKey(FIELD_NAME):
        attach_values(vtk_image, json.loads(itk_image.GetMetaData(FIELD_NAME)))


def values_from_vtk(image):
    fd = image.GetFieldData()
    array = fd.GetArray(FIELD_NAME) if fd is not None else None
    if array is None:
        return None
    return tuple(array.GetValue(i) for i in range(array.GetNumberOfValues()))


def geometry_status(image):
    """Return valid/missing/invalid without filesystem reads or pixel copies."""
    values = values_from_vtk(image)
    if values is None:
        return "missing"
    data = np.asarray(values)
    if len(data) != _LENGTH or not np.all(np.isfinite(data)) or tuple(data[:2]) != (1, 1):
        return "invalid"
    grid = tuple(image.GetDimensions()) + tuple(image.GetSpacing()) + tuple(image.GetOrigin())
    if not np.allclose(data[2:11], grid, rtol=0, atol=1e-6):
        return "invalid"
    axes = data[11:20].reshape(3, 3)
    if not np.allclose(axes @ axes.T, np.eye(3), rtol=0, atol=2e-4):
        return "invalid"
    if image.GetExtent() != (0, int(data[2]) - 1, 0, int(data[3]) - 1, 0, int(data[4]) - 1):
        return "invalid"
    direction = image.GetFieldData().GetArray("DirectionMatrix")
    if direction is None or direction.GetNumberOfValues() != 16:
        return "invalid"
    matrix = np.asarray([direction.GetValue(i) for i in range(16)]).reshape(4, 4)
    matrix[1, :] *= -1  # Historical storage convention, not an image operation.
    if not np.allclose(matrix[:3, :2].T, axes[:2], rtol=0, atol=1e-4):
        return "invalid"
    return "valid"


def slice_axis_from_volume(image):
    """Signed patient-space direction of increasing buffer k."""
    if geometry_status(image) != "valid":
        return None
    return list(values_from_vtk(image)[17:20])
