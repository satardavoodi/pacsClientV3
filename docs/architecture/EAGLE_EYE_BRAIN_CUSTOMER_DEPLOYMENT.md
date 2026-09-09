# Eagle Eye Brain customer deployment

Date: 2026-09-06
Status: Proposed architecture; remote processing is not implemented or deployed.

## Deployment decision

Preferred customer target: standalone Windows segmentation plus a small offline
normative scoring bundle. FreeSurfer and WSL are not required merely to evaluate
normative equations. A compatible, licensed and validated normative model for the
shipping segmentation pipeline is a prerequisite for this target.

If native FreeSurfer measurements remain necessary, use one headless processing
service inside each imaging center. Windows AI-PACS
clients retain the existing series selector, review interface, and PDF export.
Do not require FreeSurfer, WSL, Linux, or a separate FreeSurfer UI on every client.
The service can run on a dedicated Linux machine or a Linux VM on the center's
existing virtualization host. A Linux container on Windows still requires a Linux
kernel through WSL or a VM; Docker alone does not remove this dependency.

The existing Windows SynthSeg volume workflow can remain a separate local option.
It must not silently substitute its measurements into FreeSurfer normative models.
Local WSL installation on the development workstation is a development option,
not the proposed customer installation requirement.

## Lightweight offline reference bundle

Local asset measurements on 2026-09-06: the two CentileBrain subcortical RDS files
total 5,119,597 bytes; the extracted Potvin models.json is 186,200 bytes. These
sizes exclude the scoring interpreter and do not imply coverage of every brain
region. FreeSurfer's multi-gigabyte installer is an image-analysis runtime, not
a required download of normative population data.

The proposed reference payload contains permitted model parameters, residual
distribution information, transformations, covariate definitions, region mappings,
age domains, input estimator/version requirements, provenance, hashes and license
notices. It must not contain the developer's FreeSurfer key, reconstruction tools,
research archives, raw cohort scans or redundant installers.

Evaluate the model locally from measured volumes and required covariates. A
Python evaluator could remove the R runtime dependency only after exact parity
with the publisher's model across supported inputs and boundaries is established.
Do not replace a continuous model with an age-only mean table: sex, head-size,
scanner effects, transformations and predictive distributions may be required.
Reference parameters and normal ranges can then be updated as versioned assets
without downloading a reconstruction engine or contacting a reference website
for every examination.

The current patient volumes use SynthSeg. Matching anatomical names and cm3 units
does not make them equivalent to the native FreeSurfer measurements expected by
the existing reference adapters. There are two offline qualification routes:
obtain a fitted, redistribution-permitted reference validated for the exact
shipping SynthSeg estimator; or develop and externally validate a normative model
or calibration using an adequate healthy cohort processed with that estimator.
Calibration must be evaluated by region, age and relevant acquisition conditions;
a conversion derived from one patient or three reformats is not sufficient.

Keep FreeSurfer on development infrastructure for comparison/validation where
needed. If neither offline route is qualified, retain volume-only reporting or
use the separately designed compatible server workflow; do not expose unsupported
scores as normal/abnormal patient results. Installing FreeSurfer on a developer
machine does not convert existing SynthSeg volumes to native FreeSurfer volumes.

This is a packaging design, not an implemented or clinically qualified offline
reference feature. Model redistribution rights remain separate from runtime size.

## Activation and distribution

FreeSurfer provides a free registration-based license.txt file by email:
https://surfer.nmr.mgh.harvard.edu/registration.html
https://surfer.nmr.mgh.harvard.edu/fswiki/License

The institution supplies its real registration details, intended use and estimated
number of users, and accepts the published terms. An administrator places the
received file on the worker and configures FS_LICENSE. Mount the file read-only
into a container at runtime; do not commit it, print it, or embed a developer's key
in customer installers. Registration has not been submitted and no key has been
obtained for this deployment.

The published FreeSurfer agreement grants rights subject to its conditions,
including retained notices and license text; separately licensed components need
their own review. Do not treat the activation file as blanket permission for all
bundled dependencies or normative models. Register the actual deployment and
resolve redistribution terms before shipping a customer image.

## Proposed processing contract

1. The Windows client selects the source T1 MPRAGE and computes an immutable input
   digest. Patient identity and report demographics remain in local patient storage.
2. A background task submits image geometry, volume data and the minimum scoring
   covariates to an authenticated, explicitly configured center worker. Image data
   remain sensitive even after removing DICOM identity tags. No public website
   endpoint or automatic external upload is part of this proposal.
3. The worker validates its pinned pipeline, license availability, available disk
   and reference compatibility before accepting a job. A durable job identifier
   supports progress, cancellation and reconnect without duplicate reconstruction.
4. The worker executes allowlisted pipelines in isolated job directories with
   bounded resource use. The API must not accept arbitrary shell commands or paths.
5. Results include the source digest, pipeline version, atlas and estimator,
   segmentation geometry, volumes, QC, and per-region reference provenance. Each
   score carries model revision, covariates, applicability and qualification state.
6. The client checks ownership, digest and geometry before attaching results to the
   originating study. Review and PDF generation use the current AI-PACS interface.
   Persist artifacts under the existing patient/study-specific Eagle Eye User Data
   tree; retain Save As for the user's PDF destination.

TLS, per-center authentication, job authorization, bounded retention, cancellation,
partial-transfer recovery and private logs are required implementation properties.
The service must not expose remote Slicer Python execution to workstation clients.
Reference assets should be pinned and stored on the worker with hashes and license
metadata, allowing offline calculations after setup where the model permits them.

## Normative qualification is a separate prerequisite

The present FreeSurfer adapter in
modules/ai_imaging/eagle_eye_brain/freesurfer_reference.py invokes a local WSL
worker. A transport abstraction and server implementation are still needed; the
existing AI server configuration is not evidence that this service already exists.

CentileBrain remains the first candidate within its supported age range. Its
current adapter requires native FreeSurfer measurements and remains an unqualified
research path pending numerical parity, harmonization and site validation. Potvin
and other references must retain their own pipeline and age requirements.

BrainChart's published FAQ explicitly limits available models to non-commercial
use and recommends at least 100 unaffected same-protocol subjects for a site
baseline. Server deployment does not remove either constraint:
https://github.com/brainchart/Lifespan/blob/main/FAQ.md

Do not clamp age, infer missing regional distributions from units or mean volumes,
or enable scores solely because software activation succeeds. Unsupported scores
remain unavailable with a specific reason. The rescaling 50 + 10Z must be labeled
as a standardized score, not a young-adult-reference T-score.

## Implementation and acceptance sequence

First obtain the institution's license and provision one development worker.
Then verify a compatible reconstruction and source-model numerical parity before
adding the remote job transport. Finally exercise the complete Windows workflow:
series selection, submit, reconnect, cancel, QC review, identity-safe attachment,
per-patient persistence and downloadable PDF. Test incorrect input hashes, wrong
study ownership, unavailable workers, missing licenses, unsupported reference
domains and interrupted downloads. Measure runtime and concurrent resource needs
on representative studies before promising customer hardware or turnaround times.

No customer deployment, remote patient transfer, or newly qualified normative
scoring was performed as part of this architecture document.
