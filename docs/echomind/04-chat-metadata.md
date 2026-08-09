# 4 · Chat metadata

**Scope:** the per-chat case record — where every field comes from, when it is written,
where it is stored, and how the physician's edits interact with detection.

**Owner:** `modules/EchoMind/session_metadata.py` · **UI:** `viewer_chat/metadata_panel.py`

---

## 4.1 What it is

Every EchoMind chat (`ai_sessions.sid`) gets a persistent record describing the **case**
the chat is about: patient, study or studies, reception services, modality, regions.

It is **not** the report and **not** the conversation. It is the context a report is
generated *from*.

> **Note for anyone reading the module docstring:** it still says *"Nothing here reaches
> any prompt."* That was true on 2026-08-06 and is no longer true — `_build_gate_profile()`
> reads this record on every Turbo report. The docstring is stale; this document is
> current.

---

## 4.2 The three layers

```
auto       what detection produced (DICOM, reception, later transcript/LLM)
user       ONLY the fields the physician edited — sparse
effective  = deep_merge(auto, user)          user wins, field by field
```

Storing them apart is what makes three things possible that a single merged blob cannot:

- re-detection refreshes `auto` **without destroying** the physician's corrections
- the UI can say "detected" versus "you set this"
- "reset this field" is a delete, not a guess

A merged blob forces a bad trade: either a refresh silently clobbers user intent, or one
edit freezes all future enrichment.

**`deep_merge` does not merge lists** — a list in `user` replaces the list in `auto`
wholesale. Consequence: **user paths must never contain a numeric segment.** Writing
`studies.0.modality` builds a dict `{"studies": {"0": {...}}}` that will never merge with
the `auto` list. Write to a scalar path, or replace the whole list.

---

## 4.3 The record

```python
{
  "schema_ver": 1,
  "patient":    {"patient_id": …, "sex": "M|F|O", "age": …},
  "studies":    [{"study_uid": …, "study_description": …, "modality": …, …}],
  "reception":  {"service": …, …},
  "case":       {"modality_selected": …, "regions": [...], "contrast": …,
                 "subtype": …, "procedure": …},
  "provenance": {"patient.sex": {"source": "dicom_file", "confidence": "high"}, …},
}
```

**Every field that lands carries provenance.** Anything absent is omitted rather than
guessed. `provenance` is keyed by dotted path and records `source` and `confidence`, and
it is what lets the prompt's `STUDY_CONTEXT` slot print `(DICOM)` vs `(service booking)`
vs `(set by the physician)` — three things that carry very different weight, and the last
of which is not a hint at all.

---

## 4.4 Where each field comes from

| Field | Primary source | Fallback | Notes |
|---|---|---|---|
| `patient.patient_id` | `patients` table | — | |
| `patient.sex` | `patients.sex` | **DICOM file header** (`PatientSex`) | the table is **3% populated** on this installation; the file is not |
| `patient.age` | DICOM `PatientAge` | — | |
| `studies[].study_uid` | `studies` table | — | |
| `studies[].study_description` | `studies` table | DICOM `StudyDescription` | |
| `studies[].modality` | `series` rows | DICOM `Modality` | |
| `reception.service` | reception booking, **cached locally** | — | see §4.5 |
| `case.modality_selected` | the physician's menu choice | `studies[0].modality` | |
| `case.regions` | derived — see below | — | |
| `case.contrast` | service booking text | — | |
| `case.subtype`, `case.procedure` | service booking text | — | carried, not yet fully derived |

### Why the DICOM file is read at all

The SQLite projection of DICOM is lossy on exactly the fields that matter:
`sex` 3% populated, `body_part_examined` 7%, `protocol_name` 0%. `read_dicom_facts()`
reads six tags straight from the file:

```
PatientSex · PatientAge · StudyDescription · ProtocolName · BodyPartExamined · Modality
```

It walks up to `max_series=40` series and **skips non-image series**:

```python
_NON_IMAGE_MODALITIES = {"DOC", "SR", "PR", "KO", "SEG", "RTSTRUCT", "PDF"}
```

That set is not defensive tidiness. The scanned reception sheet is imported as a `DOC`
series into the same study, and on this installation it **sorts first** — which is how 866
studies ended up with a NULL patient sex while every CT slice in them carried `M`. The
importer was fixed the same way (`pick_representative_instance` skips the same set), for
new imports only.

### How regions are derived

`build_auto_from_context()` scores canonical regions against `_DICOM_REGION_MAP`, using
`BodyPartExamined`, `StudyDescription`, `ProtocolName` and series descriptions. **One vote
per field per region** — without that cap, twelve series descriptions at weight 0.8 buried
one `BodyPartExamined` at weight 4.0.

`normalize_region()` maps raw strings onto canonical keys. `heart` is not a key — it maps
to `chest`; `neck` maps to `head_neck`. A test asserts every emitted key is canonical,
because a non-canonical key silently selects no module.

---

## 4.5 Reception services, and when they are fetched

Reception data is not in DICOM. It is a network call, and it used to happen only when
somebody opened the reception tab — so the metadata card read "not detected" for the
service, the contrast state and anything derived from them.

**It is now prefetched during dictation.**

```
UnifiedComposer._start_record()
    → recordingStarted.emit()          ← the FIRST statement of the method
    → _prefetch_reception()            ← ai_chat_pages.py:1370
    → reception_prefetch.prefetch(study_uid=…)
```

Recording and transcription are the only part of a session where the network is idle and
nobody is waiting. By the time the report chat is minted the service list is already local.

`prefetch()` returns immediately: daemon thread, deduplicated per patient via `_inflight`
(released in `finally`), skipped when the cache is younger than `max_age_s=900`, and hard-
capped at `FETCH_TIMEOUT_S=8.0`. It is fully swallowed — it is called while an audio stream
is being opened and must never be able to interfere.

**The cache** is its own table, written whenever the reception tab fetches:

```sql
ai_reception_services(patient_id TEXT PRIMARY KEY, services_json TEXT,
                      study_uid TEXT, updated_at TEXT)
```

Stored as JSON rather than normalised columns, deliberately: the service catalogue differs
per centre and per year, and a schema would have to change with it.
API: `ai_save_reception_services`, `ai_get_reception_services`,
`ai_get_reception_services_updated_at` (`database/ai_reception_db.py`, exported through
`database/core.py` and `PacsClient/utils/__init__.py`).

---

## 4.6 Known gap: service text does not reach region detection

`build_auto_from_context()` **receives** `reception_services` and uses it for contrast and
service display, but derives regions from DICOM only.

The design weights the service booking at 5.0 — the strongest single signal, because it is
what the study was *ordered as*. The code weights it 0.

Concrete consequence, on study 53516: the booking is
`سي تي اسکن شکم و لگن با و بدون تزريق` — abdomen **and pelvis** — but only chest and abdomen
are detected. The dictated inguinal finding therefore has no pelvis package gated in.

Implementing it needs ordered keyword matching over Persian service text with Arabic-script
normalisation (`ي→ی`, `ك→ک`), which is exactly the normalisation the rest of the app already
applies to Persian input.

---

## 4.7 Lifecycle

| Event | What happens | Where |
|---|---|---|
| Chat created | `populate_for_chat(sid, study_uid=…, modality_selected=…)` builds and stores `auto` | ai_chat_pages.py:5786 |
| Recording starts | reception prefetch fires, warming the cache for the next build | :1370 |
| Card shown | `_sync_metadata_card(sid)` points the card at the chat; `history.set_lead_widget()` puts it at index 0 | :5760, :1397 |
| Physician edits a field | `set_user_field(sid, path, value)` writes **only** to `user` | metadata_panel.py:365 |
| Physician clears a field | `clear_user_field(sid, path)` removes the override; `auto` shows again | :363 |
| Turbo pressed | `_build_gate_profile()` reads `load(sid)` — the effective record | :5702 |
| Chat deleted | `delete(sid)` | — |

`populate_for_chat` is **best-effort by design**: any lookup failure yields a smaller
record, never an exception. It is called where a chat is opening, and must never be able
to stop that.

That guarantee has a cost worth knowing. When `os` was missing from the module's imports,
`read_dicom_facts` raised `NameError`, `populate_for_chat` swallowed it, and the result was
indistinguishable from "this study has no metadata". Fully guarded, completely silent, and
found only by querying real data. If the card is emptier than it should be, check the debug
log before concluding the data is absent.

---

## 4.8 Storage

```sql
ai_session_meta(sid        TEXT PRIMARY KEY,
                auto_json  TEXT,
                user_json  TEXT,
                updated_at TEXT,
                schema_ver INTEGER)
```

`ensure_schema()` is idempotent and safe to call on every access. `SCHEMA_VERSION = 1`.

Two JSON columns, not one merged column — that is the three-layer model made durable. A
migration that merges them destroys the ability to re-detect.

---

## 4.9 The card

`metadata_panel.CaseMetadataCard` — an in-chat card, inserted as the **first item in the
conversation** via `ChatHistory.set_lead_widget()`, styled like the other chat cards.
`clear()` preserves it.

- `LAYOUT_ROWS` puts short scalars in pairs and long fields (study description, service,
  regions) on full rows.
- `_FitLabel` is used for both keys and values: `setWordWrap(True)` — without it
  `heightForWidth()` returns −1 and rows overlap — and a `_fit()` pass that sets the
  minimum height from the measured height at the current width.
- Minimum label width is 40 px. An earlier 96 px column floor pushed the card's minimum
  width to 637 px and risked a horizontal scrollbar in the chat.
- Values are resolved through `_dig_first()`, a fallback chain per field — e.g. modality is
  `case.modality_selected` → `studies.0.modality`.

**Testing geometry:** offscreen Qt loads **zero** font families, so absolute pixel
measurements are roughly 2× inflated and meaningless. Only relative geometry assertions
(this row is below that one; nothing overlaps) are valid.

---

## 4.10 Fields not yet in the record

Listed because they were asked for and because a mobile implementation should leave room:

| Field | Status |
|---|---|
| Physician identity | `resolve_physician_id()` / `resolve_physician_id_from_identities()` exist in the module; not stored in the record |
| Detected region confidence | scored during derivation, not persisted per region |
| Transcript-derived regions | not implemented |
| Study subtype | key exists in `case`, derivation incomplete |
