# B93: Server dual-branch execution and client result delivery

## Problem and intervention
B92 identified an active r4 classifier schema failure. Its corrected sealed Developer
Breast bundle already exists; this session does not change classifier weights or
thresholds. B90/B91 calcium inference and overlays were not connected to the normal
request. This session connects the server adapter to two owned CPU branches and
persists the calcium result with the exact returned detection run on the client.

The server uses a separately sealed, immutable calcium bundle beside Breast. Missing
assets, unsupported DICOMs and execution failures return calcium unavailable, never
negative. FCOS completion is preserved if calcium fails; cancellation cannot publish
a partial result. A tissue failure cancels the calcium process. Both computations
are server-owned, with no client inference fallback. Private diagnostics stay server-side.

The existing authenticated artifact envelope carries the calcium branch inline,
bound to study/series/SOP and source SHA256. The client validates native XY geometry,
point scores and source bindings, then saves a run-specific sidecar. The viewer reads
it off the GUI thread and uses a Qt signal plus generation/run/study guards before
applying the already separate calcium layer. Series/run changes discard old callbacks.
The completion dialog now names classification and calcium status separately.
No invented morphology, AD head, BI-RADS grade or negative result is introduced.

## Verification
Initial new-contract collection failed because the dual-delivery module did not
exist. After implementation, 43 focused tests passed (13 new delivery tests plus
30 B90/B91 guards). Existing classification feature-contract tests remain required.
Local actual-model synthetic run completed both classifier and calcium, then published
and reloaded the calcium data. The smoke harness initially omitted study_uid from its
synthetic publisher records; this was repaired and publication retried on the same
completed synthetic outputs, without retraining or rerunning models. This is not
clinical accuracy or performance evidence. Razi and final tests are tracked in receipts.

## Qualification and outstanding gates
The frozen calcium model retains research_only status, unchanged cutoff and narrow
MONOCHROME2 unsigned-16 identity-rescale contract. B90 native CPU timing and numerical
portability limitations remain; no general DICOM or clinical qualification is claimed.
The source GUI control probe is unavailable. Live GUI acceptance, source parity,
server admission/license readiness and controlled clinical activation are separate
pending gates. Do not overwrite the running r4 service. No installed client was launched.
A matching local/Razi Developer code delta is not an activated service. Existing
concurrent saved-result/reader changes must be reconciled by their owner before a
whole-source build handoff. No training or accuracy improvement is claimed here.

Protected receipts: C:/AI-PACS-Datasets/breast-review/point-review-20261003/b93-dual-delivery-20261008
and D:/Eagle Eye Server/staging/breast-b93-20261008. Clinical data and coordinates
are excluded from repository documentation and fixtures.


## Actual source contract and polarity correction
A header-only audit of the latest retained four-image unavailable-classification
execution found four unsigned-16, single-frame, identity-rescale MONOCHROME1 images
with PixelSpacing. The initial MONOCHROME2-only candidate cannot process them.
Three equivalent-pixel tests (12, 14 and 16 stored bits) failed before the correction
and pass afterward. MONOCHROME1 is inverted once within the declared stored-code
range, with padding excluded; unknown bit alignment, nonidentity rescale, LUT
sequences and incompatible presentation shape remain explicitly unsupported.
MONOCHROME2's previous normalization is unchanged. This is inference preprocessing,
not a diagnostic display implementation or scanner/VOI qualification.
The [DICOM photometric and grayscale contract](https://dicom.nema.org/medical/DICOM/2019a/output/chtml/part03/sect_C.8.11.3.html)
distinguishes polarity from physical density; no CT HU or tissue density is inferred.
The new sealed sibling calcium-b93 keeps the prior calcium bundle intact and records
b93-stored-code-polarity-v1 in results. Weight/peak/edge assets and cutoff are unchanged.

Before this polarity extension, Razi actual-model synthetic delivery passed in
51.985 seconds including validation/publication; both branches completed. Local
55 focused tests now pass including polarity equivalence. New-target actual-image
execution and visual/clinical confirmation of this new contract remain pending.


## Final polarity revision and current native execution
The first native preprocessing attempt exposed a pydicom DataElement/value access
mistake for PixelPaddingValue. A real synthetic pydicom Dataset reproduced the
TypeError before replacing bracket access with get(). The guard passes afterward.
The immutable calcium-b93-r2 bundle uses preprocessing b93-stored-code-polarity-v2.
Its 444-file manifest SHA256 on both hosts is
2427894626ff196f90e48a1dec9aee5f120d578eb3e0aa07474c8a72566e9574.
The preceding two calcium candidate directories remain preserved, not selected.
56 combined guards passed locally and on Razi; three dependency deprecation warnings
remain on Razi. All 517 plugin mirror pairs match. All four retained native sources
pass preprocessing. Native parenchymal classification completed on all four images;
calcium completion/timing is recorded separately when the replay finishes.

The four outstanding cross-host differences were inspected: append-only saved-reader
history/index rows and the corresponding history manifest digest. They are preserved
alongside B93 documentation in the final synchronization delta. No unrelated runtime
code was overwritten and no clinical service was restarted.


The current runner uses a source-mode sealed sibling layout (calcium-b93-r2 beside
Breast), sharing the verified Breast Python runtime and loading isolated sealed
calcium dependencies. Frozen installer packaging/catalog inclusion is not verified
by this source integration and remains a build-input gate. The normal request has
no test-only feature flag; unsupported/missing branch state is explicit.
The native four-image CPU run exceeded five minutes before completion. This is
already outside the owner's approximately one-minute target; do not call its
clinical serving latency acceptable based on the 52-second synthetic smoke.


## Native replay result and transfer acceptance
The retained four-image case finished in 555.5265 seconds on Razi CPU. Both branch
statuses and breast_status completed. Four detector regions yielded four classifier
rows; no lesion row was lost. Calcium returned 50, 55, 134 and 95 support points,
with 4, 5, 8 and 4 air-edge candidates removed. These are support-point counts,
not calcification counts or accuracy/sensitivity measurements. No new physician
reference or label verification was acquired for this replay.
The native result was published with the existing artifact publisher, checksum-
verified and unpacked through the client unpack/relocate functions, then persisted
and reloaded through the new run-bound calcium helper. All four source bindings
were retained. This verifies artifact processing on the server test host, not an
HTTP/client GUI pass or activation of the clinical service. The measured runtime
fails the owner's approximately one-minute preference and requires further work.

The runtime issue is corrected in the tested candidate; the live service still uses
r4. Remaining next actions: source GUI review of these exact outputs and independent
visibility toggles, assessment of the new MONOCHROME1 output, serving-time optimization,
then service admission/license/queue qualification and a controlled immutable rollout.
See [deployment gate](B93_DEPLOYMENT_GATE_2026-10-08.md). Do not call the clinical
rollout complete based on these tests. No new research accuracy gain is claimed.

Final Developer source reconciliation: 8,180 declared files matched by SHA256 on
local and Razi, no missing/different files, and no local drift at verification.
The append-only reader documentation differences were preserved and reconciled.
This closes source parity for this snapshot, not live GUI, packaging or activation.
The source-parity receipt is retained on both hosts; active service remains r4.
