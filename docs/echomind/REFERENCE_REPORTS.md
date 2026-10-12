# EchoMind reference comparison

## Contract and implementation (2026-10-07)

`Add Reference` creates a separate structured review of the displayed, potentially edited report. The original report is retained verbatim. The user explicitly selects obstetric ultrasound or echocardiography and confirms the context needed by the reference. Missing context produces an unavailable comparison, not an inferred demographic or measurement.

The client sends `workflow=add_reference`, report text, modality and typed `reference_context` to the existing authenticated Eagle Eye endpoint. The server owns the extraction prompt, provider/model selection, reference registry and calculations. No direct provider route or automatic fallback was added. Existing request history, case authorization, TLS pairing and concurrency controls apply. No additional clinical data is sent to a new provider.

The existing server-selected reporting model extracts measurements with source quotations. Schema, exact quotation, numeric presence and unit presence are checked. Ranges, bounds and duplicate parameter labels are rejected. Extraction is not a complete semantic proof: physician review must confirm that the quoted parameter, number, unit and current examination belong together. The model cannot define reference limits or compute percentiles. Versioned Python equations and intervals produce those values. Unsupported measures remain visible without fabricated references.

The generated review contains comparison context, numbered measurement assessments, reference bands/centiles, source citations, a summary of out-of-band and unassessable measurements, original text and methodological limitations. A reference comparison does not replace an integrated clinical diagnosis.

## Selected numerical references

| Measures | Implemented reference | Required context |
|---|---|---|
| HC, AC, FL, OFD | INTERGROWTH-21st 2014 exact-GA equations | Established GA 14+0 through 40+0; confirmed singleton; explicit mm or cm |
| BPD | Same standard | Same context plus outer-to-outer calipers |
| EFW | INTERGROWTH-21st 2020 standard for Hadlock HC/AC/FL | GA 18+0 through 40+0; confirmed singleton and weight formula; explicit g or kg |
| LVEF, LVEDVI, LVESVI | ASE/EACVI 2015 adult 2D biplane reference intervals | Adult age, recorded sex, confirmed biplane method and explicit units/indexing |
| LVIDd, LVIDs | ASE/EACVI 2015 adult linear dimensions | Adult age, sex, correct end-diastolic/end-systolic measurement and units |
| LAVI | ASE/EACVI 2015 maximum LA volume/BSA interval | Adult age and explicitly indexed LA volume; acquisition method must be reviewed |
| TAPSE, RV S-prime, RV FAC, RV basal diameter, RA area, RV wall thickness | ASE 2025 right-heart Table 1 | Adult age, correct acquisition/parameter association and explicit units |

The fetal reference produces exact calculated centiles and z-scores, displaying P10-P90 as a comparison band, not a diagnosis of normality. Cardiac references supply intervals or one-sided limits; converting these into centiles would invent an unsupported distribution, so no cardiac percentile is generated.

Primary sources:

- [INTERGROWTH current fetal growth tools](https://intergrowth21.com/tools-resources/fetal-growth), including the official calculator and 2020 EFW supplement.
- [Papageorghiou et al., fetal biometry, 2014](https://doi.org/10.1016/S0140-6736(14)61490-2).
- [Stirnemann et al., Hadlock EFW standard, 2020](https://doi.org/10.1002/uog.22000). The current official tools recommend this update over the earlier two-parameter EFW standard.
- [INTERGROWTH October 2025 age-limit policy](https://intergrowth21.com/sites/default/files/2025-10/policy_on_gestational_age_limits_for_fetal_growth_standards_6.pdf). Automatic extrapolation beyond 40+0 is disabled even where older spreadsheet formulas permit it.
- [ASE/EACVI adult chamber quantification, 2015](https://www.asecho.org/wp-content/uploads/2025/04/2015_ChamberQuantificationREV.pdf), Tables 2 and 4.
- [ASE right-heart guideline, 2025](https://www.asecho.org/wp-content/uploads/2026/08/ASE-Right-Heart-Guidelines-May-2025.pdf), Table 1. This supersedes the 2010 right-heart guideline.

These are traceable, society/project-published references with verifiable equations or tables. Inclusion on an ultrasound machine alone was not used as validation. Population applicability and acquisition technique still require local clinical review.

## Other credible references reviewed; not yet automated

- [ISUOG fetal biometry and growth 2019](https://doi.org/10.1002/uog.20272) and [SGA/FGR 2020](https://www.isuog.org/resource/isuog-practice-guidelines-diagnosis-and-management-of-sga-and-fgr.html): growth interpretation requires reliable dating, clinical context, serial growth and relevant Doppler evidence. A low centile alone must not be labeled FGR by this feature.
- CRL dating, umbilical artery Doppler and other fetal Doppler/NT references have distinct gestational domains, acquisition methods and applications. They are not interchangeable with second/third-trimester size centiles. Their equations and independent example checks are not included in this release.
- [ASE diastolic function update 2025](https://www.asecho.org/guideline/left-ventricular-diastolic-function-by-echo/): E/A, e-prime and E/e-prime cannot be converted into a universal single-number normality decision. Rhythm, disease exclusions and the complete algorithm matter. No automated grade is produced.
- [ASE/EACVI aortic stenosis 2017](https://www.asecho.org/guideline/update-of-aortic-valve-stenosis/), [native regurgitation 2017](https://www.asecho.org/guideline/native-valvular-regurgitation-by-echo/) and [prosthetic valve evaluation 2024](https://www.asecho.org/guideline/evaluation-of-prosthetic-valve-function/): valve area, velocities and gradients require integrated interpretation, flow state and native/prosthetic identity. A generic valve length has no universal range. These measures are retained but not automatically graded.
- Pediatric/fetal cardiac z-scores, vendor-dependent strain, aortic indexing and multi-fetal pregnancy standards require separate validated models. Adult intervals and singleton centiles are not substituted for them.

## Verification and release scope

Public official calculator example: GA 24+3, HC 230, AC 210, FL 50, BPD 70, OFD 80 mm. Independent cached spreadsheet z-scores are pinned in tests; all six calculations, including the corresponding Hadlock EFW example, agree within 1e-9. Source downloads and synthetic results are in the ignored `user_data/echomind/agent_artifacts/reference-report-20261007` directory. No patient fixtures are committed.

Final local verification: 260 passed, two frozen-stage checks skipped because no build was produced. All 513 plugin mirror pairs match. The final Razi candidate passed 28 reference/history tests and 22 adjacent case/TLS tests; pip check passed. Four real-provider synthetic cases passed (echo Report, echo Turbo, fetal reference, adult cardiac reference). These are functional examples, not independent clinical accuracy qualification.

Source client GUI acceptance remains separate: Test Control could not connect. The human must start one fresh source client outside clinical reading and sign in. No installed client build or installer was generated. The feature extends existing EchoMind packages; it adds no optional module or feature-flag config family. Client mirrors must be synchronized before the next build.

Deployment uses a new baseline-derived server revision, an explicit file/hash manifest, protected configuration backup, empty-queue checks and automatic SCM rollback on failed post-start acceptance. See the deployment record for the observed activation outcome.
