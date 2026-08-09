# 3 · Region gating

**Scope:** what a gate is, what selects it, how several are selected at once, and what
each one contributes to the prompt.

---

## 3.1 The pipeline

```
      Metadata                 effective = deep_merge(auto, user)
          │                    case.regions is the field that matters
          ▼
   Gate selection              modules_for(regions) → de-duplicated by title
          │
          ▼
Selected region context(s)     one package each: headings · pathology · normal ·
          │                    terms · notes
          ▼
   Prompt assembly             shared slots + STUDY_CONTEXT + REPORTING_CONTEXT
          │
          ▼
         LLM
```

---

## 3.2 What a gate is

A **region gate** is a canonical region key plus the package of reporting knowledge that
belongs to it. Selecting the gate inserts the package into the prompt; not selecting it
means the model never sees that knowledge.

The canonical keys are `session_metadata.REGION_KEYS` — the *same* vocabulary the metadata
card shows the physician. That is not a coincidence and must not drift: what the gate acts
on has to be exactly what he was shown and could have corrected.

```python
REGION_MODULES["chest"] = {
    "title":     "Chest",
    "headings":  "Lungs · Pleura · Mediastinum and hila · Heart and great vessels · …",
    "pathology": ["Pulmonary nodule - preserve size (longest dimension, mm), lobe …", …],
    "normal":    ["Lung parenchyma: clear lung fields bilaterally; …", …],
    "terms":     ["برونشکتازی → bronchiectasis", …],
    "notes":     ["Report the visualised upper abdominal organs only if …"],
}
```

| Section | What belongs | What does not |
|---|---|---|
| `headings` | the organ order for this region, one line | prose, rationale |
| `pathology` | descriptors worth preserving here, and the classification systems that apply here | anything phrased as an instruction to *produce* a measurement |
| `normal` | the normal-findings reference, one line per structure, with real thresholds | verdicts ("the liver is normal") |
| `terms` | dictation terms for this region, plus the always-on ones | terms belonging to another region |
| `notes` | region-specific traps that have actually caused a mistake | restatements of the anatomy above |

**Each gate supplies both halves of the report.** That is the point — gating only the
normal half left a knee CT receiving 15 measurement bullets written for brain, chest,
abdomen and spine, of which none applied.

---

## 3.3 Why it exists

Measured on the CT branch of the shared prompt:

| | tok | share |
|---|---|---|
| whole CT prompt | 12,184 | 100% |
| `RSNA normal findings per CT body region` (19 blocks) | 4,823 | 39% |
| `CT-SPECIFIC MEASUREMENT RULES` (15 bullets) | 619 | 5% |
| `GROUPING VOCABULARY` | 445 | 4% |
| `STANDARDIZED SYSTEMS` | 176 | 1% |
| **total region-specific** | **~6,000** | **~49%** |

Half the prompt is region-specific content sent to every CT study regardless of region.
For a chest/abdomen study, 15 of the 19 region blocks are irrelevant: the model is told
how to report a normal coronary CTA, a normal paranasal sinus CT, a normal lumbar spine
and a normal wrist.

The cost is not only tokens. Irrelevant content flattens salience and, in the case of the
classification systems, actively invites a wrong category.

---

## 3.4 What selects the gate

The gate reads **only** `effective` metadata, through `_build_gate_profile()`
(ai_chat_pages.py:5702):

```python
rec     = session_metadata.load(sid)          # effective = deep_merge(auto, user)
case    = rec["case"]
regions = case["regions"]                     # ← the selection
profile = {
    "regions":   regions,
    "contrast":  case.get("contrast"),
    "procedure": case.get("procedure"),
    "subtype":   case.get("subtype"),
    "patient":   "<id · sex · age>",
    "service":   rec["reception"]["service"],
    "protocol":  studies[0]["study_description"],
}
```

It returns `None` — meaning "send everything, today's behaviour" — in three cases: no
chat, no record, no regions.

`case.regions` itself is produced by `build_auto_from_context()` from DICOM evidence, and
may have been overwritten by the physician on the card. See doc 4 for how each field is
derived and doc 4 §4.6 for the fields that are **not** yet feeding detection.

### Inputs, and their weight in the design

| Input | Where from | Status |
|---|---|---|
| DICOM `BodyPartExamined` | series rows + file header | **implemented** |
| DICOM `StudyDescription` | study row + file header | **implemented** |
| DICOM `ProtocolName` | file header | **implemented** |
| Series descriptions | series rows | **implemented**, capped at one vote per field per region |
| Modality | the physician's menu choice, or DICOM | **implemented** |
| Reception service text | cached booking | **designed, NOT implemented** — see doc 4 §4.6 |
| Transcript | the dictation | **not implemented** |

**One vote per field per region.** Before that cap, `series_desc` (weight 0.8 × 12 series)
buried `body_part_examined` (weight 4.0) and produced actively wrong regions. Capping took
the wrong-region count from 6 to 0 on the sample corpus.

---

## 3.5 Multiple regions, and additive selection

`modules_for(regions)` returns a list, in gate order, de-duplicated **by title**:

```python
modules_for(["chest", "abdomen"])       → [Chest, Abdomen]          two blocks
modules_for(["pelvis", "prostate"])     → [Pelvis]                  one block, two keys
modules_for(["head_neck", "thyroid"])   → [Neck]                    one block
modules_for(["chest", "not_a_region"])  → [Chest]                   unknown keys ignored
modules_for(["not_a_region"])           → []                        → template declines
```

Three properties matter and are individually tested:

1. **Additive, not exclusive.** Selecting chest does not exclude abdomen. Multi-region
   studies are normal, and a combined protocol (chest + abdomen + pelvis in one
   acquisition) selects all three.
2. **Not a restriction.** `PRECEDENCE` states this explicitly to the model: *"REPORTING
   CONTEXT — guidance on coverage and vocabulary, not a limit on what you may report."*
   Followed by: *"If the transcript describes anatomy outside it, report that finding
   normally and place it correctly."* A mis-gate is recoverable, because the transcript
   outranks the gate.
3. **Degrades to the previous behaviour, never to less.** If no region has a module the
   template declines and the narrowed — or ungated — prompt is used. Rendering an empty
   `REPORTING CONTEXT` would be worse than sending everything.

---

### Three canonical keys have no module

`REGION_KEYS` has 24 entries; `REGION_MODULES` has 21. The three without a package are
**`breast`**, **`scrotum`** and **`obstetric`** - none of them CT regions. Breast belongs
to mammography, scrotum and obstetric to ultrasound, and neither modality has a module
library yet.

This is not a defect, but it is a trap: a study detected as `breast` today produces a
non-empty `case.regions`, an empty `modules_for()` result, and therefore a full
ungated prompt. The behaviour is correct; the silence is what to watch. When you add
a modality library (doc 6 §6.3), these three are the first keys to fill.

## 3.6 Modality and study subtype

**Modality** selects the module library, through `turbo_modules`:

```python
turbo_modules.modules_for(modality, regions)   # the only lookup
turbo_modules.supported_modalities()           # CT, MRI, RADIOLOGY, SONOGRAPHY
turbo_modules.subtypes_for(modality, subtypes) # the SECOND axis
```

CT has 21 packages, MRI 19, radiography 19. Ultrasound and mammography have none,
so `modules_for` returns `[]` and the prompt builder sends the full shared prompt.

**A package's shape can differ by modality.** Radiography packages carry a sixth
section, `projection`, rendered before everything else because it constrains what
the report may claim: a radiograph acquires one view, and a view cannot assess
what it does not show. CT and MRI packages have no such key and render nothing.

The two paths differ by modality and that is deliberate. **Narrowing is CT-only** —
the three spans it rewrites were extracted from the CT branch and the drift
self-check is against that extraction, so applying it to MRI would cut blind. MRI
reaches the gate through the template path alone, which means that with
`AIPACS_TURBO_PROMPT_V2` off an MRI report is byte-identical to what it was before
the library existed.

**Subtype** is a separate axis from region, and conflating them was a real error caught in
design. `CORONARY CTA` was initially mapped under `chest`, which would have put ~310
tokens of coronary rules into every chest CT. Coronary CTA is a *subtype* of a chest study,
not a region.

```
region   WHERE the study looked            chest, abdomen, brain, knee …
subtype  WHAT KIND of study it is          coronary CTA, CT urography, first-trimester
                                           obstetric, NT, anomaly scan, growth/IUGR
axis     other dimensions                  contrast state, procedure
```

**Subtype is a real, wired axis since ultrasound.** `subtypes_for(modality, subtypes)`
returns study-type packages that render as a `# STUDY TYPE` block after the region
context. Two libraries exist. **Ultrasound** has nine, covering dating, ectopic search, NT,
the anomaly scan, growth, Doppler, biophysical profile, placenta accreta and multiple
pregnancy — all sharing region `obstetric` and almost no content. **Radiography** has
eighteen and needs the axis most: a hysterosalpingogram, a barium enema and a colon
transit study are all abdominopelvic and share nothing else; a bone age, a skeletal
survey and a standing alignment film are all skeletal and share nothing else.

A study with no subtype renders no block at all, and the libraries cannot see each
other's keys — `subtypes_for("CT", ["ob_nt"])` is empty, and so is
`subtypes_for("SONOGRAPHY", ["xr_bone_age"])`.

`case.procedure` is carried in the gate profile and is available
to the assembly step; the CT subtype blocks live in `turbo_regions.AXIS_BLOCKS`. Ultrasound
in particular will need subtyping before it can be gated usefully — a first-trimester scan,
an NT scan, an anomaly scan and a growth scan share a region and share very little else.

---

## 3.7 Different imaging centres

The region **library** is universal; the **activation** is per deployment. A centre that
only does ultrasound should not carry 21 CT packages, and a centre with a different service
catalogue will map its bookings to regions differently.

This distinction was learned the hard way: an earlier design sized 38 gates from this
centre's service corpus and presented it as a taxonomy. It silently dropped 93 fluoroscopy
codes that this centre does not book. The library must be complete; what a deployment
activates is a separate, smaller decision.

---

## 3.8 What the gate guarantees

Enforced by `tests/code/echomind/test_turbo_template.py`:

- every module key is a canonical `REGION_KEYS` member
- every module has all five sections populated, ≥8 normal lines
- shared titles emit one module, not two
- a multi-region study renders one block per region, in gate order
- no dictation term is emitted twice
- the assembled prompt contains **exactly one** region content layer
- no region sees another region's classification system (32 systems in the matrix)
- every pathology line is in preserve-register, not produce-register
- a contested clinical threshold is never encoded as a bare number
- every one of the 21 regions renders a complete prompt in a sane size range
