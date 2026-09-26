# Universal white-matter lesion distribution

The brain-lesions worker must compute anatomical distribution for every clinical context, not only MS. The result includes `lesion_topography.regions` with availability, candidate count and volume for periventricular contact, juxtacortical contact, infratentorial, supratentorial and corpus callosum. Categories overlap; an absent anatomical label is unavailable, not zero disease.

MS-selected requests additionally retain `ms_topography` and the existing conditional criteria review. SVD requests retain `svd_spatial`. Other/SVD PDFs include a neutral distribution page; they do not acquire an MS diagnosis. Failed anatomy computation prevents publication of a complete new report. Historical reports without distribution explicitly say it was not assessed.

DICOM identity/age/sex and the physician-selected context follow the existing server-owned path. Artifact envelopes retain the nested distribution and the complete PDF. No source MRI transfer or new endpoint is introduced. SVD nested anatomy is reused for contact assessment to avoid a second SynthSeg run.

Validation: the extended pipeline guard failed in all three contexts before the change. Focused tests cover computation dispatch, context-specific interpretation, cancellation, PDF content and archive transport. Runtime GUI acceptance remains open: the documented control client cannot connect. Production activation is blocked until the affected client result/download workflow is verified. The current Razi service is unchanged; candidate files are staged separately.

Activation: check every owner's queue is drained; compare source baselines; back up scoped files; apply only the reviewed candidate; restart only AIPacsEagleEye; verify authenticated API and real client/PACS/report workflow. Roll back by draining/stopping this service, restoring its scoped backup and restarting. Do not alter PACS, Reception or viewer services.
