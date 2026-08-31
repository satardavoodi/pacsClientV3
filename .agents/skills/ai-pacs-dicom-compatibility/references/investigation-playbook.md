# DICOM Compatibility Investigation Playbook

## 1. Establish a PHI-safe intake

Record in a local, uncommitted work note:

- AI-PACS build/commit and source versus packaged runtime;
- acquisition/vendor family only when approved;
- ingest route: PACS socket, local import, existing database or direct file;
- failing surface: import list, thumbnail, Fast Viewer, Advanced Viewer or dedicated module;
- exact symptom and expected behavior;
- whether the original and stored instances differ;
- whether another workstation displays, measures or plays the object correctly.

Do not copy patient names, IDs, accession numbers, dates, paths, raw UIDs, images or reports into issues, prompts, documentation or fixtures.

## 2. Inventory structure before decoding

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe .agents\skills\ai-pacs-dicom-compatibility\scripts\inspect_dicom_sample.py '<explicit-local-path>' --pretty
```

For a bounded decode check:

```powershell
.\.venv\Scripts\python.exe .agents\skills\ai-pacs-dicom-compatibility\scripts\inspect_dicom_sample.py '<explicit-local-path>' --decode --max-decode-files 3 --pretty
```

The report intentionally hashes UIDs and omits paths and patient attributes. Keep the report local unless its contents have been reviewed for sensitivity.

## 3. Compare source and stored representations

Compare the original and AI-PACS-stored instances locally:

- SOP/Study/Series identity equality as booleans, not raw values;
- transfer syntax and encapsulated/native state;
- payload kind and frame count;
- rows, columns, samples, photometric interpretation and bit fields;
- functional-group/waveform/calibration presence;
- file/pixel byte hashes and decode-array digest when lawful and useful;
- decoder outcome in development and packaged environments.

A changed file hash is not automatically corruption: legitimate decompression and metadata rewriting change bytes. Validate the semantic pixel array and required metadata.

## 4. Build a backend matrix

Test the smallest useful matrix and record each state independently:

| Boundary | Questions |
|---|---|
| Import inventory | Was the object preserved, grouped and classified correctly? |
| Stored object | Did transfer syntax, payload and identity remain coherent? |
| pydicom decode | Can the installed handler decode the selected frame locally? |
| Fast Viewer | Are frame selection, color, LUT/window, geometry and cine correct? |
| SimpleITK/GDCM | Can the actual ordered series be read with correct dimensions/metadata? |
| Advanced Viewer | Are canonical order, axes, spacing and VTK conversion correct? |
| Dedicated renderer | Is this a waveform/video/specialized IOD that should bypass image viewers? |
| Packaged runtime | Are codecs, plugins and mirrored source present and equivalent? |

## 5. Classify the root cause

Choose the earliest failing class:

- invalid or unsupported DICOM object;
- import filtering or identity/grouping;
- transfer-syntax/codec capability;
- native pixel interpretation or bit unpacking;
- color/LUT/window/presentation transform;
- multiframe dimension, concatenation or temporal model;
- geometry/order/calibration;
- cache identity or stale metadata;
- renderer routing/unsupported IOD;
- packaging or environment parity;
- performance/resource bound.

Keep at least one alternative hypothesis until a boundary observation falsifies it.

## 6. Design the regression guard

Prefer a generated, synthetic DICOM fixture containing only the attributes needed to reproduce the defect. For compressed transfer syntaxes, use a redistributable public conformance fixture only after checking its license and provenance, or generate it with an available encoder. Never commit clinical data, even if identifiers appear blank.

The guard must fail before the fix and assert the semantic contract, such as:

- correct series grouping despite duplicate Series Number;
- handler capability for the exact transfer syntax;
- decoded pixel values/colors, not just absence of an exception;
- frame-level spatial/temporal order;
- correct duration/frame timing;
- spacing/orientation/calibrated units;
- truthful dedicated routing instead of a black image.

## 7. Verify and record

Run focused tests directly and check the exit code:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONPATH = '.'
.\.venv\Scripts\python.exe -m pytest -p no:debugging <focused-test-path> -q
```

Also run, when relevant:

- the neighboring existing guard cluster;
- source/package mirror verification;
- builder codec/parity guards;
- a bounded memory/performance check for large multiframe data;
- source-build live validation after human launch/login;
- independent workstation comparison and clinical confirmation.

Add a row to `docs/plans/architecture/REGRESSION_CATALOG.md`, update subsystem/test indexes, and extend the existing optimization/reliability plan item rather than creating an isolated plan.
