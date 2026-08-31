# Eagle Eye lumbar benchmark

Measures the lumbar pipeline against a radiologist reference read, **as a rate
over N runs**.

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

`--evidence-mode` sets `AIPACS_EAGLE_EYE_EVIDENCE_MODE`, which is how the same
captures get compared across evidence paths. The comparison that matters right
now is `focused-v2` against `focused-v3`: identical slice selection, different
pixel budgets. On the 2026-08-30 case v3 puts both focus planes at native DICOM
sampling:

| tile | focused-v2 | focused-v3 |
|---|---|---|
| focus axial | 0.781 mm/px | **0.313** (native) |
| focus sagittal | 0.844 | **0.391** (native) |
| axial overview | 0.781 | 0.407 |
| sagittal overview | 1.172 | 0.521 |

Every mm/px above is read out of `evidence_manifest.json`, not estimated - v3
records the crop box and the effective sampling for every tile it renders.

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
