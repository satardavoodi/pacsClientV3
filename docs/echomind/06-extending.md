# 6 · Extending the system

**Scope:** how to add a modality, a region, a subtype, a lexicon, a pathology rule or a
normal-findings structure — each without touching anything unrelated.

---

## 6.1 The two content sources, and why they are separate files

```
tools/dev/gen_turbo_modules.py       NOTES, PATHOLOGY
        content a radiologist wrote for THIS project, extracted from the prompts
        that were already in production

tools/dev/turbo_region_authored.py   PATHOLOGY_RESEARCHED, NORMAL_EXTRA
        content compiled from the published literature
        ⚠️ CLINICAL REVIEW REQUIRED — not yet read by a radiologist
```

The split is structural on purpose: provenance should be visible in the file layout, not
in a comment. The generator **raises** rather than letting researched content overwrite
authored content for the same region:

```python
if PATHOLOGY.get(_r):
    raise SystemExit("researched content would overwrite authored: %s" % _r)
```

**Review status.** These ten regions have literature-sourced content that no radiologist
has read: `shoulder`, `hip`, `knee`, `ankle_foot`, `wrist_hand`, `extremity`,
`paranasal_sinuses`, `temporal_bone`, `orbit`, `dental_maxillofacial`. Also unreviewed:
the three authored CT blocks in `turbo_regions_extra.py` (temporal bone, orbit,
maxillofacial) and the compressed `normal` sections across all 21 modules, which the
generator re-shaped from lines a radiologist wrote but did not check.

---

## 6.2 Add a region

1. **Add the canonical key** to `session_metadata.REGION_KEYS`. A key that is not there
   will be dropped by `normalize_region()` and silently select nothing.
2. **Add the DICOM evidence** to `_DICOM_REGION_MAP` — the `BodyPartExamined`,
   `StudyDescription` and `ProtocolName` strings that should vote for it.
3. **Add the package.** Either extend the source the generator reads, or add an entry to
   `PATHOLOGY_RESEARCHED` / `NORMAL_EXTRA` in `turbo_region_authored.py`.
4. **Add the title** to `TITLES` in the generator. Two keys may share a title — that is how
   `pelvis` and `prostate` emit one block.
5. **Regenerate:** `.venv\Scripts\python.exe tools\dev\gen_turbo_modules.py`
6. **Extend the ownership matrix** in `test_turbo_template.py::SYSTEM_OWNERS` for any
   classification system the new region introduces.
7. **Sync mirrors:** `.venv\Scripts\python.exe tools\dev\sync_plugin_mirrors.py`
8. **Gate.**

Nothing else changes. No shared slot, no other region's package, no assembly code.

## 6.3 Add a modality

CT and MRI have libraries. MRI was added on 2026-08-09 and is the worked example:
the normal-findings blocks, the grouping vocabulary and the sequence lexicon were
already in the shared MRI prompt and were extracted; only the pathology half had to
be written. To add the next one:

1. Add a `MODALITY_NOTES` entry in `turbo_template.py` — one short note on how findings are
   described in that modality. Region content does **not** go here.
2. Build the module library. The CT library was extracted from the existing shared prompt
   by `tools/dev/regen_turbo_regions.py`; the same approach works for MRI, whose region
   blocks sit inside a span mislabelled `PATHOLOGICAL FINDINGS RULES`.
3. Key the library by `(modality, region)`. Today `REGION_MODULES` is implicitly CT-only;
   a second modality is the moment to make that explicit.
4. Extend `_render_template` / `_select_ct_blocks` to dispatch on modality instead of
   assuming CT.
5. Regenerate, extend the matrix, sync, gate.

**Known next targets, by corpus share:** MRI lumbar spine (21.5%), cervical spine, knee,
ankle/foot, shoulder, breast. Ultrasound needs subtyping first (§6.4).

## 6.4 Add a study subtype

A subtype is **not** a region. It is what kind of study it is, within a region.

```
region   chest                 subtype   coronary CTA
region   pelvis                subtype   first-trimester obstetric · NT · anomaly · growth/IUGR
region   abdomen               subtype   CT urography
```

Conflating them was a real error: `CORONARY CTA` mapped under `chest` would have put ~310
tokens of coronary rules into every chest CT.

1. Add the subtype block to `turbo_regions.AXIS_BLOCKS` (CT) or the modality equivalent.
2. Derive `case.subtype` in `build_auto_from_context` from the service booking or protocol.
3. Have assembly append the subtype block after the region blocks.
4. Test that a plain study of the same region does **not** receive it.

## 6.5 Add a regional lexicon

Terms live in each module's `terms`, produced by `terms_for(region)` from
`turbo_regions.LEX_ITEMS`, `LEX_ALWAYS` and `LEX_REGION_MAP`.

- a term that belongs everywhere → `LEX_ALWAYS`
- a term that belongs to one region → `LEX_REGION_MAP`

Format is `<Persian or Finglish> → <English>`. Terms de-duplicate first-wins across
regions at render time, so an always-on term reaches the model once regardless of how many
regions are gated in.

This is the highest-value-per-token content in the whole prompt. No model infers
`دگنش → دیگه‌اش`.

## 6.6 Add a pathology rule

Add a line to the region's `pathology` list. Two hard constraints, both enforced by tests.

**Preserve-register, not produce-register.** The source bullets this replaced were
imperatives to *produce*:

> ✗ `Brain haemorrhage: specify type (EDH/SDH/SAH/IPH), location, volume (ABC/2 method or mL), density (HU), mass effect, midline shift in mm.`

The physician dictates. He cannot dictate an ABC/2 volume he did not measure, and source
fidelity forbids the model inventing one. So the rule can only safely mean:

> ✓ `Intracranial haemorrhage - preserve the type he named (EDH, SDH, SAH, IPH), the location, and any volume, attenuation, mass effect or midline shift he gave.`

`test_pathology_rules_preserve_rather_than_produce` rejects any line opening with
`specify` / `calculate` / `measure` / `estimate` / `compute` / `assign a`, and requires a
preservation clause in every line.

**Never encode a contested threshold as a bare number.** Where published normal ranges
disagree, name the measurement, ask for his value and its plane or method, and leave the
interpretation to him.

| Measurement | Published values in current use |
|---|---|
| Gissane angle | 130–145° · 100–130° · 120–145° |
| Insall-Salvati | patella alta at >1.3 · >1.5 |
| Tibiofibular clear space | <6 mm radiographic · ~2.0–2.4 mm on axial CT |
| Vestibular aqueduct | >1.5 mm · ≥1.0 mm midpoint · 0.8 mm in the oblique plane |
| Extraocular muscle | medial rectus 3.3–5.0 mm · 3.1 ± 0.5 mm |
| Alpha angle (hip) | 50.5° · 55° · 57° |
| Lateral centre-edge | normal >25° · >20° |

`test_a_contested_threshold_is_never_encoded_as_a_bare_number` requires the caveat to
travel with the measurement.

**If a system is region-specific, it goes here, not in the shared rules.** Add it to
`SYSTEM_OWNERS` in the test at the same time.

## 6.7 Add a normal-findings structure

Add lines to the region's `normal` (or `NORMAL_EXTRA` for a researched region).

- **feature-register, not verdict-register.** `"The liver is normal."` tells the referring
  clinician nothing. `"Liver is normal in size, contour and attenuation, enhancing
  homogeneously, with no focal lesion and no intrahepatic biliary ductal dilatation."`
  says what was assessed.
- one line per organ or tightly-related pair
- real thresholds where an undisputed one exists; nothing where sources disagree
- minimum 8 lines per region, enforced
- **do not add a contrast-dependent line** unless you also implement the contrast filter
  (doc 2 §2.8) — four regions already carry this defect

---

## 6.8 Working rules for this subsystem

**Region content is Python, never a data file.** `AIPacs.spec` needs an explicit
`datas.append(...)` for every non-`.py` file. A region package stored as `.md` or `.json`
ships as a missing file and the app degrades silently.

**Generated files are generated.** `turbo_regions.py` and `turbo_region_modules.py` carry a
"do not hand-edit" banner. Both generators self-verify a round trip before writing. Edit
the source and re-run.

**Patch scripts use exact anchors and fail loudly.** The established pattern:

```python
def swap(text, old, new, label):
    n = text.count(old)
    if n != 1:
        FAIL.append("%s: anchor found %d times, expected 1" % (label, n))
        return text
    return text.replace(old, new, 1)
```

**Do not write a swap whose `new` contains its `old`.** An insert-before-anchor
swap leaves the anchor in place, so on a re-run the count is still 1, the `n == 1`
branch fires before any already-applied check, and the block is inserted twice.
That happened on 2026-08-09 and the radiography `projection` section rendered
twice before a render check caught it. Either include enough following context
that the anchor is consumed, or test for the new text first.

**Check the render, not just the tests.** The duplicate above passed every test
that existed at the time, because none of them counted occurrences. Look at the
assembled prompt after a change to the renderer.

No "already patched" guard that can produce a false positive; collect failures and abort
before writing anything.

**CRLF discipline.** The repo is CRLF. Read with universal newlines, detect the newline
from the raw bytes, and **validate before opening for write** — `open(p, "w")` truncates
the file before you get a chance to check.

```python
raw = io.open(p, encoding="utf-8", newline="").read()
nl  = "\r\n" if "\r\n" in raw else "\n"
if nl not in ("\r\n", "\n"):
    raise SystemExit("refusing to write")
io.open(p, "w", encoding="utf-8", newline=nl).write(text)
```

**The gate command:**

```
.venv\Scripts\python.exe -m pytest tests/code/echomind tests/code/reporting ^
    tests/code/database tests/code/startup tests/code/smoke tests/code/utils ^
    tests/code/identity -q --no-header
```

**Mirrors after every change** under `modules/EchoMind/`. A new file needs `--add` with the
explicit path.

**Console encoding.** The Windows console here is cp1256; printing Persian from a script
raises `UnicodeEncodeError`. Wrap stdout, or print escapes:

```python
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
```

---

## 6.9 Open work, in priority order

| # | Item | Blocked on |
|---|---|---|
| 1 | Radiologist review of the ten literature-sourced regions | you |
| 2 | Service text → region detection (doc 4 §4.6) | nothing |
| 3 | Contrast as a second gating axis (doc 2 §2.8) | nothing |
| 4 | **Evaluate v2 against 20–30 real transcripts.** It is now ON by default (owner decision), so this is no longer a gate before switching on — it is verification of something already live | a transcript set |
| 5 | Cardiac MRI — 6 service codes, no block in the shared prompt, nothing to extract | you |
| 6 | CTA territory subtypes — 7 tariff codes currently share one generic block | 4 |
| 7 | ~~Mammography~~ — done 2026-08-09, by prefix |  |
| 8 | X-ray regions | 4 |
| 9 | Move the worked example into the region packages | 4 |
| 9b | Ultrasound — needs subtyping first, then a library | 7 |
| 9c | Interventional and vascular fluoroscopy — 35 codes, a different report shape | you |
| 10 | Decide: does a sex stated in `STUDY_CONTEXT` license sex-specific normal organs? | you |
| 11 | Decide: does "the input" in the contrast rule include `STUDY_CONTEXT`? | you |

Items 10 and 11 are clinical policy, not engineering. Both rules were written when the
metadata channel did not exist; both now instruct the model to ignore facts the prompt
supplies.
