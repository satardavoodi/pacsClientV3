# Series-Identity Pipeline Unification — resolve ONCE, thread it, retire the guards

**Status:** PLAN (no code yet) · **Created:** 2026-07-14 · **Owner:** viewer / multi-study
**Directive it serves:** *"the pipeline should be straightforward for showing the series and
optimizing performance and speed"* + the standing rule
*"route decisions through the ONE authority, not bespoke checks + flags."*

Master plan: this is **OPT-35**. Extend §9/§15 there; do not start a competing plan.

---

## 1. Problem statement (evidenced, not theoretical)

To display one series the code independently re-answers the SAME question —
**"which study does this display key belong to, and where do its bytes and rows live?"** — at
four separate stages, each deriving the answer from **mutable tab state** that any other load can
overwrite.

Every multi-study patient with **colliding series numbers** finds a new stage where the
derivations disagree, and each time we added a guard:

| Patient | Stage that diverged | Wrong result | Patch added |
|---|---|---|---|
| 48912 / 29694 | disk path (plain key) | previous exam's series shown | `AIPACS_PRIMARY_SERIES_POISON_GUARD` |
| 49836 | disk path (tab repoint) | study B's series 3 loaded for study A | `AIPACS_TAB_PATH_PRIMARY_ONLY` |
| 50238 | **DB `study_pk`** | study B's series 3 rows read for study A | `AIPACS_PRIMARY_STUDY_PK_GUARD` |
| (48952, 48296, 48476, 48101 …) | cache key / grow-lane / disk-count | wrong or missing series | 5 more flags |

**Nine flags now answer one question:**

```
AIPACS_CACHE_STUDY_IDENTITY            AIPACS_PRIMARY_SERIES_POISON_GUARD
AIPACS_DM_CANON_IDENTITY               AIPACS_PRIMARY_STUDY_PK_GUARD
AIPACS_MULTISTUDY_PER_SERIES_STUDY_PK  AIPACS_STAMP_SERIES_STUDY_UID
AIPACS_VIEWER_DB_METADATA_MULTISTUDY   AIPACS_VIEWER_STABLE_IDENTITY
AIPACS_VIEWPORT_STUDY_IDENTITY_GATE
```

**The disease is not any one of these bugs. It is that identity is DERIVED four times instead of
DECIDED once.** Guard #10 is already predictable; we should stop writing them.

### 1.1 The mutable-state sources (the actual poison vectors)

| State | Refs | Why it poisons |
|---|---|---|
| `parent_widget.import_folder_path` | ~35 | The TAB's study folder — but *any* loaded series' `series_path` used to overwrite it (49836). |
| `parent_widget.metadata_fixed['study_pk']` | ~10 | The TAB's primary pk — but it is (re)populated from whichever series filled `metadata_fixed`, so a secondary load leaves the tab carrying the secondary pk (50238). |

Both are **tab-level** values being used as **per-series** identity. That is the category error.

### 1.2 The authority already exists — and is thrown away

`_vc_load.py:2173 _resolve_canonical_series_identity(display_key)` already returns
`(study_uid, orig_series_number, series_uid)` from the one map (`_server_series_info`).
It is called **20×** — and every caller uses a fragment of it, then re-derives the rest from tab
state. It is missing `study_pk` and `series_path`, which is exactly why the DB and disk stages
went their own way.

---

## 2. Target architecture — one immutable descriptor, threaded

Resolve **once**, at the moment the user picks a series, into an immutable value object; every
downstream stage *consumes* it and derives nothing.

```python
@dataclass(frozen=True)
class SeriesRef:
    display_key:   str   # "3" or "1000003" — the UI/handle key (digit, unchanged)
    study_uid:     str   # the series' OWN study
    study_pk:      int | None
    series_uid:    str   # globally unique — THE identity
    series_number: str   # the series' own (disk/orig) number
    series_path:   str   # SOURCE_PATH/<study_uid>/<series_number>
```

**Build site:** the `SeriesRef` table is constructed where series info already arrives —
`_rebuild_multistudy_series_index` / `set_server_series_info` — so resolution becomes a **dict
lookup**, not a computation. It is rebuilt (not mutated) whenever `_server_series_info` changes.

**Consumption (no stage re-derives):**

| Stage | Today | With `SeriesRef` |
|---|---|---|
| disk path | `study_path/<key>` + 3 guards + `exists()` probes | `ref.series_path` |
| DB metadata | `study_pk=_effective_study_pk` (tab state) | `ref.study_pk` |
| cache key | bare series_number (+ study guard) | `ref.series_uid` |
| render gate | compares intended vs incoming uid | same — but now a *should-never-fire* assert |
| DM / grow lane | re-keys by uid or number | `ref.series_uid` |

**Invariant to enforce:** *no code on the show-a-series path may read `import_folder_path` or
`metadata_fixed['study_pk']` for identity.* They remain only as the tab's *primary-study* display
values.

---

## 3. Aspects evaluated

### 3.1 Correctness
The three bugs become **structurally impossible**, not guarded-against: the wrong study cannot be
reached because no stage computes a study. Cache collisions on a shared series *number* vanish
because the key is the globally-unique `series_uid`.

### 3.2 Performance (the "speed" half of the directive)
Today, **per series load**, the pipeline pays:
- `Path.exists()` probes in `_resolve_plain_series_study_path` (disk I/O on the load path),
- a `find_study_pk_with_study_uid()` **DB query** (per secondary load; now also per primary load
  because of my STUDY-PK-GUARD),
- `_count_series_files_on_disk` `scandir` (1 s TTL) for the stale-check,
- multi-tier cache scans + guard scans.

After: one resolution when series-info arrives (work we **already do**), then **O(1) dict lookup**
per load. Net effect: fewer disk probes and DB round-trips on the interactive path, and the
guard branches disappear from the hot path. Expect the win to be modest in absolute ms but it
removes I/O from the click→first-image path, which is where it is felt.

**Measure, don't assume.** Baseline before/after on the same patient:
`[FAST_LOAD_BREAKDOWN] db_lookup / cached_metadata / reconcile_disk / normalize`, plus
`first_image_visible render_ms` and `[UX_SERIES_LOAD_START] → first_image_visible` wall time.

### 3.3 Clinical safety
Highest-severity area in the codebase (wrong-study images). Therefore:
- **The identity gate STAYS.** It is the fail-closed backstop that caught all three bugs. It is
  cheap, and after this work it should simply never fire.
- Nothing in this plan changes decode, geometry, slice order, orientation, WL, or the
  FAST/Advanced/VTK domain boundaries. **Identity resolution only.**

### 3.4 Risk
The refactor touches the most-guarded path in the app. Mitigated by phasing (§4), by keeping every
existing guard ON during migration (§5), and by the fact that each phase is independently
revertible via its own flag.

### 3.5 Testability
`SeriesRef` construction is **pure** (dict in → frozen dataclass out) ⇒ fully unit-testable
offscreen, no Qt/VTK/pydicom. The 50238/49836/48912 scenarios become table-driven fixtures.

### 3.6 Rollback
One flag (`AIPACS_SERIES_REF_PIPELINE`) reverts the whole consumption path to the legacy
derivations. Per-phase flags allow reverting a single stage.

---

## 4. Migration phases (each shippable, verifiable, revertible)

> **Rule:** no phase deletes a guard. Guards are retired **only** in Phase 5, and only after
> proving they never fire.

**Flag-default policy (your standing instruction, 2026-07-07: *"make all the changes in default so I
can evaluate them on build and via the routine run"*).** Every phase ships **default-ON with a kill
switch**, matching the rest of this codebase — a default-OFF flag is never exercised in routine
clinical use and therefore never actually evaluated. Safety comes from **shipping one phase at a
time** (so any regression is attributable to exactly one change), from the guards staying on as the
detector (§5), and from the kill switch — not from leaving the code dark.

**Phase 0 — Build the authority (additive, ZERO behaviour change).**
Add `series_ref.py` (pure, stdlib-only): `SeriesRef` + `build_series_ref_table(server_series_info,
primary_study_uid, source_path, pk_lookup)`. Populate the table where series info lands. **Nothing
consumes it yet** — the table is built and compared, never used to load. A shadow check logs
`[SERIESREF-SHADOW] mismatch` whenever the table disagrees with what the live pipeline actually
used. *This is the regression oracle for every later phase.*
**Default-ON** (it cannot regress anything — it only builds a dict and logs), kill switch
`AIPACS_SERIESREF_SHADOW=0`.
→ Ship, run routinely for a week, expect **zero** mismatches. If it disagrees, the table is wrong —
fix it before touching a single consumer.

**Phase 1 — Disk path.** `_load_single_series_on_demand` takes `series_path` from the ref.
Retires the *need* for the two path guards (but keeps them).
Flag `AIPACS_SERIESREF_DISK`.

**Phase 2 — DB metadata.** `study_pk` from the ref. Retires the *need* for
`AIPACS_MULTISTUDY_PER_SERIES_STUDY_PK` + my new `AIPACS_PRIMARY_STUDY_PK_GUARD`.
Flag `AIPACS_SERIESREF_DB`.

**Phase 3 — Cache keys.** Key the viewer caches by `series_uid`.
⚠ **Known trap (CLAUDE.md / OPT-17):** the ZetaBoost warmup callback `_zeta_boost_load_series`
**hard-requires a digit key** (`isdigit()` / `int(sn)`). A composite key silently breaks warmup.
⇒ Keep `display_key` (digit) as the *public handle*; use `series_uid` only as the *internal* cache
key. This is why Phase 3 is separate and later than 1–2.
Flag `AIPACS_SERIESREF_CACHE`.

**Phase 4 — DM / grow-lane / thumbnail re-key** onto the same ref (folds OPT-06's study-scoped
bind into the authority rather than a bespoke fallback).
Flag `AIPACS_SERIESREF_DM`.

**Phase 5 — Retire the guards.** Only for a guard that has logged **zero firings** across the
validation matrix (§6) and ≥2 weeks of live use. Delete one at a time, each its own commit, each
re-running the matrix. Target: **9 flags → 1** (`AIPACS_SERIES_REF_PIPELINE`) + the identity gate.

---

## 5. Regression-avoidance strategy (the core of this plan)

1. **The existing guards become the verification instrument.** Keep all of them ON during Phases
   0–4. If the new pipeline is correct, they become **no-ops**. Every guard already logs when it
   corrects something (`[TAB-PATH-GUARD]`, `[STUDY-PK-GUARD]`, `[MULTI-STUDY LOAD]`,
   `[CACHE-STUDY-MISMATCH]`). **A guard that fires after a phase ships = that phase is wrong.**
   This gives a *free, precise, production* regression detector — we do not have to guess.
2. **The identity gate is the fail-closed oracle.** `[IDENTITY-GATE] SKIP` must remain at **0**.
   Any non-zero count is a hard stop and an immediate revert of the phase flag.
3. **Phase 0 shadow-compare before any consumer changes.** We do not migrate a stage until the
   table has proven, in production, that it agrees with the current behaviour.
4. **Single-study must be byte-identical.** Single-study tabs have exactly one study, so every ref
   field equals what the legacy derivation produced. Assert this in tests *and* in the shadow log.
5. **Per-phase kill switches, shipped default-ON, ONE PHASE AT A TIME.** Attribution comes from
   sequencing, not from darkness: if a phase ships alone and a guard fires or the gate skips, it is
   that phase. A phase is only started once the previous phase's shadow/guard signals are clean.
6. **No behaviour changes ride along.** Identity only. No decode/geometry/order/WL/domain changes,
   no "while I'm here" cleanups.
7. **Guard tests stay.** The 21 existing tests (49836 + 50238) must keep passing throughout; they
   encode the exact live failures.
8. **Every prior correction in §7 is a test, not a memory.** Each one below gets a pin in the guard
   suite so the refactor cannot silently undo it.

---

## 6. Validation matrix (run for every phase)

| Case | Patient | Must hold |
|---|---|---|
| Colliding numbers, primary after secondary (DB) | **50238** | study 1 series 2/3/4 show study 1's images (90-image series 3, uid …107555) |
| Colliding numbers, tab-path poison | **49836** | study A series 3 shows uid …3657708721 |
| Previous exam, plain key after offset | **48912 / 29694** | current series 4 ≠ previous exam's series 4 |
| Secondary study series | any multi-study | offset keys still load their OWN study (48101 must not regress) |
| Document / DICOMized (series 100000 / 1100000) | 50238 / 49836 | still displays |
| **Previous exam** (cross-PatientID, `sanctioned_uids`) | 45289 / 48101 | loads from its OWN study; **no unsanctioned study admitted** (C9) |
| **Synthetic series number** (device omitted `SeriesNumber` → 9xxxxx band) | Roshana center | study downloads + displays; the synthetic stays a plain key (C1, C2) |
| Distinct series sharing name+count across studies | 49317 | **appended**, not deduped → renders (C6) |
| **Single-study patient** | any | **byte-identical**; zero guard firings; zero shadow mismatches |
| Cine / multi-frame | any | unchanged |

**The two halves of the original OPT-20 ask must BOTH hold** (*"not miss import and not import with
each other"*): every series dragged renders (**no miss**), and no series ever paints another study's
images (**no cross-mix** — `[IDENTITY-GATE] SKIP` = 0 *because nothing wrong is ever offered*, not
because the gate is busy catching it).

**Signals per run:** `[IDENTITY-GATE] SKIP` = 0 · `[SERIESREF-SHADOW] mismatch` = 0 · every guard
firing count = 0 · `ViewportLoadFailed` = 0 · per-series `first_image_visible` ≥ 1 for every series
dragged · `[FAST_LOAD_BREAKDOWN]` timings not worse than baseline.

---

## 7. Prior corrections this refactor MUST NOT undo (each gets a guard-test pin)

These are hard-won and are exactly the kind of thing a "clean rewrite" quietly reverts. Every one is
a **pin in the guard suite**, not a note.

### 7.1 Rules the new `SeriesRef` builder must obey

| # | Correction | Why it bites here |
|---|---|---|
| C1 | **NEVER `int()` a server-provided series field.** Use `series_identity.parse_series_number()` (tolerant, never raises). | OPT-25 / Roshana: the server sent the literal string `"None"`; `int("None")` aborted the WHOLE study's metadata build and the study never downloaded. The `SeriesRef` builder parses server series numbers — it is *exactly* the code that would re-introduce this. |
| C2 | **Synthetic numbers stay in the reserved band 900001–999999**, strictly **below** the 1 000 000 offset threshold, assigned in `series_uid` order. | A series with no `SeriesNumber` gets a synthetic. It must remain a *plain* key (primary study) and must never collide with, or be mistaken for, an offset key. `SeriesRef` must carry it through unchanged. |
| C3 | **Healthy data is byte-identical, incl. TYPE** — `"02"` stays the string `"02"`, never `2`. | Folder/thumbnail naming depends on it. `SeriesRef.series_number` must not "clean up" a valid number. |
| C4 | **Images are fetched by `series_uid`, never by series number.** | This is *why* the whole scheme is safe. Preserve it. |

### 7.2 Fixes in the display path that must keep working

| # | Correction | Risk during migration |
|---|---|---|
| C5 | **Never compare a series NUMBER to a list INDEX** (OPT-20 (6): `last_series_show` is a *number*, `series_idx` is an *index*; the async-apply render gate was always False for offset keys). The `AIPACS_APPLY_RENDER_TARGET_VIEWER` render-for-the-targeted-viewer path is the fix. | The apply/render stage is a `SeriesRef` consumer. If I re-plumb it and "tidy" the gate back to an index compare, every previous-exam series stops rendering again. |
| C6 | **A distinct series sharing `series_name`+count with another study's series must be APPENDED**, not deduped (`AIPACS_SERIES_APPEND_STUDY_DISTINCT`, `_pw_metadata.py`). | List *placement* is upstream of identity. If the series is never appended, `replace_series_data` returns −1 and the render loop is gated off regardless of how good `SeriesRef` is. This is a **separate concern the refactor must not absorb or break**. |
| C7 | **`_count_series_files_on_disk` resolves an offset key to the series' OWN canonical folder** (now unconditional — 48476). | `SeriesRef.series_path` makes this trivial, but the A1 grow watchdog keeps its **own fresh `scandir`** on purpose (it needs an atomic `.dcm`+`.part` snapshot for the settle decision that the 1 s-TTL shared counter cannot give). **Do NOT force-unify A1's scan.** |
| C8 | **The 48101 per-series `study_pk` for a SECONDARY series stays** (`AIPACS_MULTISTUDY_PER_SERIES_STUDY_PK`). A secondary series must use ITS OWN pk. | The 50238 guard pins *plain* keys to the primary. `SeriesRef` must serve **both**: `ref.study_pk` is the series' own — primary for plain keys, secondary for offset keys. Getting this backwards re-breaks 48101. |
| C9 | **Cross-patient isolation guards stay** (open / reconcile / resync / back-fill) and **Previous Exams enter only via the `sanctioned_uids` allow-list** (server-verified identity + explicit user click). | `SeriesRef` decides *where a sanctioned series lives* — it must never become a channel for admitting an unsanctioned study. Identity resolution ≠ admission. |
| C10 | **ZetaBoost warmup hard-requires a digit key** (`isdigit()`/`int(sn)`). | `display_key` stays the public digit handle; `series_uid` is the *internal* cache key only. This is why Phase 3 is separate and last. |
| C11 | **The offset-key scheme (`slot*1_000_000 + orig`) stays.** It is the UI handle, not the identity. | Do not "improve" it into a composite string — that is C10's trap and breaks the thumbnail/DM keys too. |

### 7.3 Architecture rules that outrank this plan

- **FAST / Advanced / VTK-modules stay completely separated** (the NON-NEGOTIABLE hard rule).
  `SeriesRef` is a **trunk** value object — immutable, identity-keyed, read-only. That is precisely
  what the trunk is allowed to carry. It must **not** become a channel through which one domain
  reaches another's cache, widget, or lifecycle. If a phase cannot be done without coupling the
  domains, **do not do it**.
- **FAST never instantiates a VTK render window.** Nothing here changes that.
- Extend the master plan (OPT-35); do not spawn a competing optimization plan.

### 7.4 Operational traps

- **Read logs HOST-side** (Read/Grep tools), never via the sandbox bash mount — it serves truncated
  copies and has already faked both a "stalled log" and false SyntaxErrors. It also silently wrote a
  **corrupt plugin mirror** once: **never run `sync_plugin_mirrors.py` from the sandbox.**
- `[MULTI-STUDY LOAD]` is `logger.info` and app.log has not always captured viewer-module INFO —
  **raise/route the identity traces BEFORE Phase 0**, or no phase can be verified. (This is what made
  49836 take an extra round: the resolution trace was invisible and the bug had to be proven by
  reading SeriesInstanceUIDs off the DICOM.)
- `_vc_load.py`, `_vc_switch.py`, `_vc_cache.py`, `_pw_metadata.py` are **not** plugin-mirrored;
  `qt_fast_container.py` / `qt_viewer_bridge.py` **are** — run `verify_plugin_mirrors.py` after edits.
- The identity gate's `study_uid[:48]` log clipping is **display-only** — a clipped uid is not a
  truncated uid (this red herring cost a round on 48101).

---

## 8. Explicit non-goals

- Not touching decode, geometry, slice order, orientation, WL, MPR, or the FAST/Advanced/VTK
  separation.
- Not changing the offset-key display scheme.
- Not removing the viewport identity gate (it is the clinical backstop, and it is cheap).
- Not a general viewer refactor — **identity resolution only**.

---

## 9. Decision requested

Phase 0 is additive and zero-risk — it only *builds and shadow-compares* the table; nothing consumes
it, so it cannot change what is displayed. It ships **default-ON** (per your standing instruction)
precisely so it is exercised in routine clinical use, and it is the thing that tells us whether the
rest of the plan is sound **using production data rather than my judgement**.

**Recommend: approve Phase 0 now**, review a week of `[SERIESREF-SHADOW]` output, then decide on
Phases 1–5 with evidence in hand. Prerequisite inside Phase 0: raise/route the identity traces
(§7.4) — without them no phase is verifiable.

Interim: today's `AIPACS_PRIMARY_STUDY_PK_GUARD` stays as the stop-gap so 50238 works now.
