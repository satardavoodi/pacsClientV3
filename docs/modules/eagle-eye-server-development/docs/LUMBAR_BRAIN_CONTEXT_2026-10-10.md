# Lumbar image stage request context

The active r3 hosted Lumbar path entered runtime.configuration but not
runtime.request_context before calling EagleEyeImageAnalysis. The headless
Manage credential resolver requires current_settings, so this path failed before
provider transport and hosting collapsed the exception into HTTP502. This
deterministic source reproducer matches the observed generic502; historical
responses did not retain the underlying exception, so no raw provider incident
is inferred from them.

The repair enters the existing request context inside the private configuration
context and tags central Brain accounting as eagle_eye. It preserves configured
Brain selection, stage models, canonical prompts, case verification, permissions,
limits and the absence of automatic inference replay.

Verification: route suite15 plus two request-isolation/restoration guards passed17.
Synthetic tests do not constitute a real image/provider or GUI pass. Real Gate1
acceptance is pending the reviewed active revision and the existing ordinary
authenticated Client; no patient evidence belongs in this document.

The urgent immutable candidate must contain this minimal repair, not unrelated
unqualified hardening or in-progress mobile runtime integration. Its scoped
runtime agreement is separate from full latest Developer snapshot parity.
Clinical r3 remains active until controlled transition approval and drain.
Retain old source, command, private settings and exact human grants for rollback.
The existing transition pauses new admission and briefly stops/starts SCM after
stable idle; it must not be described as a zero-downtime update.
