# EchoMind Secretary — LLM Prompt Structure Guide

**Date:** 2026-02-20

This document defines **exactly** what we must send to the LLM so it understands our internal software structure and returns **executable JSON** without any human interpretation.

It focuses on two internal structures you requested:

1) **Patient Search Structure** (filters: modality + date/day)
2) **Open Patient Structure** (open by patient code)

It also includes the **precise command formats** the LLM must return for each action.

---

## 1) Core Prompt Contract (what we send to the LLM)

The prompt must include **four blocks**:

1. **Strict JSON-only rule**
2. **Exact executable schema** (what our commander validates)
3. **Action registry** (what is allowed + required fields)
4. **User message (raw, unchanged)**

Below is the **canonical structure** that should be used in the system/developer message.

### 1.1 Strict output rule

```
Return ONLY a single JSON object.
No markdown, no code fences, no prose.
The output MUST match one of the supported contracts.
```

### 1.2 Executable command schema (strict)

This is the **exact structure** our internal commander accepts for executable commands:

```json
{
  "action": "list_patients | open_patient | download_patient",
  "entities": {},
  "confidence": 0.0,
  "needs_confirmation": false,
  "reason": "short reason"
}
```

### 1.3 Action registry (allowed commands + allowed fields)

```
Action: list_patients
  allowed entities: source, date, modality
  needs_confirmation: false

Action: open_patient
  allowed entities: source, patient_code, resolved_patient
  needs_confirmation: true

Action: download_patient
  allowed entities: source, patient_code, use_context_patient, resolved_patient
  needs_confirmation: true
```

### 1.4 Validation rules to include

```
Required fields: action, entities, confidence, needs_confirmation, reason
action must be one of: list_patients, open_patient, download_patient
source must be one of: active_tab, local, server
date may be: today | yesterday | yyyy-mm-dd | yyyymmdd | start..end
unknown entity keys are forbidden
```

### 1.5 Clarification policy (when the LLM must ask)

```
Ask for clarification when:
- open_patient or download_patient is requested but no patient_code or context is provided

Return error JSON when:
- action is unsupported
- output cannot satisfy schema
```

---

## 2) Patient Search Structure (filters: modality + date/day)

### 2.1 Internal structure summary

The PACS patient search accepts filter criteria such as:

- **modality** (e.g., MR, CT, US)
- **date filter** (today, yesterday, or explicit range)

These filters are executed through our internal search criteria:

```
criteria = {
  date_from: "YYYYMMDD",
  date_to:   "YYYYMMDD",
  modality:  "MR" | "CT" | ...
}
```

### 2.2 How this must be represented in the LLM prompt

The LLM must be told that **patient search maps to**:

```
action = "list_patients"
entities may contain:
  - date (token or range)
  - modality (normalized DICOM modality)
  - source (active_tab | local | server)
```

### 2.3 Exact command structure the LLM must return

**Example: “Show yesterday’s patients”**

```json
{
  "action": "list_patients",
  "entities": {
    "date": "yesterday"
  },
  "confidence": 0.90,
  "needs_confirmation": false,
  "reason": "user requested patient list with yesterday filter"
}
```

**Example: “Show today’s MRI patients”**

```json
{
  "action": "list_patients",
  "entities": {
    "date": "today",
    "modality": "MR"
  },
  "confidence": 0.92,
  "needs_confirmation": false,
  "reason": "user requested patient list filtered by modality and date"
}
```

### 2.4 Execution expectation

The internal commander will normalize `date` into a concrete range:

```
today     → date_from = date_to = YYYYMMDD (local time)
yesterday → date_from = date_to = YYYYMMDD (local time)
range     → date_from/date_to from provided range
```

Then it executes the search and returns the filtered list.

---

## 3) Open Patient Structure (open by patient code)

### 3.1 Internal structure summary

Opening a patient is a **side‑effect action** and must always be confirmed.

Internal behavior:

1. Find the patient by `patient_code`.
2. Open by simulating a double‑click.

### 3.2 How this must be represented in the LLM prompt

The LLM must be told that **open patient maps to**:

```
action = "open_patient"
entities must include:
  - patient_code (string)
needs_confirmation = true
```

### 3.3 Exact command structure the LLM must return

**Example: “Open patient code 2342.”**

```json
{
  "action": "open_patient",
  "entities": {
    "patient_code": "2342"
  },
  "confidence": 0.93,
  "needs_confirmation": true,
  "reason": "user requested opening a patient by code"
}
```

### 3.4 Clarification rule for open_patient

If no `patient_code` is present, the LLM must return a **clarification JSON** asking for it.

Example:

```json
{
  "kind": "clarification",
  "question": "Which patient code should I open?",
  "required_fields": ["patient_code"],
  "suggested_options": []
}
```

---

## 4) User Message Handling (raw Persian input)

The LLM must receive the **raw user text unchanged** as the `user` message.

Example user payload:

```
User message (raw, unchanged):
لیست بیماران دیروز رو به من نشون بده
```

The LLM must interpret it **without any developer-side interpretation**, and return a valid JSON command as described above.

---

## 5) Summary (what the prompt must enforce)

1. **Only JSON output** (no markdown, no prose).
2. **Strict schema** with required fields.
3. **Allowed action registry** (list_patients, open_patient, download_patient).
4. **Patient search structure** uses entities: date, modality, source.
5. **Open patient structure** requires patient_code + needs_confirmation=true.

This ensures the internal commander can execute the returned JSON **directly**, without any additional interpretation.
