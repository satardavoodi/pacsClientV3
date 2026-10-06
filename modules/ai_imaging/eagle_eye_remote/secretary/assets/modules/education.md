# Module Document: Education
**module_id:** `education`
**Document version:** 1.0
**Sent in Phase 2 when the user issues an education / consultation /
courses / case-of-the-day command.**

---

## 1. What This Module Does

The Education module opens inside a workstation tab and contains:

* **Library** — searchable courses, books, videos (search supported)
* **My Courses** — the user's downloaded / created / imported courses
* **Build Course** — course authoring
* **Case of the Day** — daily teaching case
* **Online Consultation** — consultant directory, my consultations,
  requests (only present when the consultation module is enabled)

The Education tab is a singleton: every action below opens or activates
it automatically, then switches to the right section.

---

## 2. Available Actions

### `open_education`

Opens or activates the Education tab (no specific section).
No entities. **needs_confirmation:** `false`

### `open_consultation`

Education → Online Consultation tab.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `section` | string | no | `directory` \| `profile` \| `consultations` \| `requests` \| `storage` \| `shared`. "show MY consultations" → `consultations`. |

**needs_confirmation:** `false`

### `show_consultant_profiles`

Education → Online Consultation → Consultant Directory.
No entities. **needs_confirmation:** `false`

### `open_courses`

Education → My Courses tab.
No entities. **needs_confirmation:** `false`

### `open_case_of_day`

Education → Case of the Day tab.
No entities. **needs_confirmation:** `false`

### `search_education`

Education → Library tab, then runs the QUICK library filter (titles,
descriptions, tags only).

| Entity | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | The topic to search. Strip command words. |

**needs_confirmation:** `false`

### `search_education_content`

DEEP full-content search across ALL educational resources — courses,
slides, Case-of-the-Day entries, PDF/e-book files, PowerPoint decks,
and (only when explicitly requested) consultation notes. Runs as a
BACKGROUND task: the user keeps working; results arrive via the
Education icon badge + a notification with the result file.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | The topic, e.g. "ACL reconstruction". |
| `include_consultations` | boolean | no | Only set true when the user explicitly asks to include consultations. |

**needs_confirmation:** `false`

Use `search_education_content` (not `search_education`) when the user
says "find ALL …", "search everything", "including PDFs/slides", or
asks for resources "discussing/about" a topic.

---

## 3. Choosing the Right Action

* "open education" → `open_education`
* "open consultation", "show my consultations" → `open_consultation`
* "show consultant profiles" → `show_consultant_profiles`
* "open (my) courses" → `open_courses`
* "open case of the day" → `open_case_of_day`
* "search education for X" → `search_education` with `query=X`

## 4. Output Contract

```json
{
  "action": "open_consultation",
  "entities": {"section": "consultations"},
  "confidence": 0.95,
  "needs_confirmation": false,
  "reason": "User asked to see their consultations."
}
```

## 5. Error Envelopes

`MODULE_UNAVAILABLE` (education failed to open),
`CONSULTATION_UNAVAILABLE` (Online Consultation gated off on this
workstation), `SECTION_UNAVAILABLE`, `MISSING_QUERY`, `ACTION_FAILED`.
All recoverable; report the message to the user.
