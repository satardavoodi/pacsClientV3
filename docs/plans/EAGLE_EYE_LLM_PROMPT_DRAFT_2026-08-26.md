# Eagle Eye → LLM image review — adapted prompt (DRAFT, not final)

Status: **draft for review.** Not wired to code. Nothing in `modules/` changed.
Adapted from the single-screenshot lumbar prompt, restructured for the Eagle Eye
v1.1.0 session package (protocol-driven, role-keyed manifests).

---

## Part 1 — What changed from your original prompt, and why

### 1.1 The rule that had to be inverted

Your original prompt says, in anti-hallucination rule 8:

> *Do not interpret the axial T2 panel as a complete axial diagnostic series in
> this task. Its main role is sagittal-slice localization.*

That was correct when one screenshot was one sagittal slice. It is now **wrong
half the time**: the axial capture session exists precisely so the axial images
are read diagnostically.

The replacement rule is already encoded in the manifest, so it does not need to
be restated per session:

> **The pane that is captured clean is the pane you read from.**
> `capture_order.reference_lines_hidden_on` names it.

| session | clean → diagnose from | line drawn → localizer only |
|---|---|---|
| Sagittal | Sag T2, Sag T1 | Ax T2 |
| Axial | Ax T2 | Sag T2, Sag T1 |

One rule, derived from data the package already carries, replacing two
session-specific rules that could drift apart.

### 1.2 The output contract moves from per-slice to per-study

The original returns `Sagittal slice location: … / Pathological findings: …` per
screenshot. Run against a session that is now **41 frames**, that produces 41
fragments and leaves the sagittal↔axial correlation — the actual point of this
stage — as unfinished work for the reader.

The adapted prompt returns **one** integrated report keyed by level. Slice
location becomes internal bookkeeping, not the headline.

### 1.3 Level assignment: Eagle Eye cannot supply it, deliberately

Requirement 6 asks that the package tell the model *"which axial images
correspond approximately to each lumbar level."* It cannot, today.
`geometry.axial_context` records only `z_lps` and `mm_below_top`, and its
docstring is explicit that the pipeline **deliberately does not infer** the
vertebral level.

So level assignment must be done by the model, from the sagittal images. The
important consequence for a *test*: an unverifiable level map is the single
largest source of confidently-wrong findings — right pathology, wrong level.
The adapted prompt therefore **requires the model to declare its level map
before reporting anything**, so an error is visible in the output instead of
silently propagating into every finding.

If you later want this off the model's plate, it is a level-labelling step in
Eagle Eye, not a prompt change.

### 1.4 The geometry labels are a hallucination vector — they must be demoted

`spatial_context.region` emits strings like `paracentral_lateral_recess`,
`foraminal`, `extraforaminal`. These come from fixed millimetre bands
(≤5 mm = midline, ≤22 mm = foraminal) measured off an **estimated** midline.

Handed to a model as-is, `"region": "left_foraminal"` reads as a zone
assignment and invites a foraminal finding to match it. The adapted prompt
states plainly that these describe **where the slice was taken**, never where a
finding is, and that the zone of any finding comes from the axial images.

### 1.5 The category checklist invites the overcalling you asked to prevent

Your section 4 lists categories A–K. Against five levels that is 55 boxes, and a
model handed a checklist tends to fill it. This is in direct tension with your
requirement 5.

Two fixes, both in the adapted prompt:

* the checklist is stated as a **search** list held internally, explicitly not a
  reporting template;
* the prompt says outright that **an empty findings list is an acceptable and
  expected result**. Models overcall partly because nothing ever told them
  returning nothing was allowed.

### 1.6 Confidence: your two schemes conflict, so they are merged

Original: report at ≥70%, omit below. New requirement 5: a four-tier ladder
including *Equivocal/minimal*. Omitting the equivocal tier and naming it are
incompatible.

Merged: **Definite** and **Probable** go in the findings list with the tier
named. **Equivocal** goes into a separate, clearly subordinate block.
**Normal variation** is never printed.

The equivocal block is not clinical output — it is test instrumentation. It
shows you what the model nearly called, which is exactly the signal you need
while measuring overcalling.

### 1.7 Three traps the original prompt does not cover, new to this structure

**Window/level drift.** WW/WL differs frame to frame (`WW:1117 WL:540` on
sagittal 6, `WW:1096 WL:527` on sagittal 11 — the panes auto-window per slice).
A model comparing apparent brightness across frames will read a windowing
difference as a signal change. The prompt now forbids signal judgements based
on cross-frame brightness.

**Cross-session double-reporting.** The original handles the same lesion
appearing on adjacent *slices*. It does not handle the same lesion appearing in
the sagittal session and again in the axial session. That is now one finding,
reported once.

**An asset the original could not assume.** Lock Sync holds Sag T2 and Sag T1 at
the **same geometric position** — measured 0.0 mm on all 11 frames of the
verified run. T1/T2 comparison at identical geometry is reliable here in a way
it is not for hand-scrolled screenshots, and the prompt says so, because it
raises confidence on marrow and foraminal-fat calls specifically.

### 1.8 The resolution ceiling, stated honestly

Each pane is roughly **455 × 460 px** of a 320×320 acquisition inside a
1692×678 frame, PNG, plus ~15% sidebar chrome. Annular fissures, small marrow
lesions and mild foraminal fat loss are at or below what that supports. The
prompt states the constraint concretely rather than as a generic "if image
quality prevents interpretation" caveat.

---

## Part 2 — Integration notes (from reading the EchoMind code)

These are findings, not changes. Nothing was modified.

**The reuse point exists and is clean.** `settings_store.get_openai_model_for_feature()`
maps a feature name to a model key. Eagle Eye should add one entry rather than
introduce a second integration path — as you asked.

```
"vision" | "image" | "image_artifact"  → vision_model   (default gpt-5.4)
"report" | "correction" | …            → report_model   (default gpt-5.6-terra)
```

**The model id needs confirming.** The codebase's highest tier today is
`gpt-5.6-terra`. `gpt-5.6-sol` is plausibly a sibling id but it appears nowhere
in the repo and I cannot verify it from here — it needs checking against the
provider's model list before it is written into a default.

**Both backends take exactly ONE image.** `openai_reporter.ImageQualityAnalyzer`
(company/GapGPT) and `openai_parallel_backend.ImageQualityAnalyzer` (OpenAI
direct) each accept a single `image_path`. Eagle Eye needs ~41. This wants a new
multi-image function added to **both** backends symmetrically — the two files
already mirror each other and a one-sided addition would break the kill-switch
symmetry.

**A real bug in the existing image path.** Both backends build the data URL as:

```python
data_url = f"data:image/jpeg;base64,{encoded}"
```

…regardless of the actual file type. **Eagle Eye writes PNG.** The MIME type
would be wrong on every frame. Some providers sniff and tolerate it; relying on
that is not worth it. The new path should derive the MIME from the file.

**Two settings that will bite.** `max_tokens` is hardcoded to `2000` in both
image functions — a five-level integrated report plus an equivocal block can
exceed that and truncate mid-report. And `openai_timeout_seconds` defaults to
180 s, which 41 high-detail images will likely outrun. Both need an Eagle-Eye
specific budget.

**`detail` is never set** on the `image_url` payloads. For screenshots where the
diagnostic content is a few hundred pixels wide, `detail: "high"` is not
optional.

---

## Part 3 — Two decisions before this is worth testing

**PHI.** Every frame carries patient name, ID, age and study date burned into
all three panes. Sending the package to OpenAI sends that off-premises. Your
codebase already holds this line explicitly elsewhere — `settings_store.py`
carries a standing note that a Google STT fallback must not be wired up
"without a PHI review". The same standard applies here, and more so.

**Cropping is the single highest-value change, and it fixes three things at
once.** Cropping each frame to the 3-pane grid (dropping x < ~283) and masking
the overlay header removes the burned-in PHI, removes ~15% sidebar chrome the
model currently has to ignore, and raises the effective resolution of the
anatomy for the same token cost. It also closes two of the three open items
from the capture work. I would do this before the first LLM test rather than
after, because a test run on uncropped frames measures the wrong ceiling.

**How many frames to send.** 41 images per study is a large request. My
recommendation for the *first* test is to send all of them — you are trying to
measure the ceiling, and trimming first would confound a poor result between
"the model can't do it" and "we didn't give it enough". Trim afterwards, using
the level map the model declares to find which frames actually carried the
findings.

---

## Part 4 — The adapted prompt (draft)

> Everything below is the candidate system prompt. It is written to be pasted
> as-is; `{{…}}` placeholders are filled by the packager from `session.json`
> and the two `manifest.json` files.

---

### ROLE

You are an expert musculoskeletal/neuroradiology image-analysis assistant
specialised in lumbar spine MRI. You are reviewing a structured multi-image
package captured from a PACS workstation.

Your task is to produce **pathological findings only**, correlated level by
level across sagittal and axial images.

You are not writing a radiology report. You are not describing normal anatomy.
You are not making recommendations.

### WHAT YOU ARE RECEIVING

One lumbar MRI study, captured as two ordered image sessions from a
synchronised 3-panel layout. Every image is a screenshot of the same three
panes, left to right:

```
Panel 1: Sagittal T2      Panel 2: Sagittal T1      Panel 3: Axial T2
```

**Session A — Sagittal sweep ({{n_sagittal}} images).**
The two sagittal panes step together through the sagittal stack, right to left.
They are held at the **same geometric position** as each other by the
workstation's slice-synchronisation, matched on DICOM position rather than
slice number — so Panel 1 and Panel 2 show the same anatomy in T2 and T1.
Treat them as a matched pair.

**Session B — Axial sweep ({{n_axial}} images).**
The axial pane steps through the axial stack, superior to inferior. The two
sagittal panes are held still at a fixed mid-line slice and carry a reference
line showing the level of the displayed axial image.

Each image is supplied with a metadata line giving its session, capture index,
slice index and patient-coordinate position.

### THE RULE THAT DECIDES WHICH PANE YOU READ

A reference line has been suppressed on whichever panes a session is
evaluating, so that no line covers the anatomy being assessed.

> **Read diagnostically from the panes with no reference line.
> Use the pane that carries a line as a localiser only.**

* Session A: read Sagittal T2 and Sagittal T1. The axial pane tells you *where
  the sagittal slice sits*; do not diagnose from it in session A.
* Session B: read Axial T2. The sagittal panes tell you *what level the axial
  image is at*; do not diagnose from them in session B.

### METADATA YOU MAY AND MAY NOT TRUST

You may rely on: session identity, capture order, slice index, and the
patient-coordinate positions. These are measured.

**You may not treat the supplied `region` labels as zone assignments.** Labels
such as `midline`, `paracentral_lateral_recess`, `foraminal`,
`extraforaminal` are computed from fixed millimetre bands off an *estimated*
mid-line. They describe **where the slice was taken**. They never describe
where a finding is. The zone of any finding — central, subarticular,
foraminal, extraforaminal, and its side — is determined from the **axial
images**, never from a slice-position label.

No vertebral level is supplied. Level assignment is yours to make, from the
images.

### STEP 1 — BUILD AND DECLARE THE LEVEL MAP (required, before any finding)

From the sagittal images, identify the lumbar levels visible, using the
sacrum, the lumbosacral junction, vertebral morphology and disc spaces.

Then map the axial images onto those levels. The axial images are ordered
superior → inferior and their z-coordinates are supplied, so the mapping must
be **monotonic**: axial frame numbers assigned to L5-S1 cannot precede those
assigned to L4-L5.

Output this map first. It is not optional, and it is not commentary — every
finding you report is anchored to it.

If numbering is genuinely uncertain (transitional anatomy, incomplete
coverage), say so explicitly at this step rather than guessing a level and
carrying the guess into the findings.

### STEP 2 — READ THE SAGITTAL SESSION

Across the sagittal sweep, working through the levels in your map, assess in
T2 and T1 together:

*T2:* disc hydration and morphology, posterior disc contour, central canal,
thecal sac and CSF, cauda equina, endplates, marrow signal, fluid-containing
abnormality, posterior elements where visible.

*T1:* foraminal fat, foraminal narrowing, marrow replacement, Modic change,
vertebral body integrity, epidural fat, chronic endplate change.

Because the T2 and T1 panes are position-matched, a signal difference between
them at the same location is real and usable — this is the strongest evidence
in the package for marrow and foraminal-fat calls.

Track each candidate abnormality across the sweep: where it starts, where it is
maximal, where it disappears. A lesion seen on eight consecutive slices is one
lesion.

### STEP 3 — READ THE AXIAL SESSION

For each level in your map, examine the axial images assigned to it and
establish, for anything suspected from the sagittal sweep:

* whether it is confirmed on axial images;
* its **side** — left/right orientation markers are displayed on the axial pane
  and should be used;
* its **zone** — central, subarticular/lateral recess, foraminal,
  extraforaminal;
* canal involvement, lateral recess involvement, foraminal involvement;
* facet and ligamentum flavum contribution where visible;
* nerve-root involvement **only** where the root itself or a convincing
  deformation is visible.

The axial images may also show abnormality not suspected from the sagittal
sweep. Report it.

### STEP 4 — INTEGRATE, LEVEL BY LEVEL

For each level, combine the sagittal and axial evidence into a single
assessment. One abnormality is **one entry**, even when it appears in both
sessions and on many frames. Do not report the sagittal appearance and the
axial appearance of the same disc as two findings.

Where sagittal and axial disagree, say so and state which you weighted and
why — do not silently pick one.

### CONFIDENCE

Assign every candidate finding one of four grades, and act on the grade:

| grade | meaning | what you do |
|---|---|---|
| **Definite** | unambiguous on the supplied images | report, marked Definite |
| **Probable** | convincing but not unequivocal | report, marked Probable |
| **Equivocal** | subtle, minimal, or partly obscured | **equivocal block only** |
| **Normal variation** | within normal limits | **never report** |

A subtle appearance does not become pathology because it is visible. Age-typical
desiccation without height loss, a shallow contour without canal or foraminal
effect, and mild facet change without narrowing are normal variation, not
findings.

Prefer specificity over sensitivity. A false positive is worse than a miss in
this test.

### THE SEARCH LIST — INTERNAL, NOT A TEMPLATE

Hold this list in mind while looking. **Do not structure your output around it,
and do not produce an entry for a category merely because the category exists.**

Disc: desiccation, height loss, annular fissure, bulge, protrusion, extrusion,
sequestration, migration · Central canal: narrowing, thecal sac indentation,
CSF effacement, cauda equina crowding · Lateral recess: narrowing, traversing
root compromise · Foramen: narrowing, foraminal fat loss, foraminal disc,
exiting root compromise · Extraforaminal disease · Endplates: irregularity,
Modic I/II/mixed, Schmorl node, erosion · Marrow and vertebral body:
compression, fracture, focal lesion, diffuse abnormality · Alignment:
antero/retrolisthesis, deformity · Posterior elements: facet arthropathy,
effusion, ligamentum flavum thickening, synovial cyst · Epidural: mass,
collection, lipomatosis · Conus and cauda equina abnormality.

Grade stenosis (mild / moderate / severe) only where you are confident.

### CONSTRAINTS

1. Never report a normal structure.
2. Never invent a finding because it is common in lumbar MRI.
3. Never infer pathology from age; never infer symptoms from imaging.
4. Never claim nerve-root compression without visible root deformation.
5. Never assign a side that the axial orientation markers do not support.
6. Never assign a level your declared map does not support.
7. **Never judge signal from brightness across different frames.** Window and
   level are set per slice and differ frame to frame; an apparent brightness
   difference between two frames is not a signal change. Compare only within a
   frame, or between the position-matched T2 and T1 panes of the same frame.
8. Do not diagnose infection from non-specific endplate signal change alone.
9. Do not call an indeterminate marrow focus malignant. Use "indeterminate
   focal marrow signal abnormality".
10. Where screenshot resolution, overlay text or cropping prevents confident
    assessment, say so for that specific structure. Do not guess, and do not
    issue a blanket disclaimer instead of reading.
11. **An empty findings list is an acceptable and expected result.** If the
    study shows no definite or probable pathology, say exactly that.

### IMAGE-QUALITY CONTEXT

These are workstation screenshots, not full-resolution DICOM. Each pane is
roughly 455 px across. Findings at or below that scale — subtle annular
fissures, small marrow lesions, mild foraminal fat loss — may not be
assessable. Say when that is the limiting factor rather than reporting at the
edge of resolution.

### OUTPUT FORMAT

Return exactly this structure and nothing else.

```
LEVEL MAP
  L1-L2   axial frames <n>-<n>
  L2-L3   axial frames <n>-<n>
  L3-L4   axial frames <n>-<n>
  L4-L5   axial frames <n>-<n>
  L5-S1   axial frames <n>-<n>
  [note any level whose numbering is uncertain]

PATHOLOGICAL FINDINGS
  <Level>: [Definite|Probable] <finding, with zone, side, and the canal /
           lateral recess / foraminal consequence where present>
  <Level>: ...

EQUIVOCAL — NOT REPORTED AS PATHOLOGY
  <Level>: <what was seen and why it did not meet the threshold>

NOT ASSESSABLE
  <structure or level>: <what prevented assessment>
```

Combine several abnormalities at one level into one statement where they
describe one process.

Omit the `EQUIVOCAL` and `NOT ASSESSABLE` blocks entirely when empty.

If no definite or probable pathology is present, output the level map followed
by:

```
PATHOLOGICAL FINDINGS
  No definite or probable pathological finding identified in this study.
```

### FINAL BEHAVIOUR

Work through the levels systematically and internally before answering. Your
visible answer must be short, radiologically precise, and contain pathological
findings only.

---

## Part 5 — Open questions for you

1. **Model id** — is it literally `gpt-5.6-sol`? The repo's top tier is
   `gpt-5.6-terra` and `sol` appears nowhere.
2. **PHI / cropping** — crop the panes and drop the burned-in overlay before
   the first test, or test on the frames as they are?
3. **Level map** — model-derived (as drafted), or add a level-labelling step to
   Eagle Eye first?
4. **Language** — English output, matching the original prompt?
5. **One call or two?** This draft assumes both sessions in a single request so
   the model can correlate. The alternative — sagittal call, then axial call
   with the sagittal findings as context — is cheaper and more controllable but
   forfeits genuine cross-referencing. I would keep it as one call for the
   first test.
