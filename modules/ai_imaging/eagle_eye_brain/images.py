"""Worker-only image preparation. Report identity is separate from clean model inputs."""
from pathlib import Path
import re
import numpy as np
from .contracts import BrainError


def read_volume(path, *, expected_protocol="t1"):
    import SimpleITK as sitk
    if expected_protocol not in {"t1", "flair"}:
        raise BrainError("Unsupported brain input protocol.")
    source = Path(path)
    if source.is_dir():
        series = sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(source))
        if len(series or ()) != 1:
            raise BrainError("Select a directory containing exactly one DICOM series.")
        files = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(source), series[0])
        # Enhanced MR requires a qualified multiframe converter, not an implicit
        # classic-slice fallback. NIfTI exported by dcm2niix is supported.
        import pydicom
        positions = []
        orientation = None
        for filename in files:
            ds = pydicom.dcmread(filename, stop_before_pixels=True,
                                specific_tags=["NumberOfFrames", "ImagePositionPatient", "ImageOrientationPatient",
                                               "Modality", "SOPClassUID", "MRAcquisitionType",
                                               "SeriesDescription", "ProtocolName"])
            # Reject explicit contradictions; missing/vendor-specific descriptions
            # still require operator verification and are not positive classification.
            description = " ".join(str(getattr(ds, key, "")) for key in
                                   ("SeriesDescription", "ProtocolName")).lower()
            tokens = set(re.findall(r"[a-z0-9]+", description))
            if expected_protocol == "t1" and tokens & {"t2", "t2w", "flair", "swi", "dwi", "adc", "diff"}:
                raise BrainError("DICOM sequence metadata contradicts the selected T1-weighted role. Select the original MPRAGE series.")
            if expected_protocol == "flair" and (tokens & {"t1", "t1w", "mprage"}
                                                  or (tokens & {"t2", "t2w"} and "flair" not in tokens)):
                raise BrainError("DICOM sequence metadata contradicts the selected FLAIR role.")
            if int(getattr(ds, "NumberOfFrames", 1)) != 1:
                raise BrainError("Export this enhanced MR series with dcm2niix and select its NIfTI file.")
            if str(getattr(ds, "Modality", "")) != "MR" or str(getattr(ds, "SOPClassUID", "")) != str(pydicom.uid.MRImageStorage):
                raise BrainError("The direct DICOM path requires classic MR images; use a qualified NIfTI export for other objects.")
            if str(getattr(ds, "MRAcquisitionType", "")).upper() == "2D":
                raise BrainError("This protocol requires a 3D MR acquisition.")
            current = np.asarray(getattr(ds, "ImageOrientationPatient", []), dtype=float)
            position = np.asarray(getattr(ds, "ImagePositionPatient", []), dtype=float)
            if current.shape != (6,) or position.shape != (3,):
                raise BrainError("DICOM geometry is incomplete.")
            if orientation is None:
                orientation = current
            if not np.allclose(orientation, current, atol=1e-5):
                raise BrainError("The selected series has inconsistent slice orientations.")
            positions.append(position)
        if len(positions) < 3:
            raise BrainError("A complete three-dimensional brain volume is required.")
        delta = np.diff(positions, axis=0)
        normal = np.cross(orientation[:3], orientation[3:])
        distances = delta @ normal
        if (np.any(distances <= 0) or not np.allclose(distances, distances[0], rtol=0.01, atol=0.01)
                or not np.allclose(delta, distances[:, None] * normal, atol=0.01)):
            raise BrainError("DICOM slices have gaps, duplicates or unsupported shear.")
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(files)
        image = reader.Execute()
    else:
        if not source.name.lower().endswith((".nii", ".nii.gz")):
            raise BrainError("Select a NIfTI image or a single-series DICOM directory.")
        image = sitk.ReadImage(str(source))
    validate_image(image)
    # Reconstruct from the pixel buffer so no private DICOM/NIfTI metadata travels.
    clean = sitk.GetImageFromArray(sitk.GetArrayFromImage(image).astype(np.float32))
    clean.CopyInformation(image)
    return clean


def validate_image(image):
    import SimpleITK as sitk
    if image.GetDimension() != 3 or image.GetNumberOfComponentsPerPixel() != 1:
        raise BrainError("A scalar 3D image is required; time series and quantitative maps are not this protocol.")
    if min(image.GetSize()) < 3 or np.prod(image.GetSize(), dtype=np.int64) > 256 * 1024 * 1024:
        raise BrainError("The image dimensions are unsupported.")
    spacing = np.asarray(image.GetSpacing())
    direction = np.asarray(image.GetDirection()).reshape(3, 3)
    if (not np.isfinite(spacing).all() or np.any(spacing <= 0) or not np.isfinite(direction).all()
            or not np.allclose(direction.T @ direction, np.eye(3), atol=1e-4)
            or not np.isfinite(image.GetOrigin()).all()):
        raise BrainError("The image geometry is invalid.")
    array = sitk.GetArrayViewFromImage(image)
    if not np.isfinite(array).all() or np.ptp(array) <= 0:
        raise BrainError("The image is empty, constant or contains invalid intensities.")


def register_flair(t1, flair, cancel):
    """Deterministic rigid MI registration; review is required, not inferred from convergence."""
    import SimpleITK as sitk
    registration = sitk.ImageRegistrationMethod()
    registration.SetMetricAsMattesMutualInformation(32)
    registration.SetMetricSamplingStrategy(registration.RANDOM)
    registration.SetMetricSamplingPercentage(0.1, 1729)
    registration.SetInterpolator(sitk.sitkLinear)
    registration.SetOptimizerAsRegularStepGradientDescent(2.0, 0.001, 150)
    registration.SetOptimizerScalesFromPhysicalShift()
    registration.SetShrinkFactorsPerLevel([4, 2, 1])
    registration.SetSmoothingSigmasPerLevel([2, 1, 0])
    registration.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    initial = sitk.CenteredTransformInitializer(t1, flair, sitk.Euler3DTransform(),
                                               sitk.CenteredTransformInitializerFilter.GEOMETRY)
    registration.SetInitialTransform(initial, inPlace=False)
    registration.AddCommand(sitk.sitkIterationEvent,
                            lambda: registration.StopRegistration() if cancel.is_set() else None)
    transform = registration.Execute(t1, flair)
    if cancel.is_set():
        raise BrainError("Brain analysis cancelled.")
    aligned = sitk.Resample(flair, t1, transform, sitk.sitkLinear, 0.0, sitk.sitkFloat32)
    validate_image(aligned)
    return aligned, transform
