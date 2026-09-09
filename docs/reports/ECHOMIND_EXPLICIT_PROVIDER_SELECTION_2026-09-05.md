# EchoMind explicit provider selection

The installed 3.6.5 Eagle Eye run saved its images successfully but selected direct
OpenAI from an older roaming user configuration. Missing Eagle Eye model settings
were then filled with company-route model defaults. The log showed a Gemini request
to the direct endpoint, one HTTP 404, and a separate upload write timeout. The exact
network cause of the timeout was not established. No clinical content or credentials
are reproduced here.

## Corrected contract

- Company/GapGPT is the default through the existing company entitlement and key authority.
- Direct mode requires a saved `openai` selection, the user's key, and the user's Base URL.
  Missing configuration resolves to company; credentials alone do not select direct mode.
- No runtime, connection probe, transcription fallback, settings form, or bundled
  EchoMind configuration supplies a hardcoded direct OpenAI endpoint.
- A per-call key override cannot switch a company request to direct mode.
- Direct Eagle Eye screening and diagnosis models must be explicitly selected in
  EchoMind Settings. Both fields are now visible and persisted. Missing selections
  stop the run before a worker/request starts and retain a retryable failure record.
- Company Eagle Eye model defaults remain in the company pipeline. They are not a
  fallback for missing direct-provider models. Explicit field/environment overrides
  remain available; supported model availability at a custom provider is not inferred.

Existing complete explicit direct configurations remain valid. This change does not
reset installed user preferences, rotate credentials, or automatically select company
for a user who already saved a complete direct configuration. Older such users must
choose their Eagle Eye models or select company mode before using Eagle Eye.

## Implementation and verification

`settings_store` remains the shared selection authority. `llm_client` and the optional
OpenAI transcription provider require an explicit endpoint. The settings form no longer
prefills an endpoint and prevents activating incomplete direct configuration. The Eagle
Eye resolver no longer swallows missing direct-model errors; its runner reports them
without starting a worker. No image preparation, diagnostic prompts, clinical geometry,
company credentials, or provider endpoint for the company route was changed.

The initial guard reproduced **14 failures and 4 passes**, exit 1, before production
changes. The final affected selection passes **205 tests**, with **1 existing expected
failure** and 6 existing SWIG deprecation warnings, exit 0. It includes 21 provider/UI/
runner guards, shared backend authority, pipeline scoping, routing, asynchronous settings
probes, Eagle Eye analysis, and the UI boundary. Synthetic settings now isolate the older
Eagle Eye tests from workstation credentials and reception/history network access.

Three EchoMind payload mirrors were synchronized with the supported sync tool. The
global mirror check subsequently found unrelated concurrent drift in the `run_cd`
portable viewer; that file was left untouched. The release parity selection reported
two failures: that unrelated mirror and stale staged templates (`echomind_settings.json`
after this change, plus `patient_table_sort.json`). These are not passing release gates.
The installed application, user settings, staged build output, and live services were
not modified. No release build or deployment was run.

## Remaining verification and rollback

Run the normal release gates on a coherent candidate, then have the operator validate
company and explicitly configured direct mode in the source application. The currently
installed application still uses its existing code and preferences. Source/offscreen
verification does not establish installed-build or live clinical verification.

Rollback is a scoped reversal of this change and its matching payload copies in a future
build, preserving unrelated work. There is no bypass switch that restores implicit
direct routing. The operator may explicitly configure a direct provider through Settings.

Regression guards: `tests/code/echomind/test_explicit_provider_selection.py`.
Canonical reliability item: OPT-55 (Eagle Eye provider/model boundary).
