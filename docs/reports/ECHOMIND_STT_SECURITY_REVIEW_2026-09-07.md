# EchoMind transcription routing and security review

Date: 2026-09-07. Scope: Company Server 1, Company Server 2, Google Speech,
and adjacent settings/transport boundaries. Review only; no runtime code changes,
credential rotation, server changes, audio uploads, or release build performed.

## Verdict

The settings-to-provider wiring has passing automated coverage, but these paths
cannot be described as fully secure or end-to-end verified. The connection-test
success indicator is insufficient evidence of authenticated transcription.

## Confirmed findings

1. **Unencrypted built-in company transport.** `voice_transcription.py:67` and
   `:68` configure public HTTP destinations. `_post_audio` uploads the recording
   and an optional bearer token. `resolve_auth_token` falls back to the selected
   center's GapGPT credential when the STT token is empty. Therefore that provider
   credential can be sent to a different service over HTTP. Encryption of the
   stored center registry does not protect this network transfer. This review did
   not inspect external VPN protection or server-side authorization policy.
2. **Google is remote, not local recognition.** `v2t_google.py:45` invokes
   `SpeechRecognition.recognize_google` without a project-specific key or endpoint
   override. Installed SpeechRecognition 3.16.1 uses an HTTP default endpoint and
   a generic library key for this call. The UI wording at
   `echomind_settings.py:1087` is misleading. No Google account/credential controls
   are provided in this form for the legacy route.
3. **Google ignores EchoMind transport controls.** `v2t_google.py:56` discards the
   timeout argument, and its Recognizer retains `operation_timeout=None`. The
   installed library sends with urllib `urlopen`, outside `echomind_http`; EchoMind
   Direct/SOCKS5 selection consequently does not control this route. System-level
   routing may still affect it; that is distinct from honoring app settings.
4. **False-positive connection success.** Company probes classify status codes
   below 500 as success. Isolated probes returning HTTP 401 produced `ok=True`
   for `aipacs_1`, `aipacs_2`, and adjacent `aipacs_3`. Google Test Connection only
   imports the library. Neither behavior verifies a successful transcription.
5. **Error details can expose destinations.** Several STT error paths return or
   log raw exception strings, including delegated provider errors. A safe failure
   contract should avoid emitting credentials, query parameters or clinical text.
   No actual secret-bearing error was printed during this review.

## Correct boundaries retained

- Saving Voice to Text updates the unified provider and the legacy Secretary
  route. The service resolves configuration per request; Server 1/2 destination
  changes do not require restarting the workstation.
- EchoMind Chat uses `VoiceTranscriptionService`; Secretary's native route
  delegates to it. Secretary explicitly disables automatic Google fallback.
- Company uploads use the common HTTP/proxy authority. Settings probes normally
  run off the GUI thread. These properties do not remedy plaintext HTTP.
- Adjacent Company Server 3 uses HTTPS and the validated center's encrypted
  provider credential; it has no independent embedded bearer key. Its connection
  test still has the status-classification defect above.
- Packaging sanitizes `stt_auth_token` and custom endpoint values.

## Evidence and limits

- Direct pytest: `test_voice_transcription_service.py`, `test_transcribe_retry.py`,
  `test_echomind_http_authority.py`, `test_echomind_http_timeout.py`:
  **76 passed**, process exit code **0**. These existing guards do not cover all
  findings above.
- Credential-free GET health probes to both configured company servers returned
  **HTTP 200**. No authorization header or audio was sent. Public health success
  says nothing about authorization on the upload endpoint.
- Inspected the installed Google library and reproduced the company 401 probe
  misclassification with mocked HTTP responses, without network traffic.
- Live source UI exposed all requested provider choices. A temporary form
  selection of Company Server 1 was possible, but Save could not be verified:
  computer control reported `foreground window did not report a process id`,
  and subsequent selection found no targetable AIPacs window. No relaunch was
  attempted. The persisted provider was independently checked and remained
  `aipacs_3`, the value at review start. Full live save/restore and transcription
  acceptance remain unverified.

## Recommended correction sequence

1. Establish verified HTTPS company endpoints with server-side STT authorization.
   Do not merely replace the URL scheme without verifying certificates and routes.
   Separate STT service credentials from the upstream LLM provider credential.
2. Correct connection-test semantics: distinguish library/config availability,
   network reachability, authentication and an actual synthetic transcription.
   Treat 401/403 as authentication failures, not success.
3. Make the selected Google implementation explicit and provide a supported,
   authenticated transport with TLS, bounded timeout and application proxy policy.
   Preserve the user's intended provider; do not silently migrate accounts or
   upload recordings elsewhere.
4. Add failing regression guards before each code correction, sync the EchoMind
   mirror, and verify both Chat and Secretary with nonclinical test speech after
   the human has launched the source app. Keep clinical recordings out of tests.

The review does not authorize deployment, provider migration or rotation of existing
credentials. Actual transcription accuracy and server-side credential enforcement
were not assessed by health checks or the automated tests.

## Repository-only follow-up

The owner deferred server-side HTTPS investigation and requested verification of
the repository code. No server requests or runtime source edits were made in this
follow-up.

- Expanded direct pytest selection: the four suites above plus
  `test_settings_probe_off_gui_thread.py` and
  `test_secretary_teardown_and_thread_safety.py`: **102 passed**, exit code **0**.
- Executed the actual Save, provider-change, and Test slot function bodies from
  the settings source with fake UI controls and a temporary configuration file.
  This tests slot logic without constructing the full workstation or its database;
  it is not live GUI validation.
- Save correctly persisted `aipacs_1`, `aipacs_2`, and `v2t`, with the corresponding
  Secretary route. Merely editing the selection did not persist a new provider.
- With a synthetic WAV and mocked HTTP transport, Chat's shared service and
  Secretary's native adapter sent to the same saved destination and honored a
  configured 17-second timeout on both company servers.
- The actual Test slot deferred work to its worker dispatcher and did not change
  the saved provider. Its request used the form configuration.
- Mocked 401 responses again produced `ok=True` for all three company probes.
- Exercised the actual installed Google recognizer with its network function
  mocked: a requested 7-second timeout reached the network boundary as `None`.
  The shared EchoMind HTTP transport was not called. No real Google request was
  made and no generic library key was displayed.

Thus local routing/save behavior is verified, but connection-result classification
and Google timeout/proxy behavior remain confirmed code defects. Passing existing
tests does not imply these uncovered behaviors are correct. Corrections and their
durable failing-before/passing-after regression guards remain a subsequent task.


## Quality policy confirmation and manual selection correction

The owner confirmed report/chat defaults to clear and retries once with noisy after
a quality rejection on servers 1/2; Agent starts with noisy; Google ignores quality
mode. Local recording levels drive waveform display, not a quality classifier.
Server threshold implementation was not tested.

The immediate chat slot ignored the file payload's manual quality selection and
the microphone composer's selection. It now reads those on the first attempt,
defaults to clear, and leaves the retry handler's explicit mode authoritative.
The queued multi-file path already reads the composer selection. Agent and Google
behavior are unchanged. The slot docstring now distinguishes transport retries.

Seven behavioral cases execute the real slot prefix without workstation startup,
database access, or network calls: two failed before; all seven pass after.
The focused STT suite passes 109 tests (exit 0); the builder mirror guard passes
one test (exit 0). Canonical and plugin payload were synchronized; all 462 mirror
pairs match. This is repository-level verification, not live UI, server threshold,
or installer validation. Previously reported connection-probe and Google timeout
findings are outside this quality fix.
