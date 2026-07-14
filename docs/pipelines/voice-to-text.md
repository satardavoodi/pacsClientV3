# Voice-to-Text pipeline (Persian transcription) — as-built

**Status:** implemented 2026-07-13. Default ON.
**Kill switch:** `AIPACS_ECHOMIND_STT_ENDPOINT=0` (restores the legacy hard-coded endpoint).
**Authority:** `modules/EchoMind/voice_transcription.py` — `VoiceTranscriptionService`.
**Configuration:** Settings ▸ EchoMind ▸ **Voice to Text**.

This is the **single, reusable component** for turning a recorded voice file into
Persian text. **Any** new feature that needs speech-to-text must call this service.
Do not add a second transcription path, and never hard-code a transcription URL again.

---

## 1. What it is

A recorded `.wav` is uploaded to a server that runs a Whisper model and returns
Persian text as JSON. The client does no ASR — it only records, uploads, and renders.

```
Voice recorded (any module)
  → WAV saved by that module's existing workflow
  → VoiceTranscriptionService.transcribe([path])
      → reads Settings ▸ EchoMind ▸ Voice to Text  (resolved PER CALL)
      → POST  <endpoint>          multipart: audio_files=<wav>, quality_mode=<clear|noisy>
                                  header:    Authorization: Bearer <token>
      → server-side Whisper transcribes (Persian)
  → JSON response
  → { transcript, quality_report, session_id, … } returned to the calling module
```

## 2. Providers

Selected in Settings; the two AI-PACS servers are shown **by name only** — their
addresses live in `voice_transcription.py` and must never be surfaced in the UI.

| Provider id | Label | Destination |
|---|---|---|
| `aipacs_1` | AI-PACS Server 1 | A100 GPU server (`AIPACS_SERVER_1_BASE`) |
| `aipacs_2` | AI-PACS Server 2 | Windows server (`AIPACS_SERVER_2_BASE`) — **the default** |
| `custom`   | Custom Server    | user-entered URL + port |
| `v2t`      | Google Speech    | local `speech_recognition` library, no endpoint |
| `openai`   | OpenAI Transcription | `{openai_base_url}/audio/transcriptions` |

`aipacs_1` / `aipacs_2` / `custom` are the **HTTP (Whisper) providers**
(`STT_HTTP_PROVIDERS`) — they share the same request shape and the same response
contract. `v2t` and `openai` are delegated to their existing providers and are
normalized into the same return shape.

## 3. How to use it from a new module

```python
from modules.EchoMind.voice_transcription import VoiceTranscriptionService

result = VoiceTranscriptionService().transcribe(
    [wav_path],                 # an ALREADY-SAVED file; the service never records
    quality_mode="clear",       # "clear" first; retry once as "noisy" on failure
)

if result["ok"] and result["transcript"]:
    persian_text = result["transcript"]
else:
    show_error(result["error"])
```

Or the one-liner: `transcribe_voice_files([path], quality_mode="clear")`.

**Run it OFF the GUI thread.** The upload can take minutes. Both existing callers
wrap it in a worker (`ApiWorker(QThread)`); do the same.

### Response contract

The server's **raw JSON body is merged through**, then normalized keys are added:

| Key | Meaning |
|---|---|
| `ok` | bool — the request succeeded |
| `transcript` | **the Persian text** (stripped; `""` when nothing was recognized) |
| `quality_report` | `[{accepted: bool, criteria: {reason, energy, zcr, dbfs, speech_ms}}]` |
| `error` | message when `ok` is False |
| `session_id`, usage fields… | passed through untouched from the server |
| `endpoint`, `stt_provider`, `route_used` | which server actually handled it |

**A low-quality voice comes back as HTTP 200 with `accepted: false`** — *not* an HTTP
error. That is the signal for the "Voice Rejected" message and for the automatic
one-shot retry in `noisy` mode. **Never drop `quality_report`** when passing the
result through a wrapper — an earlier provider did, which silently disabled the
chat's rejection handling.

## 4. Current consumers

- **EchoMind Chat** — `modules/EchoMind/viewer_chat/ai_chat_pages.py`
  (`_transcribe_now` single voice; the queued/multi-file `work()`; and
  `_transcribe_with_active_backend`). Renders the transcript into the *Transcribe*
  (or *Correction*) tab, handles rejection, auto-retries once in `noisy` mode, and
  removes the voice chip on success.
- **Secretary EchoMind** — `PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py`
  via `SttRouter` → `NativeIrannobatProvider`, which delegates to this service. Its
  transcript then feeds Phase 2 (module routing).

`SttRouter` stays 3-way (`native | v2t | openai`); **every HTTP provider maps to
`native`** (`settings_store.stt_provider_to_legacy_route`).

## 5. Invariants — do not break

1. **The endpoint is resolved INSIDE a function, per call** (`resolve_endpoint()`).
   The original bug: `URL_GEN_TRANSCRIPT = f"{AI_BASE}/generate_transcript"` was
   built at **import** time and imported *by value*, so reassigning `AI_BASE` at
   runtime changed nothing. **Never cache the resolved URL in a module constant.**
   This is what makes a Settings change take effect with no restart.
2. **One service, both modules.** Chat and Secretary must never be able to send to
   different servers. Extend this service; do not fork a parallel uploader.
3. **The service never records and never saves.** It is handed a path. Recording,
   WAV location (`%TEMP%\rec_*.wav` / `secretary_*.wav`) and attachment handling
   belong to the calling module and are out of scope.
4. **`quality_report` must survive** any wrapper (see §3).
5. **Auth:** the configured token wins; when empty it falls back to the GapGPT key
   (`Manage.instance().ensure_detected().gapgpt_key`). Best-effort — resolving the
   token must never raise into the audio path.
6. **Upgrade safety:** the legacy `secretary_stt_provider: "native"` meant the
   hard-coded `AI_BASE` = the **Windows** server, so it maps to `aipacs_2`. An
   install that never opens this screen keeps hitting the exact server it hits
   today. Do not remap it.
7. **Build:** `stt_custom_base_url` and `stt_auth_token` are blanked by
   `builder/config_sanitizer.py` — a centre's own server/token must never ship.
   The provider *choice* is a product default and does ship.
8. `modules/EchoMind/*` is **plugin-mirrored** (echomind package). After editing,
   run `tools/dev/sync_plugin_mirrors.py` then `verify_plugin_mirrors.py`. A **new**
   module needs `--add <path>` (a plain sync only updates existing pairs).

## 6. Settings keys (`echomind_settings.json`, roaming config)

| Key | Default | Notes |
|---|---|---|
| `stt_provider` | `""` | `""` ⇒ derived from the legacy `secretary_stt_provider` |
| `stt_custom_base_url` | `""` | custom only; sanitized out of builds |
| `stt_custom_port` | `0` | `0` = the port is part of the URL |
| `stt_endpoint_path` | `/generate_transcript` | |
| `stt_timeout_seconds` | `360` | |
| `stt_auth_token` | `""` | optional; sanitized out of builds |

Accessors: `get_stt_provider()`, `get_stt_settings()`, `save_stt_settings()`,
`get_secretary_stt_route()` (the 3-way router view).

## 7. History — why this exists

Before 2026-07-13 there were **two disconnected pipelines and no configuration**:
the chat POSTed directly to `{AI_BASE}/generate_transcript` and ignored the
Voice-to-Text setting entirely, while Secretary reached the same frozen constant
through `NativeIrannobatProvider` (sending **no** auth header). The destination
could only be changed by editing code, and the two modules could silently disagree.
`_transcribe_with_active_backend` — which *would* have honoured the backend — was
dead code, never called.

## 8. Tests

`tests/code/echomind/test_voice_transcription_service.py` (17) — endpoint
resolution, per-call resolution (the no-restart guarantee), both modules hitting the
same server, upload format/timeout/auth, `quality_report` survival, legacy mapping,
the 3-way router mapping, the kill switch, and source-pins that no hard-coded
endpoint remains in either module.

**Live verification still needed:** record in EchoMind Chat and in Secretary, against
**Server 1** and **Server 2**, and confirm the Persian text returns in each.
