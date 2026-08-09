# 5 · Mobile parity contract — Android and iOS

**Scope:** what an Android or iOS EchoMind must reproduce exactly, what it may implement
differently, and where the canonical definitions live.

**Related:** `docs/plans/echomind/ANDROID_ECHOMIND_SYNC_SPEC_2026-07-01.md` (transport and
sync). This document covers prompts, gating and metadata.

---

## 5.1 The rule

> A report generated on Android from the same study and the same transcript must be
> generated from a **byte-identical system prompt** to the one Windows would have sent.

Anything that changes the prompt is a parity surface. Anything that does not — UI, audio
capture, storage engine — is free.

---

## 5.2 What must be identical

| # | Thing | Canonical location | Why |
|---|---|---|---|
| 1 | The nine slot names and their order | `turbo_template.py` | order is load-bearing (role first, output last) |
| 2 | The text of the six shared slots | `turbo_template.py` | every rule encodes an observed failure |
| 3 | The canonical region keys | `session_metadata.REGION_KEYS` | a non-canonical key silently selects no module |
| 4 | All 71 region packages across five modalities | `turbo_*_modules.py` | this is the clinical content |
| 4b | The 32 study-type packages | same files | the second gate axis (§5.4b) |
| 4c | Mammography is a PREFIX, never a template render | `build_mammography_prefix` | its schema is regex-locked |
| 5 | Region-major rendering, gate order, section labels | `render_region_context()` | |
| 6 | Term de-duplication, first-wins across regions | same | |
| 7 | Title-based module de-duplication | `modules_for()` | `pelvis`+`prostate` → one block |
| 8 | The three-layer metadata model and merge semantics | `session_metadata.py` | |
| 9 | The JSON output contract and validator behaviour | `_validate_report_json` | |
| 10 | The Persian normal-template triggers, verbatim | `RULES_NORMAL` | `دگنش` is a real STT corruption; spelling matters |
| 11 | The precedence ladder | `PRECEDENCE` | resolves mis-gates |
| 12 | Fallback semantics: builder returns null → shared prompt | `build_turbo_system_prompt` | |

## 5.3 What may differ

- Storage engine (Room / Core Data / SQLite) — the **shape** must match, the engine need not
- UI layout of the metadata card — but it must be the first item in the conversation, and
  every field it shows must be editable
- Audio capture and the transcription endpoint
- Threading model for the reception prefetch
- Whether region content ships as a compiled resource or as source

---

## 5.3b The five libraries, and what each package carries

```
CT           21 regions                         headings pathology normal terms notes
MRI          19 regions                         headings pathology normal terms notes
RADIOLOGY    19 regions + 18 study types        + projection
SONOGRAPHY   12 regions +  9 study types        + technique
MAMMOGRAPHY   1 prefix   +  5 study types       prefix only — no template render
```

**A package's shape differs by modality and that is deliberate.** Radiography carries
`projection` because a view cannot assess what it does not show; ultrasound carries
`technique` because "not visualised" is not "normal". Reproduce both, and reproduce
that CT and MRI carry neither — the CT prompt must not grow a projection block.

## 5.4 Porting the region library

The Windows library is Python because of a packaging constraint: `AIPacs.spec` needs an
explicit `datas.append(...)` for every non-`.py` file, so a region package stored as `.md`
or `.json` ships as a missing file. That constraint does not exist on mobile.

**Recommended:** generate the mobile library from the Windows one rather than hand-porting
it. `turbo_region_modules.py` is already machine-generated from `tools/dev/gen_turbo_modules.py`;
add an emitter that writes JSON, and check the JSON into the mobile repos.

```
tools/dev/gen_turbo_modules.py
        ├── turbo_region_modules.py     (Windows, existing)
        └── turbo_region_modules.json   (mobile, to add)
```

Hand-porting 21 packages × 5 sections guarantees drift. If you must, add a checksum test on
both sides over the canonicalised JSON.

### The JSON shape

```json
{
  "schema": 1,
  "modality": "CT",
  "modules": {
    "chest": {
      "title": "Chest",
      "headings": "Lungs · Pleura · Mediastinum and hila · …",
      "pathology": ["Pulmonary nodule - preserve size (longest dimension, mm), …"],
      "normal":    ["Lung parenchyma: clear lung fields bilaterally; …"],
      "terms":     ["برونشکتازی → bronchiectasis"],
      "notes":     ["Report the visualised upper abdominal organs only if …"]
    }
  }
}
```

Encode as UTF-8 without BOM. The Persian terms and the `·` separator are content, not
decoration — a lossy encoding pass breaks the lexicon.

---

## 5.4b The second axis: study types

`subtypes_for(modality, subtypes)` selects study-type packages by `case.subtype` and
renders them as a `# STUDY TYPE` block AFTER the region context, because a subtype
narrows within a region rather than replacing it. A study with no subtype renders
nothing at all — never a bare heading.

Region is WHERE the study looked; subtype is WHAT KIND of study it is. Obstetric
ultrasound forced it: a dating scan, an NT scan, an anomaly scan, a growth scan and a
biophysical profile all have region `obstetric` and share almost no content.
Radiography needs it most — a hysterosalpingogram, a barium enema and a colon transit
study are all abdominopelvic and share nothing else.

The libraries must not see each other's keys: `subtypes_for("CT", ["ob_nt"])` is
empty, and so is `subtypes_for("SONOGRAPHY", ["xr_bone_age"])`.

## 5.5 Metadata on mobile

Reproduce the record shape and the merge semantics exactly.

```
ai_session_meta(sid PK, auto_json, user_json, updated_at, schema_ver)
```

Two JSON columns. Not one merged column, not normalised columns.

**Room (Android)**

```kotlin
@Entity(tableName = "ai_session_meta")
data class SessionMeta(
    @PrimaryKey val sid: String,
    val autoJson: String,
    val userJson: String,
    val updatedAt: String,
    val schemaVer: Int,
)
```

**Core Data / SQLite (iOS)** — same four columns. `sid` is the primary key and matches the
`ai_sessions.sid` used by the chat store.

### The merge

`effective = deepMerge(auto, user)`, where dictionaries merge key-by-key and **lists are
replaced wholesale**. Reproduce the list behaviour exactly — code that merges lists will
diverge on `case.regions` the first time a physician edits it.

The same consequence applies: **never write a user path containing a numeric segment.**

### Detection

`buildAutoFromContext` needs the same inputs and the same weighting:

- read the six DICOM tags from the file, not only from your local index
- skip `DOC · SR · PR · KO · SEG · RTSTRUCT · PDF` when picking a representative instance
- **one vote per field per region**
- map raw strings to canonical keys before storing
- attach provenance to every field that lands

If your local index is more complete than the Windows SQLite projection, you may skip the
file read — but the *result* must still be a canonical key and a provenance entry.

---

## 5.6 Assembly on mobile

```
1.  load(sid) → effective
2.  regions = effective.case.regions
3.  if regions is empty            → send the shared modality prompt, stop
4.  modules = modulesFor(regions)  → de-duplicated by title, gate order preserved
5.  if modules is empty            → send the shared modality prompt, stop
6.  facts   = studyContextFacts(effective)     — omit empty values entirely
7.  subs    = subtypesFor(modality, effective.case.subtype)   — may be empty
8.  prompt  = ROLE + PRECEDENCE + TWO_HALVES
            + RULES_PATHOLOGICAL + RULES_NORMAL
            + modalityNote(modality)
            + renderStudyContext(facts)
            + renderRegionContext(modules, studyNotes)
            + renderSubtypeContext(subs)      — nothing when empty
            + OUTPUT
9.  send    system=prompt, user=transcript

MAMMOGRAPHY DIVERGES AT STEP 1: build the breast prefix and prepend it to the shared
mammography prompt. Never render the template — the schema is regex-locked and the
template's OUTPUT slot would emit the wrong shape.
```

Steps 3 and 5 are the fallback contract. **Never render an empty `REPORTING CONTEXT`** —
sending the full prompt is strictly better than sending a prompt with a heading and
nothing under it.

`renderStudyContext` must omit a fact whose value is empty rather than printing a blank
row, and must print provenance in parentheses when it is known.

---

## 5.7 The parity test

Add this on both platforms. It is the only thing that will actually catch drift.

```
GIVEN   a fixture set of (modality, regions[], studyFacts) tuples — one per region,
        plus the multi-region and shared-title cases
WHEN    the platform assembles the system prompt
THEN    it equals the checked-in expected prompt for that tuple, byte for byte
```

Generate the expected prompts once from Windows and check them into all three repos. When
a shared slot changes, all three fixture sets change in the same commit — which is the
point.

Minimum fixture set:

| Case | Why |
|---|---|
| each of the 21 regions alone | catches a mis-ported package |
| `["chest", "abdomen"]` | multi-region, merge order, term de-dup |
| `["pelvis", "prostate"]` | title de-duplication |
| `["chest", "not_a_region"]` | unknown key ignored, not fatal |
| `["not_a_region"]` | falls back rather than rendering empty |
| no regions at all | falls back |
| a study with no contrast and no service | `STUDY_CONTEXT` omits rather than blanks |
| each study type, one per library | the second axis renders in the right place |
| a region with no subtype | no `# STUDY TYPE` block at all |
| a mammogram | prefix + shared prompt, byte-identical base |

---

## 5.8 Things that will bite

- **Unicode normalisation.** Do not NFC/NFKC-normalise the Persian triggers or the lexicon
  on the way into the prompt. `دگنش` is a corruption the prompt matches literally.
- **Line endings.** The Windows repo is CRLF; the prompt strings themselves use `\n`. A
  platform that emits `\r\n` inside the prompt will not match the parity fixtures.
- **The `·` separator** (U+00B7) is used in headings and term lists. Not a hyphen, not a
  bullet.
- **Whitespace.** The template's slots are deliberately unindented; a language whose
  multi-line string literals preserve leading indentation will inflate the prompt and fail
  the whitespace budget test. Dedent explicitly.
- **Turbo pinning.** If mobile has a backend switch, it must not reroute the Turbo
  equivalent. That was a real scoping leak on Windows.
- **Fallback must be to *more*, never to less.** Every degraded path sends the full shared
  prompt. A mobile client that sends a truncated prompt on failure is worse than one that
  has no gating at all.
