"""Deterministic planning and measurement contracts; no Qt, model or network imports."""
from dataclasses import dataclass
import csv
import math
from pathlib import Path


class BrainError(RuntimeError):
    """A patient-safe error suitable for the operator status area."""


@dataclass(frozen=True)
class BrainPlan:
    """The complete allowlist for future LLM recommendations.

    An LLM cannot set file paths, executable names, labels, normative values,
    crop dimensions or QC acceptance. A clinician still reviews the overlay.
    """
    profile: str = "standard"
    threads: int = 2

    def __post_init__(self):
        if not isinstance(self.profile, str) or self.profile not in {"standard", "robust"}:
            raise BrainError("Choose the standard or robust segmentation profile.")
        if type(self.threads) is not int or not 1 <= self.threads <= 8:
            raise BrainError("The CPU thread count must be between 1 and 8.")

    @classmethod
    def from_recommendation(cls, value):
        if not isinstance(value, dict) or set(value) - {"profile", "threads"}:
            raise BrainError("The proposed analysis settings are not supported.")
        return cls(**value)


def read_single_subject_csv(path):
    """Reject partial/duplicate/multi-subject output; never return the subject cell."""
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        rows = [row for row in csv.reader(stream) if row]
    if len(rows) != 2 or len(rows[0]) != len(rows[1]) or len(rows[0]) < 2:
        raise BrainError("The model returned an incomplete or ambiguous measurement table.")
    names = [name.strip() for name in rows[0][1:]]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise BrainError("The model returned duplicate or unnamed measurements.")
    try:
        values = [float(item) for item in rows[1][1:]]
    except ValueError:
        raise BrainError("The model returned a nonnumeric measurement.") from None
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise BrainError("The model returned an invalid measurement.")
    return dict(zip(names, values))


def volume_rows(volumes):
    """SynthSeg posterior volumes, not binary-mask Segment Statistics volumes."""
    icv = volumes.get("total intracranial")
    if icv is None or not math.isfinite(icv) or icv <= 0:
        raise BrainError("A valid model intracranial volume is required.")
    result = []
    for name, value in volumes.items():
        if not math.isfinite(value) or value < 0 or value > icv + 0.01:
            raise BrainError("A structure volume is inconsistent with intracranial volume.")
        result.append({"structure": name, "volume_mm3": value, "volume_cm3": value / 1000,
                       "icv_percent": value / icv * 100, "method": "SynthSeg posterior",
                       "percentile": None, "z_score": None,
                       "normative_status": "No qualified reference model installed"})
    return result


def geometry_voxel_volume(affine):
    import numpy as np
    matrix = np.asarray(affine, dtype=float)
    if (matrix.shape != (4, 4) or not np.isfinite(matrix).all()
            or not np.allclose(matrix[3], [0, 0, 0, 1])):
        raise BrainError("The image geometry is invalid.")
    volume = abs(float(np.linalg.det(matrix[:3, :3])))
    if volume < 1e-8:
        raise BrainError("The image geometry is singular.")
    return volume
