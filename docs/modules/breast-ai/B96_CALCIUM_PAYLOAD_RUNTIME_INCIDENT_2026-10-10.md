# B96: calcium payload omitted from the active Developer snapshot

Date: 2026-10-10. Stage: Developer deployment repair; unchanged B95 model.

## Evidence and cause

The active Razi source revision was `20261010-ordinary-human-r2`. Its Breast
binding existed, but the adjacent `generated-files/eagle-eye/calcium-b95`
manifest did not. The latest retained Breast envelope reported classification
completed, calcium unavailable with `calcium_bundle_not_installed`, and Breast
incomplete. No calcium subprocess log existed: the dedicated model never started.
The historical staging script listed seven model bindings and omitted calcium.
Private request artifacts remain on their owning host; no patient data is included here.

The retained `20261008-reconciled-developer` calcium bundle and local bundle both
pass the complete 445-file inventory and SHA256 verification. Manifest seal:
`889df3e37ca6e7991e6190fe887f0ad8f16bb34fb7a7a1055959c51209ff10c6`.
No weights, thresholds, preprocessing, annotation or predictions were changed.

## Repair and verification

`tools/eagle_eye/developer_model_bindings.py` defines the eight required Developer
model bindings and validates the pinned calcium manifest, exact inventory and each
file digest. An explicitly selected preserved target is supported for staging;
after junction creation the same preflight must pass on the candidate without
overrides. Host-private environments, settings, credentials and clinical storage
are outside the model inventory. This helper does not prove other models' internal
integrity, perform a service transition, or qualify an installer payload.

Four new regression guards failed before the helper existed and pass afterward.
Combined calcium/dual-branch tests: 42 passed, one skipped (peak equivalence requires
the isolated scipy Breast runtime), exit 0. Local eight-binding preflight and remote
retained calcium verification pass. No live inference or GUI pass is claimed.

The Eagle Eye owner holds activation of its frozen reconciled r1 and will stage a
new immutable candidate with the verified eighth binding. No executing source was
overwritten and no independent service stop was attempted by this workstream.
Source/hash parity, candidate test receipts, running revision identity and end-to-end
client calcium display must be recorded separately before completion/build handoff.

## Scope and remaining gates

This restores an existing server result contract. Android/iOS components and wire,
identity and authentication contracts are unchanged; mobile implementation is not
required for this payload-only correction. Research-only qualification and B93/B95
clinical acceptance and latency limits remain unchanged. No new training or clinical
accuracy estimate is justified by fixing availability. Next action: owner-controlled
candidate staging, drained activation, authenticated Breast replay and client display.
