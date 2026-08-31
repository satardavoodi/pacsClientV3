# DICOM Format Compatibility Operating Guide

**Date:** 2026-08-30

**Scope:** Local import, PACS-delivered objects, thumbnails, Fast Viewer, Advanced Viewer, and dedicated medical-object renderers

**Companion workflow:** [AI-PACS DICOM Compatibility skill](../../.agents/skills/ai-pacs-dicom-compatibility/SKILL.md)

## Purpose

This guide establishes the repository-level operating model for investigating new DICOM and medical-imaging compatibility failures. It does not claim universal DICOM conformance and it does not change runtime behavior by itself.

The unit of compatibility is not a filename or modality label. It is a specific information object, transfer syntax, frame/sample model, display transform, geometry/calibration contract, ingest route, renderer, and packaged environment.

## Capability vocabulary

Use these states independently in plans, bug reports and release notes:

| Capability | Evidence required |
|---|---|
| Preserved | Import/PACS storage retains a coherent DICOM object and identity. |
| Classified | SOP Class/IOD and payload kind route to an appropriate surface. |
| Decoded | The exact transfer syntax and payload decode in the named environment. |
| Displayed | Photometric, LUT/window, frame and geometry semantics render correctly. |
| Interactive | Cine, waveform, measurements or modality-specific interaction works. |
| Packaged | Codec, plugin, mirror and runtime parity are proven in the installed build. |
| Interoperable | Behavior agrees with the standard and an independent conformant implementation. |
| Clinically verified | A qualified human confirms visual/measurement meaning for the use case. |

`pydicom.dcmread()` success proves none of the later states. Likewise, a valid DICOM object may be a waveform, document, video or measurement object rather than a raster image.

## Current architecture baseline

### Ingest and storage

- Local import groups by Study Instance UID and Series Instance UID and can decompress supported pixel data before storing Explicit VR Little Endian.
- PACS transport compression and DICOM transfer-syntax compression are distinct layers.
- Original-versus-stored comparison is mandatory when an imported object fails but the source displays elsewhere.
- Pixel-bearing, waveform, document and metadata-only objects require separate classification. Metadata-only objects must not become black image cards.

### Fast Viewer

Fast Viewer is the pydicom/NumPy/Qt domain. It owns frame-aware decoding, YBR normalization and conversion, frame-level cache identity, functional-group geometry and cine timing. It must remain independent of VTK runtime construction.

High-risk boundaries include decoder selection for the installed pydicom version, multiple multiframe instances in one series, concatenations, spatial-versus-temporal dimension classification, color transforms, per-frame windows and bounded cache/decode behavior.

### Advanced Viewer

Advanced Viewer is the SimpleITK/GDCM-to-ITK-to-NumPy-to-VTK domain. It depends on acquisition-direction ordering and the repository's canonical geometry/axis contracts. A successful SimpleITK read is insufficient if the file list, spacing, direction or downstream VTK conversion is wrong.

### Dedicated object families

Waveform Sequence objects such as ECG/hemodynamic recordings, encapsulated documents/video, and specialized ophthalmic measurements or maps cannot be assumed to belong in either generic raster viewer. They require an explicit product route, meaningful controls and truthful unsupported behavior until that route exists.

## Required investigation sequence

1. Capture the exact source/build, ingest route, failing surface and symptom without patient data.
2. Identify SOP Class UID, payload kind, transfer syntax, frame/sample structure and required calibration using the current DICOM standard.
3. Run the skill's redacted inventory tool on an explicitly selected local copy.
4. Compare original and stored representations before testing a renderer.
5. Test the earliest boundary first: preservation, identity, codec, pixels/samples, transform, geometry, routing, package parity or resources.
6. Reproduce with a synthetic or approved anonymized fixture.
7. Add a failing semantic regression guard, make the smallest fix, update the regression catalog and synchronize package mirrors when applicable.
8. Verify the focused test cluster, packaged environment, source-build live behavior and clinical meaning as appropriate.

## Privacy and evidence rules

- DICOM instances, images, waveforms, reports, paths, patient identifiers, acquisition dates, raw study/series/instance UIDs and private tags stay local.
- Internet research uses only standard tag numbers/keywords, standard SOP Class or transfer syntax UIDs, library versions and redacted exception classes.
- Public or synthetic fixtures require provenance and license review before they enter the repository.
- Vendor/private semantics require a conformance statement or vendor dictionary. Do not infer them from visual coincidence.
- Another workstation is a valuable comparator, but the DICOM standard and declared conformance remain the primary authority.

## Authoritative sources

- [Current DICOM standard](https://dicom.nema.org/medical/dicom/current/output/chtml/)
- [DICOM PS3.3 Information Object Definitions](https://dicom.nema.org/medical/dicom/current/output/html/part03.html)
- [DICOM PS3.5 Data Structures and Encoding](https://dicom.nema.org/medical/dicom/current/output/html/part05.html)
- [pydicom compressed image data](https://pydicom.github.io/pydicom/stable/guides/user/image_data_handlers.html)
- [pydicom waveform data](https://pydicom.github.io/pydicom/stable/guides/user/working_with_waveforms.html)
- [SimpleITK DICOM Series Reader](https://simpleitk.readthedocs.io/en/latest/link_DicomSeriesReader_docs.html)

The repository currently uses pydicom 2.4.5, while the stable online guide describes newer 3.x APIs. Any API change must be verified against the installed and packaged versions.

## Known baseline gaps to test, not silently assume

- Codec capability must be tested per transfer syntax in the real development and packaged environments; module import alone is not a capability check.
- No general renderer was found for Waveform Sequence ECG/hemodynamic objects or encapsulated documents/video.
- Specialized ophthalmic objects may require coordinates, registration, maps and measurement semantics beyond frame display.
- Multiframe series with multiple instances or concatenations require explicit coverage.
- Import warning text and actual decompression behavior must remain aligned.
- Current Fast Viewer derived-stack-geometry comment/default behavior should not be altered without a concrete reproducer and guard.

These are investigation targets, not declarations that every instance in each family is broken.
