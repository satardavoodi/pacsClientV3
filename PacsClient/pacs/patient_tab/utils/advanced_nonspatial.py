"""Display ordering for single-frame US, deliberately not a patient-space volume.

Only the Advanced loader uses this fallback. CT/MR and partially spatial or
multiframe input retain the strict geometry contract. No pixel data is read here.
"""
from dataclasses import dataclass

import pydicom


@dataclass(frozen=True)
class NonSpatialUSPlan:
    dicom_files_for_itk: tuple[str, ...]
    _instances: tuple[tuple[tuple[str, object], ...], ...]
    study_uid: str
    series_uid: str

    def display_instances_metadata(self):
        return [dict(instance) for instance in self._instances]

    def stamp_metadata(self, metadata):
        # Metadata may be reused from a previously spatial load.
        for key in ("series_geometry_index", "_series_geometry_index_obj",
                    "display_order_hash", "canonical_order_hash"):
            metadata.pop(key, None)
        metadata.update(
            instances=self.display_instances_metadata(),
            spatial_geometry_available=False,
            instances_order_contract="ADVANCED_NONSPATIAL_US_INSTANCE_ORDER",
            _instances_geometry_sorted=False,
            _geometry_index_applied_reverse=False,
            display_convention_applied=False,
        )
        metadata.setdefault("series", {}).update(
            study_instance_uid=self.study_uid, series_instance_uid=self.series_uid,
            modality="US", orientation=None, geometry_plane="UNKNOWN",
            display_convention="UNKNOWN", spatial_geometry_available=False,
        )
        return metadata


def nonspatial_us_plan(files, *, study_uid_hint="", series_uid_hint=""):
    """Return an explicitly nonspatial plan, or None if eligibility is unproven."""
    instances = []
    identities = set()
    sizes = set()
    sops = set()
    for path in files:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        if (str(ds.get("Modality", "")).upper() != "US"
                or str(ds.get("SOPClassUID", "")) != "1.2.840.10008.5.1.4.1.1.6.1"
                or int(ds.get("NumberOfFrames", 1) or 1) != 1
                or ds.get("ImageOrientationPatient") is not None
                or ds.get("ImagePositionPatient") is not None):
            return None
        study_uid = str(ds.get("StudyInstanceUID", ""))
        series_uid = str(ds.get("SeriesInstanceUID", ""))
        sop = str(ds.get("SOPInstanceUID", ""))
        if (not study_uid or not series_uid or not sop or sop in sops
                or (study_uid_hint and study_uid != study_uid_hint)
                or (series_uid_hint and series_uid != series_uid_hint)):
            return None
        identities.add((study_uid, series_uid))
        sops.add(sop)
        rows, cols = int(ds.get("Rows", 0)), int(ds.get("Columns", 0))
        sizes.add((rows, cols, int(ds.get("SamplesPerPixel", 1))))
        if rows <= 0 or cols <= 0 or len(identities) != 1 or len(sizes) != 1:
            return None
        spacing = ds.get("PixelSpacing")
        instances.append(dict(
            instance_path=str(path), instance_number=int(ds.get("InstanceNumber", 0) or 0),
            sop_uid=sop, study_uid=study_uid, series_uid=series_uid,
            rows=rows, columns=cols,
            image_orientation_patient=None, image_position_patient=None,
            pixel_spacing=tuple(float(v) for v in spacing) if spacing else None,
            slice_thickness=None, spacing_between_slices=None,
            window_width=ds.get("WindowWidth"), window_center=ds.get("WindowCenter"),
            is_rgb=int(ds.get("SamplesPerPixel", 1)) > 1,
        ))
    if not instances:
        return None
    instances.sort(key=lambda item: (item["instance_number"], item["sop_uid"]))
    study_uid, series_uid = next(iter(identities))
    return NonSpatialUSPlan(
        tuple(item["instance_path"] for item in instances),
        tuple(tuple(item.items()) for item in instances), study_uid, series_uid,
    )
