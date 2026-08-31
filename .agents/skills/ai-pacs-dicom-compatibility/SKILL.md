---
name: ai-pacs-dicom-compatibility
description: Diagnose and correct DICOM and medical-imaging compatibility in AI-PACS, including import and grouping, transfer syntaxes, pixel or waveform payloads, photometric transforms, multiframe and cine timing, geometry, ophthalmic objects, and Fast-versus-Advanced rendering differences. Use when a study is missing, black, corrupted, misordered, miscalibrated, non-playable, or displays differently in another workstation. Do not use for unrelated viewer UI defects or the public website.
---

# AI-PACS DICOM Compatibility

Use this workflow to turn a concrete interoperability failure into a standards-based, regression-guarded AI-PACS correction.

## Load the right context

1. Read `references/repository-map.md` for every investigation.
2. Read `references/standards-routing.md` when identifying an IOD, transfer syntax, functional group, calibration rule, waveform, or ophthalmic object.
3. Read `references/investigation-playbook.md` before inspecting a failing study or changing code.
4. Follow the repository `AGENTS.md`, `CLAUDE.md`, subsystem index, test guard index, and current readiness report. For stability work, update the existing `OPT-*` item in the master plan.

## Model the object in seven layers

Do not treat every readable DICOM file as a conventional 2D image. Classify the failure across these layers:

1. **Object identity and IOD**: SOP Class UID, modality, image versus waveform versus document/video, enhanced versus legacy object.
2. **Encoding**: transfer syntax, native or encapsulated pixel data, codec availability, bit depth, signedness, endian and VR rules.
3. **Frame or sample model**: single-frame, multiframe, concatenation, spatial stack, temporal phases, waveform channels, frame timing and dimension indices.
4. **Display transform**: photometric interpretation, planar configuration, palette/ICC, modality LUT or rescale, VOI/window, presentation LUT, padding and overlays.
5. **Geometry and calibration**: patient orientation/position, functional groups, pixel spacing, ultrasound region calibration, ophthalmic coordinates and units.
6. **AI-PACS identity and storage**: original versus imported file, decompression, Study/Series/SOP identity, collision handling, database grouping and cache keys.
7. **Execution domain**: Fast Viewer, Advanced Viewer, a dedicated modality/module renderer, thumbnail path, or an explicitly unsupported object.

Use SOP Class UID and the standard's IOD definition as the primary classifier. Modality, filename extension, folder layout, and Series Description are only clues. Preserve valid non-pixel objects during import, but never present them as black image cards; route them to a dedicated renderer or a truthful unsupported state.

## Investigate safely

- Keep patient data, DICOM files, reports, prompts, screenshots, paths, identifiers, and private tags local. Never upload them to web search, external tools, analytics, or committed fixtures.
- Prefer the bundled `scripts/inspect_dicom_sample.py` for a redacted structural inventory. Use `--decode` only on an explicitly selected local sample and within its resource limits.
- Record the exact application build, ingest route, storage location, backend, operating system, Python/package versions, and observed behavior.
- Compare the original source instance with the stored/imported instance before blaming rendering. Compare only structural values, salted or one-way UID labels, payload presence, decoder results, and local hashes.
- Form at least two competing hypotheses and falsify them at the earliest pipeline boundary. A different workstation's behavior is useful evidence, not a specification.

## Preserve architecture contracts

- Keep Fast Viewer, Advanced Viewer, and every VTK module as separate execution domains. Share only immutable, identity-keyed pure data through documented read-only helpers.
- Never perform filesystem, network, decode, AI, or VTK construction work on the Qt GUI thread.
- Never relabel compressed bytes with an uncompressed transfer syntax. Decode and rewrite coherently, or preserve the original encoding.
- Never fabricate geometry from filenames or arbitrary order when authoritative DICOM geometry is present. Never collapse temporal phases into a spatial stack.
- Test decoder availability in the actual target environment and packaged build; an importable Python module is not proof that a transfer syntax is supported.

## Turn diagnosis into a guarded correction

1. Reproduce with a synthetic or explicitly approved anonymized fixture that retains only the necessary structure.
2. Add the smallest regression guard that fails before the fix. Avoid real patient data and unreviewed binary fixtures.
3. Change the narrowest authoritative seam: import/storage, header classification, decoder selection, color transform, frame indexing/timing, geometry, or renderer routing.
4. Preserve existing worktree changes, offline behavior, cache identity, memory bounds, and source/package mirror parity.
5. Add the required row to `docs/plans/architecture/REGRESSION_CATALOG.md` and update the relevant subsystem/test indexes and existing plan item.
6. Run focused pytest directly with the supported interpreter and inspect its exit code. Run mirror and builder parity guards when mirrored code changes.
7. For live validation, use the source build only after the human launches and logs in once. Ask for clinical/radiologist confirmation when visual correctness or measurement meaning is involved.

## Report completion precisely

Separate these outcomes instead of saying only "supported":

- preserved by import;
- structurally classified;
- decoded in the development environment;
- decoded in the packaged environment;
- rendered in Fast Viewer;
- rendered in Advanced Viewer;
- rendered by a dedicated waveform/video/ophthalmic path;
- verified against an independent conformant implementation;
- clinically confirmed.

State remaining unsupported transfer syntaxes, IODs, dimensions, transforms, calibration rules, or environment gaps explicitly.
