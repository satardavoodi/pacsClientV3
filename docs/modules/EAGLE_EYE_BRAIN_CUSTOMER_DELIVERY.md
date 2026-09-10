# Eagle Eye Brain customer delivery

Status: full portable Windows service passed on 2026-09-07: 101 posterior
measurements, 98 Slicer binary segments and a 29-page anatomically organized PDF with published intervals.
The latest DICOM rerun differs from the previous same-scan measurement by at most
0.000003 cm3; this is
software parity, not clinical validation. Canonical packaging is implemented; redistribution
evidence and clean Windows acceptance remain required. No release installer has
been produced from these changes.

Full-inference correction: the first Python 3.8 / TensorFlow 2.2 portable candidate
failed native Windows inference with exit 3221226505. Its CLI probe is insufficient
and it is not approved for distribution. The isolated Python 3.10.11 / TensorFlow
2.12.0 replacement passed full inference and PDF generation. The accepted local
candidate is `generated-files/eagle-eye/brain-tf212-py310`.

## Standard single-study workflow

The existing Brain chooser selects the T1 series belonging to the open study.
Its background worker calls `study_workflow.run_study_analysis`, then the Brain
service. The service performs SynthSeg parcellation, isolated headless Slicer
measurement, reference attachment and the standard organized PDF generation.
Save PDF report exports the completed PDF atomically to the user's chosen location.
The patient/study-specific original remains under User Data. No longitudinal
comparison script is part of this route.

The shared report includes regional groups, cortical parcels and lobar cortical
GM summaries, medial temporal measurements, available published reference
intervals and scientific citations. Red means strictly more than 25% beyond
the nearest reference endpoint. It is an attention rule, not a statistical
significance test. Cortical atlas analogues remain explicitly marked and do
not establish matched diagnostic cutoffs. Missing references remain unavailable;
no substitute numerical range or Z-score is invented.

## Installed assets

The model resolver now searches these locations in order:

1. Explicit administrator `AIPACS_BRAIN_BUNDLE` override.
2. `User Data/ai/eagle_eye/brain/model`.
3. `advanced_mpr/eagle_eye/brain/model` under module runtime roots, or the same
   payload under the installed ProgramData module package.
4. Legacy `eagle_eye_brain/model` under module runtime roots.
5. The accepted development candidate above, requiring a model-bound full-inference
   probe. The legacy development bundle is used only if this candidate is absent.
   A damaged candidate fails explicitly.

The selected model bundle must pass the existing pinned manifest and file hash
checks. Published reference files are resolved from the User Data reference
directory, or `references/volbrain` under the installed Eagle Eye Brain payload
(with legacy module-path compatibility). Local overrides must pass their
hash checks; damaged local files are not silently replaced with other tables.

Both canonical PyInstaller and Nuitka data lists include `slicer_worker.py` as an
actual file alongside the Brain module. Slicer launches this script externally, so
freezing it only as Python bytecode is insufficient.

## Preparation and packaging

`tools/slicer/prepare_portable_brain.py` prepares a fresh candidate from the
verified local Windows model bundle. It copies a real Python base and dependencies,
not the absolute-path virtual environment launcher, and writes a format-2 hash
manifest. The default output is `generated-files/eagle-eye/brain-tf212-py310`. Imports and
the SynthSeg CLI are tested with a separate cwd and isolated Python settings.
This does not test clinical accuracy or an installer on another computer.

Supply `--python-home` explicitly. The current candidate uses Python 3.10.11
embedded x64 from python.org and `tools/slicer/brain_windows_requirements.in`.
`dependencies.json` records resolved versions and the manifest hashes their files.
The preparation step removes TensorFlow C/C++ headers under `tensorflow/include`;
they are compile-time SDK material, are never loaded by inference, add no runtime
capability, and otherwise exceed the safe Inno Setup source-path budget.
Do not reuse the retired TensorFlow 2.2 environment. For a prepared Python already
at `<output>/model/python`, the tool can finalize that fresh Python-only tree in
place; it refuses to overwrite an existing model manifest or reference payload.
Then run `tools/slicer/probe_portable_brain.py` with a local T1, payload root and
private User Data output directory. It exercises the complete service and records
success/failure without adding patient identifiers to the packaged readiness file.

`builder/eagle_eye_brain_payload.py` validates and stages only explicit files:
manifested model assets, three reference CSVs, provenance and readiness records.
It never recursively packages User Data or validation outputs. The shared release
builder and package materializer call this stage. The Eagle Eye edition requires
Brain and Lumbar; Standard and ARM exclude Eagle Eye assets before copying.
The installer fails if the required Brain payload is absent. Both features remain
under Eagle Eye ownership in `modules/ai_imaging/eagle_eye/assets.py`; the existing
`offline_lumbar` disk path is retained for installed-version compatibility.

Set `AIPACS_EAGLE_EYE_BRAIN_SOURCE` to an approved immutable asset-cache location
when building from a separate source snapshot. Preparation does not create a
distribution approval. The release owner must supply `distribution-approval.json`
with `approved: true`, the exact `reference_revision`, `model_manifest_sha256`,
and actual `rights_evidence` document references. This receipt concerns asset
redistribution only; it is not permission for clinical release. Complete clean
Windows installer acceptance after producing the candidate, before customer
release, to avoid requiring an installation test before its installer exists.
Approval fields must describe completed review, never assumed or fabricated approval.
The model-bound runtime probe must also record `inference_status: passed`.

## Remaining delivery work

- Complete clean Windows installer acceptance for the portable candidate. Local
  full-service success does not establish frozen clean-machine acceptance.
- Resolve the applicable redistribution rights before putting the published
  normative CSV files into a commercial installer. The associated AssemblyNet
  software license has noncommercial/restriction language; independent rights
  for the CSV tables have not been established. Local availability is not a
  redistribution clearance. Reference calculations themselves do not require
  installing FreeSurfer, Linux or R on the customer's computer.
- Exercise missing/corrupt package behavior on the installed app. Runtime model
  and reference integrity checks remain active; missing reference values must not
  be presented as a complete referenced report.

## Cleanup status

Retired scorer source modules and their dedicated tests were removed. No R or
FreeSurfer call remains in the Brain product pipeline. Automatic execution review
rejected the requested removal of old reference directories and the dedicated
Windows R runtime by direct folder deletion. The official R uninstaller then
completed successfully and absence of Rscript was verified. Old reference data
and configurations were then moved to the reversible
`generated-files/retired-brain-references-20260907` archive. Only volBrain remains
in the active reference directory. FreeSurfer was removed through apt after the
replacement Windows service passed; its reconstruction executable is absent.
WSL, shared Slicer and private comparative jobs were preserved. Archives and
failed development candidates are excluded from the installer allowlist.

## Clean Windows acceptance

Use the canonical installer on a machine without the development checkout,
Python, FreeSurfer or developer environment variables. Validate the packaged
runtime and reference hashes, then run an authorized test T1 through the actual
Brain chooser. Check series identity, geometry, measurement units, reference
source/age/sex handling, PDF alignment and red boundary rules. Verify the
patient-specific saved result and byte-identical Save PDF As copy. Repeat with
network disconnected, paths containing spaces, missing or corrupted packages,
cancellation and an unwritable export destination. Compare resulting volumes
against the pinned source-runtime test dataset within documented tolerances.
Do not include private patient files in installer fixtures or build artifacts.

## Source verification

`test_eagle_eye_brain_customer_paths.py` exercises frozen model lookup,
installed reference discovery/local precedence and real App A worker collection.
Each new regression failed before its associated source fix. Adjacent workflow,
reference and PDF guards are also required. No heavyweight installer was built
and no live app was restarted for these changes.
