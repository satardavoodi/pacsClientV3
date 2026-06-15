"""In-place de-identification of a staged consultation package (ADR-0003 / B3).

Runs AFTER ``export_studies_to_offline_cloud`` has staged the package and BEFORE
the envelope is sealed (sealing hashes every file, so it must see the final,
de-identified bytes). Pure python/pydicom — no Qt; blocking work stays on the
compose worker thread.

Clinical-safety rules (mirrors ``modules/cd_burner/dicom_prepare.py``, which is
NOT imported here because it ships in the separate ``run_cd`` package):

* A de-identification failure NEVER leaks an identified file — the file is
  DELETED from the staged package and reported, never uploaded as-is.
* The package layout is preserved (files are rewritten in place); study/series
  instance UIDs are intentionally NOT remapped so the package's own metadata
  (``metadata.json`` / ``reception.json``) keeps referencing the right objects
  and the receiver's ingest flow works unchanged. UIDs are pseudonymous; the
  identifying attributes below are blanked/replaced.
* Sidecar ``*.json`` files inside the package are scrubbed key-by-key so a
  patient name/ID can not survive in the manifest while the DICOM is clean.
* A ``deidentification.json`` summary is written into the package root so the
  receiving side can see that (and how) the package was de-identified.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

ANONYMOUS_VALUE = "ANONYMIZED"

# Same pragmatic basic-profile subset as the CD-burner preparer.
_BLANK_KEYWORDS = (
    "PatientBirthDate",
    "PatientBirthTime",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "OtherPatientIDs",
    "OtherPatientNames",
    "PatientMotherBirthName",
    "MilitaryRank",
    "EthnicGroup",
    "PatientComments",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "PhysiciansOfRecord",
    "RequestingPhysician",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
    "DeviceSerialNumber",
)

# JSON keys (case/sep-insensitive) whose values are replaced in sidecar files.
_JSON_SCRUB_KEYS = {
    "patientname",
    "patientid",
    "patientbirthdate",
    "patientbirthtime",
    "patientaddress",
    "patienttelephonenumbers",
    "otherpatientids",
    "otherpatientnames",
    "birthdate",
    "dateofbirth",
    "dob",
    "referringphysician",
    "referringphysicianname",
    "performingphysicianname",
    "operatorsname",
    "institutionname",
    "institutionaddress",
    "accessionnumber",
}


@dataclass
class DeidentifyResult:
    processed_files: int = 0      # DICOM files rewritten de-identified
    excluded_files: int = 0       # failures → deleted from the package
    scrubbed_json: int = 0        # sidecar json files scrubbed
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """False only when de-identification destroyed the package's images.

        An empty staging tree (no DICOM at all — e.g. unit tests stubbing the
        export engine) is fine; exclusions alongside surviving files are
        reported as warnings; exclusions that leave NO image are a hard fail.
        """
        if self.excluded_files and self.processed_files == 0:
            return False
        return True


def _norm_key(key: str) -> str:
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def _is_dicom_file(path: Path) -> bool:
    if path.suffix.lower() in (".dcm", ".dicom"):
        return True
    if path.suffix:
        return False
    try:
        from pydicom import dcmread

        dcmread(str(path), stop_before_pixels=True)
        return True
    except Exception:
        return False


def _iter_files(root: Path):
    for dirpath, _dirs, files in os.walk(str(root)):
        for name in files:
            yield Path(dirpath) / name


def _scrub_dataset(ds, seed: int) -> None:
    ds.PatientName = f"ANONYMOUS^{seed}"
    ds.PatientID = f"ANON{seed:04d}"
    if "AccessionNumber" in ds:
        ds.AccessionNumber = f"ANON{seed:04d}"
    for keyword in _BLANK_KEYWORDS:
        if keyword in ds:
            try:
                setattr(ds, keyword, "")
            except Exception:
                del ds[keyword]


def _scrub_json_value(value, hits: list):
    if isinstance(value, dict):
        scrubbed = {}
        for k, v in value.items():
            if _norm_key(k) in _JSON_SCRUB_KEYS and isinstance(v, (str, int, float)) and v != "":
                scrubbed[k] = ANONYMOUS_VALUE
                hits.append(k)
            else:
                scrubbed[k] = _scrub_json_value(v, hits)
        return scrubbed
    if isinstance(value, list):
        return [_scrub_json_value(v, hits) for v in value]
    return value


def deidentify_package(
    package_root: str,
    *,
    seed: int = 1,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> DeidentifyResult:
    """De-identify every DICOM + sidecar json under ``package_root`` IN PLACE."""
    result = DeidentifyResult()
    root = Path(package_root)
    if not root.exists():
        result.warnings.append(f"Package root does not exist: {package_root}")
        return result

    dicom_files = [p for p in _iter_files(root) if _is_dicom_file(p)]
    json_files = [p for p in _iter_files(root) if p.suffix.lower() == ".json"]
    total = len(dicom_files)

    for n, path in enumerate(dicom_files):
        if progress_callback and total:
            progress_callback(int(n * 100 / total), f"De-identifying {n + 1}/{total}")
        try:
            from pydicom import dcmread

            ds = dcmread(str(path))
            _scrub_dataset(ds, seed)
            ds.save_as(str(path), write_like_original=False)
            result.processed_files += 1
        except Exception as exc:
            # NEVER leave an identified file in the package.
            result.excluded_files += 1
            result.warnings.append(
                f"De-identification failed — file removed from package: {path.name} ({exc})"
            )
            try:
                path.unlink()
            except OSError as unlink_exc:  # pragma: no cover - defensive
                result.warnings.append(
                    f"FAILED to remove identified file {path.name}: {unlink_exc}"
                )

    for path in json_files:
        if path.name == "deidentification.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue  # not json we understand — leave untouched
        hits: list = []
        scrubbed = _scrub_json_value(payload, hits)
        if hits:
            try:
                path.write_text(
                    json.dumps(scrubbed, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                result.scrubbed_json += 1
            except Exception as exc:  # pragma: no cover - defensive
                result.warnings.append(f"Sidecar scrub failed for {path.name}: {exc}")

    try:
        summary = {
            "format": "aipacs-consultation-deidentification-v1",
            "policy": "basic-profile-subset (names/IDs/dates/physicians/institution blanked; UIDs preserved)",
            "processed_files": result.processed_files,
            "excluded_files": result.excluded_files,
            "scrubbed_json": result.scrubbed_json,
            "warnings": list(result.warnings),
        }
        (root / "deidentification.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("deidentification summary write failed: %s", exc)

    if progress_callback and total:
        progress_callback(100, "De-identification done")
    return result
