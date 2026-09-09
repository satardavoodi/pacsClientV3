# Eagle Eye lumbar benchmark

Measures the lumbar pipeline against a radiologist reference read, **as a rate
over N runs**.

The application runtime has one canonical evidence mode:
`focused-v4-correlated`. Retired layout/V1/V2/V3 profiles are not ordinary app
configuration. This benchmark may enable one explicitly inside its own process
to reproduce a historical comparison; that exception does not change the app
default.

## Why rates

Repeated model runs can disagree about morphology. A single-run comparison
cannot separate a prompt or evidence change from that variability. Compare
multiple runs under a recorded configuration, inspect parsed claims, and keep
the radiologist reference independent of model-generated answers.

Every number this tool prints is a hit rate over N runs. There is deliberately
no single-run verdict.

## Layout

| Path | What it is |
|---|---|
| `reference.py` | Loads and validates a reference read |
| `scoring.py` | Parses a FINAL REPORT into structured findings and scores them |
| `bench.py` | CLI: `score` existing sessions, or `run` one session N times |
| `user_data/ai/eagle_eye/_bench/ground_truth/<case>.json` | The reference reads (gitignored) |
| `user_data/ai/eagle_eye/_bench/runs/<label>/` | Bench run output |

No file in this package contains patient data. Reference reads live outside the
repository and are addressed by an opaque case id.

## Writing a reference read

A reference is written **once, by a radiologist, from full-resolution DICOM** -
never from a pipeline output. Scoring a model against a reference derived from
its own earlier answer measures nothing.

`reference.py` refuses a read with no `recorded_by`, an unknown morphology, or
an endplate claim without `accept_levels` (a vertebral endplate borders two
disc levels, and the report names levels, not vertebrae).

Mark the findings that must never be missed with `"critical": true`. Those
drive the critical-miss rate, which is the number that matters clinically.

## Scoring

Each reference finding becomes a claim, scored `hit` / `partial` / `under` /
`over` / `wrong_side` / `miss`. Findings at a level the reference calls normal
are counted as false positives. Structures the reference does not comment on at
all can be listed under `soft_normal_structures` so they are reported without
dominating the score.

The parser is deliberately conservative: negations are honoured (`no focal
herniation` does not become a protrusion), side and zone are read from the disc
phrase rather than from a consequence later in the same sentence, and a
non-monotonic LEVEL MAP is flagged rather than silently scored - an inverted map
means every finding in that run sits at a level that cannot be trusted.

Parsing prose will never be perfect. Read the extracted structure before
believing a number; `--out` writes it per run.

## Use

Score what already exists on disk - costs nothing, calls no model:

```
python -m tools.eagle_eye_bench.bench score --case lumbar-001
python -m tools.eagle_eye_bench.bench score --case lumbar-001 --out scores.json
python -m tools.eagle_eye_bench.bench score --case lumbar-001 --session <session dir>
```

Re-run a captured session N times and score all N. This spends model budget -
N x 3 requests - and asks before it starts:

```
python -m tools.eagle_eye_bench.bench run --case lumbar-001 \
    --session "<...>/user_data/ai/eagle_eye/<study>/<session>" \
    --repeats 5 --label baseline-4.6.1 --evidence-mode focused-v2
```

`run` copies only the captures (`session.json`, `series_sources.local.json`,
`Sagittal/`, `Axial/`) into a fresh folder per repetition, so no previous
answer comes along and the source session is never modified.

`--evidence-mode` selects an evidence path for this benchmark process. When a
retired path is requested, the CLI also enables the engineering-only legacy
gate. The comparison that matters right now includes `focused-v4-correlated`
against the retained V3 baselines. V2 and
V3 use identical slice selection with different pixel budgets; V4 also changes
the screening-localization handoff. On the 2026-08-30 case v3 puts both focus planes at native DICOM
sampling:

| tile | focused-v2 | focused-v3 |
|---|---|---|
| focus axial | 0.781 mm/px | **0.313** (native) |
| focus sagittal | 0.844 | **0.391** (native) |
| axial overview | 0.781 | 0.407 |
| sagittal overview | 1.172 | 0.521 |

Every mm/px above is read out of `evidence_manifest.json`, not estimated - v3
records the crop box and the effective sampling for every tile it renders.

`focused-v4-correlated` is the canonical source and packaged-build default. It gives Gemini a
source-grounded DICOM atlas, validates returned tile boxes in patient geometry,
and centres diagnostic evidence on the resolved focus. The app ignores a stale
legacy `AIPACS_EAGLE_EYE_EVIDENCE_MODE` value unless
`AIPACS_EAGLE_EYE_ALLOW_LEGACY_EVIDENCE=1` is also set. Use that gate only for
controlled engineering rollback. Prefer this CLI for comparisons because it
scopes the exception to the benchmark process. V4 changes evidence and prompt
versions together, so it must not be interpreted as a prompt-only experiment.

Pipeline 5.4.0 changes V4 screening pixels without changing the diagnosis-free
screening prompt: sagittal T2/T1 use bounded `320 x 555` tiles with six slices
per page, while axial pages remain unchanged. `screening_manifest.json` schema
1.1.0 records effective sampling and a separate screening request budget. Do not
compare a 5.4.0 run with 5.3.0 as if only model randomness changed; record the
pipeline version and screening manifest with every cohort arm.

## Guards

`tests/code/ai_imaging/test_eagle_eye_bench_scoring.py` includes report-parser
guards and synthetic attribute-negation cases. Inspect parsed claims before
using the scores; a parser error can reverse the interpretation of a run.

## Scoped scorer repair and additive evidence trial (2026-08-31)

Scorer **1.1.0** retains contact when another root attribute is negated, for
example "Contact, but no deviation, of the right L4 root." This now scores
`under`, not `miss`, against a compression reference. Individual score JSON
records `scorer_version` and root `effect_assertions`. Existing reports and
references are not rewritten when rescored.

This is not the complete Phase 0 benchmark repair. Morphology-as-severity,
generic herniation parsing, coexisting bulge/herniation, coupled root identity
and effect scoring, failed-run denominators, and reference-negative adjudication
remain unresolved. Do not treat current aggregate rates as proof of improvement.

The CLI accepts `--evidence-mode focused-v3-parasagittal`. This opt-in condition
retains all baseline V3 images/captions, then appends bilateral sagittal T2
focus supplements within the original budget. It does not trust screening
laterality or assert the geometric reference is anatomical midline. Manifest
1.4.0 records source-volume slices, actual patient-space offsets, and any
excluded/partial supplement. Base V3 remains manifest 1.3.0.

Use a distinct experiment label; do not mix this condition with ordinary V3.
The existing `run` command still reruns the full pipeline and spends model
budget: it is not frozen-stage E1/E2 replay. No model run was made for the
implementation preflight. See the
[implementation and verification record](../../docs/plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#30-v3-bilateral-sagittal-experiment-and-scoped-root-scoring-2026-08-31).

## Current follow-up: scorer 1.2.0 and integrity guard (2026-08-31)

Scorer 1.2.0 recognizes root-effect participles (`contacting`, `abutting`,
`compressing`, `deviating`) and associates a consequence grade with its own
structure-local clause. A subarticular disc location alone is not recess
stenosis and cannot hide a later explicit grade. Lower-thoracic map rows are
retained. Synthetic parser coverage now comprises 35 tests.

`score` adds `level_assignment_audit` to each run: it compares the saved
screening map with the final map and reports uniform shifts separately from
strict named-level outcomes. Missing screening maps are `unavailable`, not
consistent. The audit does not remap levels or award corrected-level credit.
Inspect this diagnostic before interpreting a cluster of apparent misses.
All remaining Phase 0 limitations listed above still apply.

New lumbar three-stage analyses also persist this audit and flag conflicting
or unavailable level assignments as `review_required`. Their displayed/copied
report carries the warning without changing the raw model response. Consistent
maps are not anatomically verified. Old sessions are not rewritten by this change.

The opt-in parasagittal manifest is now 1.5.0: only surplus vertical padding
is compacted, preserving seven-plane selection and original sampling. Existing
V3 base images remain unchanged. Coverage exclusions are visible in the
verification header and final review warning. Image/pixel/byte caps are not
raised; eight images still fill the image budget. Compare saved 1.4.0 and new
1.5.0 as distinct rendering revisions, not interchangeable trials. No runtime
default or clinical system prompt changed. The current CLI is still a
full-pipeline rerun, not frozen-stage E1/E2.

See [section 31 verification and limits](../../docs/plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#31-level-assignment-integrity-padding-headroom-and-scorer-120-2026-08-31).

## Frozen saved inputs: offline preparation, not replay

`freeze` now copies the **saved** verification input into a new private folder.
It preserves the historical prompt/settings, upstream context, header, captions,
image order, and encoded image bytes. It does not substitute the current prompt,
rerun screening, re-render evidence, score a report, or contact GapGPT.

Windows CMD (replace the source path; choose a new output name on each freeze):

```cmd
.venv\Scripts\python.exe -m tools.eagle_eye_bench.bench freeze --session "<existing-session-folder>" --out "user_data\ai\eagle_eye\_bench\frozen\trial-01"
.venv\Scripts\python.exe -m tools.eagle_eye_bench.bench check-frozen --snapshot "user_data\ai\eagle_eye\_bench\frozen\trial-01"
```

Record the returned digest in the private experiment log; pass it back as
`--expected-id "<digest>"` for an independent identity check. Schema 1.0.0 hashes
`input.json` and each ordered `images/NNN.ext` asset in `manifest.json`; the
manifest maps positional assets to unchanged `sent.images` entries. No final
answer, benchmark reference, DICOM files, or `local_provenance` block is copied.
**This is not anonymization:** images, captions and upstream context can still
contain sensitive clinical data. Keep the output local and ignored by Git.

Existing destinations and outputs inside the source session are refused. Missing,
linked, escaping, empty, mismatched or modified artifacts fail closed. The
completion manifest is written last; failed writes may leave a private incomplete
folder, which must not be reused. Local limits are 64 images, 256 MiB aggregate
encoded images and 8 MiB per JSON document, not an expansion of runtime upload
budgets. Bytes are preserved without decoding or judging clinical adequacy.

The snapshot proves identity **from freeze time**, not that the files were
unchanged since the original request or that the provider received identical
decoded pixels. Hashes detect drift, not malicious replacement of an entire
snapshot plus its trusted digest. A freeze is not an E1/E2 experiment: the `run`
command still reruns all stages. Verification-only dispatch, clinician landmark
entry/validation and controlled comparison remain separate work.

Pipeline 4.7.0 uses grading catalog 2.0.0 (corrected Bartynski criteria) and
separate root-observation contract 1.0.0. Historical catalog 1.0.0 used different
recess criteria; do not pool its grades with new grades or rewrite saved reports.
See [section 32](../../docs/plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md#32-grading-correction-and-fixed-input-preparation-2026-08-31)
for the clinical gate and experiment sequence.

## Independent spatial packet utility (2026-09-08)

`spatial_packet.py` exposes `SlicePlane`, `build_manifest`, `intersection`, and
`render_locator` for controlled diagnosis-input experiments. Callers must verify
source identity, shared frame of reference and complete immutable memberships
before supplying planes. Origins/directions/spacing describe displayed pixels
after any crop, flip or resize. Do not reuse untransformed DICOM geometry.

The manifest sorts inside each group by physical normal, reports adjacent spacing
and retains acquisition boundaries. Locators show finite-field plane intersections
in both directions; originals remain separate. The utility performs no DICOM I/O,
inference or runtime integration. Keep clinical adapters, inputs and outputs in
the ignored private benchmark tree. Synthetic verification:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:debugging tests/code/ai_imaging/test_eagle_eye_spatial_packet.py --reruns 0 -q
```

See the [experiment report](../../docs/reports/EAGLE_EYE_SPATIAL_PACKET_EXPERIMENT_2026-09-08.md)
for the current protocol and limits; historical benchmark defaults above do not
describe this independent experiment.

### Paired correspondence cards

`render_correspondence_cards(reference, axial_planes, pixels, directory,
expected_members=...)` renders every member of one validated axial group in
physical order. Each output pairs a one-line mini-locator with clean pre-enlarged
sagittal slab context and matching axial pixels. The audit contains source crops,
canvas boxes, IDs and measured spacing. Existing cards are not overwritten.
Always dispatch all original members of the selected groups separately as well;
the auxiliary cards do not replace native diagnostic images. See the spatial
experiment report for layout-only validation and production boundaries.
