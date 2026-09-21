# EchoMind Demo Center Activation — 2026-09-10

## Outcome

The protected `TEST` record is the owner-approved end-user EchoMind demo. It is now
available in the default source and packaged runtime registries. A restricted
deployment can explicitly remove it with `AIPACS_ENABLE_DEMO_CENTER=0`.

No access code or provider credential is present in this report, source changes, test
fixtures, or command output.

## Root cause

The registry already contained eight encrypted center records, including `TEST` with
the expected display name and one authenticated credential envelope. In-memory checks
confirmed that the owner-supplied access code selected that record and opened the
owner-supplied provider credential. The encrypted record was therefore not stale.

The failure was policy routing in `modules/EchoMind/api_manager.py`: `TEST` was listed
as development-only and removed from both runtime lookup maps unless a deployment
environment variable explicitly enabled it. Normal source runs and shipped packages
did not set that variable, so a correct demo code always failed before any provider
request.

## Minimal correction

- Keep the existing encrypted center registry and envelope format unchanged.
- Classify `TEST` as the owner-approved demo and include it by default.
- Add the explicit restricted-deployment opt-out
  `AIPACS_ENABLE_DEMO_CENTER=0`.
- Continue reading `AIPACS_ALLOW_TEST_CENTER` so existing deployment automation does
  not change behavior unexpectedly.
- Apply the identical runtime change to the EchoMind plugin payload mirror.
- Do not add UI logic, a second credential path, or a plaintext test secret.

The established generator remains the only supported way to add, rotate, or remove a
center record. This fix changes activation policy only.

## Regression boundaries

The new guards prove all of the following:

- the protected demo is present and can authenticate by default;
- the demo reaches the existing company-backend entitlement chokepoint;
- an explicit opt-out removes the demo and makes its code invalid;
- disabling the demo does not alter any non-demo center;
- common false values and the legacy environment flag retain deterministic behavior;
- the packaged registry still contains no plaintext access or provider credentials;
- direct-user provider configuration remains independent of company authorization.

Fail-before evidence was three targeted demo failures: default registry membership,
validation, and entitlement. One adjacent OpenAI assertion was also stale because it
did not supply the endpoint now required by the explicit-provider contract; its
synthetic fixture was corrected without changing production routing.

## Verification

- Focused and adjacent EchoMind/build selection: **197 passed, 15 deselected**.
- Complete `tests/code/echomind` selection: **2,346 passed, 12 skipped,
  15 deselected, 4 pre-existing quarantined xfails**.
- Plugin source/payload parity: **462 of 462 pairs match**.
- Patient-free provider probe: local demo validation succeeded; the configured
  completion endpoint returned HTTP 200 with a non-empty response from the configured
  production model route in 1,899 ms.

The probe contained only a deterministic synthetic instruction. It contained no
patient identifiers, DICOM data, images, reports, or credential output.

## Client and provider responsibility boundary

AES-GCM envelope protection prevents casual plaintext extraction from the packaged
Python payload, but it cannot prevent a user who possesses the authorized demo code
from obtaining service through the running client. That is the intended demo behavior.

Provider-side quota, billing, monitoring, abuse controls, and credential rotation are
managed by GapGPT and are intentionally outside the desktop client's activation
contract. The client neither evaluates nor blocks a valid demo code based on those
concerns. Normal clean-machine installed-build validation remains a human-operated
release gate. The source app was not launched or restarted by this work.

## Rollback

For a restricted deployment, set `AIPACS_ENABLE_DEMO_CENTER=0`. This removes only the
demo record from runtime lookup maps and does not modify the registry, credentials, or
paying-center behavior.
