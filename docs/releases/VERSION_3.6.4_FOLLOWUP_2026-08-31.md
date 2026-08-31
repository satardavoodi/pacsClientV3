# AI-PACS 3.6.4 source follow-up — 2026-08-31

## Scope and version

This batch publishes the reviewed project changes accumulated after `fa2f3126` to `main` and
`beta-version` on `Vahid-INO/ai-pacs`, `satardavoodi/PacsClientV2`, and
`satardavoodi/pacsClientV3`. Product identifiers in `pyproject.toml` and `main.py` remain **3.6.4**.
The previously published `v3.6.4` tag is not moved or rewritten. A later installer must record the
exact source commit it actually builds; that older tag does not contain this follow-up.

No installer build, installation, extension installation, clinical model run, or production
deployment is performed by this publication task.

## Included work

### DICOM import, local series identity, and Fast Viewer

- Separate image-bearing DICOM objects from metadata-only objects without decoding pixel payloads.
  Preserve non-image files on disk while avoiding blank image cards and incorrect image counts.
- Preserve each series' exact persisted storage path when multiple series share a DICOM series
  number. Allocate numeric UI aliases without confusing them with collision-suffixed folder names.
- Carry original series metadata through local imports, cached thumbnails, drag/open handling,
  and study-scoped references. Prefer SeriesInstanceUID for image-count updates.
- Recover color facts from each decoded object when projected database metadata is incomplete;
  avoid treating RGB arrays as grayscale cine stacks or using an unsafe subprocess decode path.
- Expand supported multi-object cine content using object-specific frame counts. Keep Fast Viewer
  separate from VTK execution domains.
- Add the DICOM compatibility operating guide and repository-local investigation skill.

### Eagle Eye evidence and analysis

- Advance the lumbar analysis pipeline to **4.6.1**, retaining the existing EchoMind/GapGPT
  credential and transport authorities.
- Refine pathology-focus adjudication, paired sagittal clinical context, laterality, same-lesion
  cross-plane reasoning, and original capture-frame numbering.
- Add shared DICOM evidence services and local-only source provenance for worker-side image
  preparation; original captures are preserved.
- Add opt-in `focused-v2`, `focused-v3`, and `focused-v3-parasagittal` verification evidence.
  Default `layout` mode remains unchanged. Focused paths enforce image budgets, same-slab
  coverage, explicit geometry/provenance, quality checks, and a visible layout fallback.
- Add benchmark tooling with externally stored references and scorer **1.1.0**. The scoped
  root-negation correction is implemented; the documented remaining scoring/reference issues
  still prevent aggregate scores from being treated as clinical accuracy evidence.

The focused morphology research plan distinguishes implemented preflight work from proposed
localization, independent diagnosis, and future clinical evaluation. It is not a declaration that
all proposed phases are implemented or clinically validated.

### Slicer investigation and developer tooling

- Add synthetic control-probe scripts, the source-linked runtime control audit, extension source
  manifest, operational guides, and tool-augmentation feasibility report.
- These describe a bounded synthetic capability investigation. They do not introduce a production
  LLM control loop or make unverified Slicer effects clinically available. In particular, the
  audit's Mask volume compatibility issue remains documented, not silently marked fixed.

## Verification performed for publication

All pytest runs used the source environment directly, offscreen, with live/build/slow/property
lanes excluded. The PowerShell wrapper was not used as evidence.

| Check | Result |
| --- | --- |
| Complete `tests/code/ai_imaging` | 675 passed, 8 existing xfailed; exit 0 |
| Changed and adjacent viewer/import/series/thumbnail checks, credential guard, and default-build inclusion | 174 passed, 3 existing local-fixture tests skipped; exit 0 |
| Source/plugin mirror verification | 458 pairs matched; no plugin-only files |
| Staged Python / JSON syntax | 50 Python files and 1 JSON manifest parsed successfully |
| Staged privacy/credential checks | No credential-shaped values in staged files; no newly added study-UID or session-ID signatures |
| Publication diff and runtime dependencies | `git diff --cached --check` and `pip check` passed |
| Staged package catalog | Original 15-package feed retained; empty working feed excluded |

The earlier credential-hardening safeguards remain in place. The prior timeout investigation
showed correct credential mapping and a provider read timeout, not a decryption failure; this batch
does not claim to fix provider availability. No raw logs, images, references, clinical requests,
or generated model responses are included in this publication.

## Publication hygiene and exclusions

A real study identifier in an untracked benchmark CLI example was replaced with a placeholder
before staging. Benchmark documentation was generalized without changing executable behavior.

The following local state is deliberately left on disk and excluded from the commit:

- `builder nuitka/output/**`: existing local build states, checkpoints, and reports.
- `config/patient_table_sort.json`: local user preference.
- `generated-files/**`: runtime profiles, model diagnostics, Slicer probe outputs, and downloaded
  extension research material.
- `builder/plugin package/packages/module_package_feed.json`: the working file contains zero
  packages while the committed feed contains 15. This partial generated result must not replace
  the published package catalog. Its working copy is preserved unchanged.

The source publication does not revoke historical provider credentials or remove existing Git
history. The accepted client-only protection model and its runtime/history limitations remain as
documented in the credential-hardening release notes.

## Remaining release gates and rollback

- Clinical validation of new evidence/prompt behavior remains required before clinical rollout.
- Installer generation, clean-machine installation, upgrade/uninstall/rollback QA, and the
  repository-level release/build issues are separate from this source-publication gate.
- Do not rename or reuse an older installer as 3.6.4. Do not resume stale Nuitka checkpoints as
  evidence that the new source was compiled.
- For a source rollback, revert this publication commit with a new reviewed commit; do not reset
  or force-push shared branches. Preserve local settings, clinical data, and generated artifacts.
- For evidence-mode rollback, use `AIPACS_EAGLE_EYE_EVIDENCE_MODE=layout` and restart through the
  normal human-controlled source workflow. This disables experimental evidence preparation, not
  every prompt change in this batch.
