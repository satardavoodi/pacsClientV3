# Enhanced MR Multi-frame Mixed with Raw Data — Diagnosis and Guarded Fix

**Date:** 2026-09-01

**Status:** Fast Viewer defect reproduced, fixed, and automatically verified; source-build visual confirmation pending

**Privacy:** This report contains no patient identifiers, clinical paths, raw UIDs, acquisition dates, pixel digests, images, or private-tag values.

## Outcome

The supplied study did not contain one image per series. Its pixel-bearing objects are uncompressed Explicit VR Little Endian Enhanced MR Image Storage instances with real multi-frame Pixel Data and Shared/Per-Frame Functional Groups. The inspected pixel series represent 1,945 frames in 32 series.

Nineteen series also contain a metadata-only Raw Data Storage object under the same Series Instance UID. Raw Data Storage is a distinct non-raster IOD; it must be preserved by storage but must not become an image slice.

The Fast Viewer metadata projection omitted `NumberOfFrames`. Its fallback probed only the first object. This produced two order-dependent failures:

- Raw Data first: the first probe returned one frame and the Enhanced MR object was never probed, so the series stayed at its object count.
- Enhanced MR first: the Enhanced object expanded, but the Raw Data object remained as one additional invalid image slice.

The smallest real reproduction expected three Enhanced MR frames. Before correction, Raw-first produced two slices and Enhanced-first produced four. Enhanced-only produced the correct three.

## Standards boundary

Enhanced MR uses the Multi-frame Functional Groups and Multi-frame Dimension modules. Raw Data Storage maps to the separate Raw Data IOD and does not become a raster image merely because it shares a Series UID with an image object.

- https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.36.2.3.html
- https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.36.2.4.html
- https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.37.html
- https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.37.3.html

## Implemented correction

`PacsClient.utils.dicom_displayability.dicom_file_pixel_facts` is the shared low-cost authority for pixel-element presence and frame count. It uses a partial DICOM read that stops at the pixel element, so it does not decode or load the pixel value.

The Fast Viewer now:

1. skips leading metadata-only objects until it reaches the first pixel-bearing object;
2. preserves the ordinary many-file single-frame path after one probe;
3. when it finds a multi-frame object, probes the remaining small mixed-object set;
4. expands every pixel-bearing multi-frame object;
5. excludes non-pixel objects from the viewport without deleting or rewriting them.

This logic is independent of metadata ordering and remains inside the pydicom/NumPy/Qt execution domain. The Advanced Viewer and VTK/MPR volume route were not changed by this correction; their existing multi-frame eligibility boundary remains separate.

## Verification

The new synthetic guard failed before the correction for both metadata orders:

- Raw-first: two slices instead of three.
- Enhanced-first: four slices instead of three.

After correction, the complete Fast multi-frame guard file passed 22 tests.

Read-only validation across the supplied study then reported:

- 32/32 pixel series matched their expected frame counts;
- 1,945 expected frames and 1,945 projected Fast Viewer frames;
- 19 metadata-only objects encountered and zero projected as images;
- three bounded end-to-end pixel decodes succeeded;
- source files were not modified.

## Remaining gate

Open the supplied study in the source build and confirm that the viewport slice counter and scrolling expose all frames for representative short and long Enhanced MR series. This visual source-build check remains required; it is not a release or clinical-validation claim.
