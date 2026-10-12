# Echocardiography reporting

Date: 2026-10-07. Status: source verified and deployed to Razi revision 20261007-echo-reference-r2; fresh-source client GUI acceptance remains pending. Historical source-only test notes below precede activation; see deploy-record-eagle-eye-reference-2026-10-07.md.

## Behavior

The shared report modality catalog now includes `ECHOCARDIOGRAPHY`, making it available to the existing composer modality menu. Template normalization recognizes echo, echocardiogram, TTE and TEE as this category. DICOM `US` remains SONOGRAPHY: ultrasound studies are not automatically classified as cardiac examinations.

Company Report and Turbo requests retain the authenticated Eagle Eye route. The client sends dictation, modality and existing contextual fields; the server constructs the dedicated cardiac prompt. No endpoint, credentials, provider fallback or client-direct company inference route was added. The existing client prompt copy is kept consistent with the server core; this does not certify unrelated legacy routes.

The prompt groups supplied findings by cardiac structure, with one numbered pathological finding per paragraph. It preserves EF and its measurement method, chamber dimensions, valve measurements, Doppler parameters, right ventricular function and supplied pressure estimates. MR is interpreted in cardiac context as mitral regurgitation. TTE, TEE and stress-specific content is included only when supplied. Adult reference ranges must not be applied to pediatric studies.

Missing measurements, normal findings, severity grades and recommendations must not be invented. Supplied templates provide qualitative baseline statements; contradictory statements are removed and numeric placeholders are filled only from dictation. Template example numbers are not patient measurements. Explicitly requested, uniquely defined macros remain supported. An empty pathological section uses “No pathological findings were provided.” rather than asserting a normal examination.

The existing five-key report contract and downstream formatting remain intact. Translation continues through the existing server workflow.

## Source and evidence

- Client: `modules/EchoMind/ai_chat_config.py`, `normal_templates.py`, and `viewer_chat/openai_reporter.py`.
- Server: `modules/ai_imaging/eagle_eye_remote/echomind/service.py` and corresponding `core` files. Migration hashes were refreshed; the upstream manifest retains its historical receipt and records this targeted update separately.
- Guard: `tests/code/echomind/test_echocardiography_reporting.py`. Initial run failed five cases before implementation. Coverage includes modality selection, template aliases, schema acceptance, prompt parity, neutral empty-pathology handling and Report/Turbo server prompt construction.
- Focused EchoMind suite: 171 passed. Builder mirror guard: 1 passed. Mirror verification: 513 pairs matched.
- Transport tests use a mocked provider and synthetic dictation; they are not real network or model-quality acceptance.
- Source Test Control `client.py ping` could not connect (QLocalSocket invalid name). No application restart, authentication automation, installed-server update or release build was performed for this feature.

Organization was informed by the [ASE Guidelines for the Standardization of Adult Echocardiography Reporting](https://www.asecho.org/guideline/guidelines-for-the-standardization-of-adult-echocardiography-reporting/). This prompt is a dictation fidelity and organization contract, not an implementation of diagnostic thresholds or clinical certification.

## Remaining acceptance

Use a fresh human-launched source client outside clinical reading to verify selection and rendering. Deploy the matching server source through the existing deployment procedure, then exercise authenticated Report and Turbo with synthetic cardiac dictation. Review actual model output for measurement fidelity, contradictions, missing information and template handling before clinical use. Source tests alone do not establish those outcomes.
