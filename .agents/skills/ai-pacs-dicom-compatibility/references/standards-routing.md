# Standards and Library Routing

Use primary specifications and official library documentation. Search the web only with redacted structural terms: SOP Class UID, transfer syntax UID, tag keyword/number, library version and exception class. Never search with patient data, private tags, screenshots, files, UIDs from a patient study, or report text.

## Normative DICOM sources

- Current DICOM standard index: <https://dicom.nema.org/medical/dicom/current/output/chtml/>
- PS3.2 Conformance: <https://dicom.nema.org/medical/dicom/current/output/html/part02.html>
- PS3.3 Information Object Definitions: <https://dicom.nema.org/medical/dicom/current/output/html/part03.html>
- PS3.5 Data Structures and Encoding: <https://dicom.nema.org/medical/dicom/current/output/html/part05.html>
- PS3.6 Data Dictionary: <https://dicom.nema.org/medical/dicom/current/output/chtml/part06/ps3.6.html>
- Encapsulated Pixel Data: <https://dicom.nema.org/medical/dicom/current/output/chtml/part05/sect_A.4.html>
- Multiframe Functional Groups: <https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.16.html>
- Common Functional Group Macros: <https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.16.2.html>
- Waveform Module: <https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.10.9.html>
- Ultrasound Region Calibration: <https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.5.5.html>
- Ophthalmic Tomography IOD: <https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.52.html>
- Ophthalmic Tomography module table: <https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.52.3.html>

## Official library sources

- pydicom compressed image data: <https://pydicom.github.io/pydicom/stable/guides/user/image_data_handlers.html>
- pydicom waveform data: <https://pydicom.github.io/pydicom/stable/guides/user/working_with_waveforms.html>
- SimpleITK DICOM Series Reader example: <https://simpleitk.readthedocs.io/en/latest/link_DicomSeriesReader_docs.html>
- SimpleITK ImageSeriesReader API: <https://simpleitk.org/doxygen/latest/html/classitk_1_1simple_1_1ImageSeriesReader.html>

The stable pydicom documentation currently describes the 3.x pixel API, while this checkout uses pydicom 2.4.5. Verify an API against the installed version before adopting it; do not mechanically copy `pydicom.pixels` examples into the current runtime.

## Route the research question

| Symptom or object | Start with | Then inspect |
|---|---|---|
| Decode failure or corrupted pixels | PS3.5 transfer syntax and encapsulation | pydicom handler support, packaged codec parity, bits/signedness |
| Wrong colors | PS3.3 image pixel/VOI/palette/ICC modules | Photometric Interpretation, Planar Configuration, YBR subsampling, pydicom behavior |
| Multiframe order or cine failure | Multiframe Functional Groups | Dimension Index, Frame Content, temporal tags, concatenation and cache identity |
| Wrong spacing/measurements | Relevant IOD and functional-group macro | Pixel Measures, orientation/position, units and backend geometry |
| Ultrasound Doppler/flow calibration | Ultrasound Region Calibration | region coordinates, physical units, reference values and waveform/image distinction |
| ECG/hemodynamic data | Waveform Module and SOP Class definition | channel definitions, sampling frequency, multiplex groups and pydicom waveform APIs |
| Ophthalmic/OCT object | Ophthalmic IOD/module table | raster frames versus maps/measurements, coordinate systems and registration |
| Advanced Viewer series mismatch | IOD geometry plus SimpleITK docs | acquisition-direction sorting, metadata loading and AI-PACS canonical contracts |

## Evidence hierarchy

Use evidence in this order:

1. DICOM normative specification and the object's Conformance Statement.
2. Official pydicom, SimpleITK/GDCM and VTK documentation for the installed version.
3. Minimal local reproducer and instrumented boundary observations.
4. Independent conformant workstation behavior.
5. Vendor notes, issue trackers and community reports.

If sources conflict, document the conflict and prefer normative requirements over observed vendor behavior. Private tags and vendor-specific semantics require a vendor dictionary or conformance documentation; do not guess them.
