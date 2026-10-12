# Panoramic dental Developer trial

Date: 2026-10-09. Status: source implementation and synthetic model execution;
clinical image review, combined Developer activation and live GUI acceptance pending.

## Workflow and scope

Open a DX/CR/PX/IO study in Eagle Eye, choose **Panoramic Dental AI | Research
Review**, select one study image, load it, confirm a complete panoramic acquisition,
and click **Analyze Panoramic | Eagle Eye Server**. The authenticated server resolves
the exact Study/Series/SOP identity from PACS. The client sends references, not a local
file path or model credentials. A manually selected local DICOM must belong to this
study and already be retrievable from the server's configured PACS source.

The study tab displays a preview and FDI tooth / finding / raw score table. The
display cutoff is not a diagnostic threshold. All 256 scores remain in the retained
result and CSV. Saved results can reopen in the case review panel. No automatic
final diagnosis or clinical report approval is performed.

Eight candidate findings cover 32 permanent FDI teeth: missing tooth, implant,
residual root, crown/bridge, root canal filling, filling, caries and periapical
radiolucency. Scores are not calibrated probabilities. Pulp involvement,
periodontal bone loss, root canal adequacy and implant health are unsupported.
A low score or absent displayed row does not establish normality.

## Model and private worker

Upstream: https://github.com/stmharry/dental-pano-ai at
`86e643c72e14d6a213939f0a414f9374b456bcbe`.
Pinned image: `stmharry/dental-pano-ai@sha256:74a722b3fb62f5b3f7f08820bfac9a21c1ffbe357311f22f9e1e187129204147`.
The original DeepLab/Detectron2 and YOLO inference remains inside its Python 3.11
container. No model dependencies are installed in the workstation environment.
Upstream MIT licensing alone does not resolve weight/dataset/Ultralytics commercial
terms; review these before distribution or clinical/commercial integration.

The Razi server owns a dedicated SSH identity and pinned worker host key in private
host configuration, outside source. The Linux authorized key allows only
`dental-panorama-v1` through a forced command, with forwarding/PTY disabled. The
worker receives a PNG over stdin; DICOM identifiers and headers are excluded.
There is no additional public inference listener. The container has no network,
CPU/memory/PID limits, serialized admission, a bounded timeout and owned-container
cleanup. Container execution is CPU-only for this trial.

Server configuration: `AIPACS_DENTAL_WORKER_CONFIG`, default
`D:/Eagle Eye Server/config/dental-worker.json`. Required fields are
`ssh_executable`, `ssh_config`, `known_hosts`, `private_key`, `destination`.
Never copy keys/configuration into source or mirror host identities.

Preprocessing: one monochrome frame, native modality LUT, padding exclusion,
valid-pixel min/max scaling to uint8 and MONOCHROME1 inversion; no client resizing.
Photometric, identity, payload size and complete finite output are checked. This
preprocessing requires physician evaluation against actual device exports.

## Evidence and remaining gates

- Downloaded model archive SHA-256:
  `2f534e717c66a561bdcc5e89201dfaee28141079ca0941b744ad6e41eca3e50e`.
- Original container smoke: uniform synthetic image, 256 finite scores, about 32 s.
- Razi-to-Linux fixed-command execution: exit 0, 256 rows, 33.209 s, synthetic only.
- Razi adapter path: synthetic DICOM decoding through the actual worker to CSV,
  preview and HTML, 256 rows, 34.423 s. No real patient image was used.
- Related local/Razi suite: 83 passes on each host before the final source-binding
  hardening; the final immutable snapshot carries a fresh verification receipt.
- Protected trial artifacts: `D:/AI-PACS-Research/dental-pano/2026-10-09` on control
  PC, corresponding research folder on Linux, and private Razi staging/config.
- Guard coverage includes exact source admission, unsupported inputs, complete
  output, cross-study rejection, padding, photometric inversion and saved review.
- Canonical source has concurrent identity/education work beyond the currently
  active Razi revision. Stage an immutable reconciled snapshot and recheck all
  hashes; do not silently activate these other changes to test this feature.
- Required: running-source identity after controlled queue/text drain, authenticated
  server scenario, actual panoramic image, local source GUI click-through, saved
  result reopening and physician review. A capability response or synthetic pass
  does not satisfy these gates. No release/build is requested by this trial.
- The local test-control endpoint was unavailable during preflight. A running
  ordinary source Client does not prove it loaded the new files; the human must
  perform a controlled source launch/login for live GUI acceptance after activation.

Tests, receipts, source parity and activation state are separate evidence. Keep
patient images, identifiers, private paths, credentials and logs out of this file.

## Client retry diagnosis and guarded correction

The authenticated TLS8002 capability read succeeded, but the active
education-presenter service did not advertise dental-panorama. The client therefore
stops at its capability guard before submitting an imaging job. No new clinical
job was registered, and no uncertain request was blindly replayed.

The existing usage catalog guard separately failed because the new module was
missing from GROUP_LABELS. Adding its display label fixes that omission: the
combined dental/usage selection passes 31 tests. This correction does not prove a
native settings-crash repair and is not an activation receipt.

Razi's multimedia GUI logged a native access violation in shiboken6 during
AIUsageWidget._render / QTableWidget.setItem. A synthetic probe on that exact
revision completed 30 widget lifecycles and 900 filter changes without reproducing
the crash. The native memory cause and live GUI acceptance remain open.

The Eagle Eye owner is coordinating the combined Developer transition, preserved
payloads/runtime, configuration and official human admission. Administrator
provisioning exists, but user access initialization/grants require qualification.
Do not replace this with device-only authentication or a client/provider fallback.
The local test-control endpoint is unavailable; the exact selected PACS instance
must be recovered through the approved source control path before an actual replay.

Mobile scope: this is a desktop research UI. No Android/iOS dental UI or clinical
support is claimed. The common module/permission addition is explicitly handed to
the Eagle Eye owner for shared API assessment; existing wire schemas are unchanged.
