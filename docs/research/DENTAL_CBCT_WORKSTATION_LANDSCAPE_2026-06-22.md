# Dental CBCT DICOM Workstations — Capabilities, Imaging Science, AI & Market (research report)

**Date:** 2026-06-22
**Purpose:** Inform the AI-PACS dental/medical imaging workstation roadmap — understand what
CBCT radiologic images *are*, what leading dental CBCT workstations *do*, the state of AI
automation, and where AI-PACS has gaps worth closing.
**Method:** Multi-source web research (fan-out across 4 areas), with adversarial cross-checking.
Load-bearing facts are triangulated across independent sources; the exact DICOM SOP Class UIDs
were verified against two independent registries. Uncertain or single-source claims are flagged
inline as ⚠. This is a desk-research synthesis, not clinical or regulatory advice.

---

## Executive summary (read this first)

1. **A dental CBCT workstation is mostly a reconstruction + planning engine, not just a viewer.** The
   high-value features are: arch-curve **panoramic + perpendicular cross-section reconstruction**,
   **implant planning** (implant libraries, nerve-safety margins, guide/STL export), **airway**
   volume analysis, **cephalometric** tracing, **TMJ** corrected views, **segmentation**, and
   **CBCT↔intraoral-scan (STL) fusion**.
2. **The single most important imaging-science fact: CBCT gray values are NOT true Hounsfield Units.**
   They are device-, exposure-, FOV-, and position-dependent and must not be used for absolute
   bone-density decisions. Independently confirmed by the clinical, physics, and DICOM literature.
   [Bone mineral density in CBCT: only a few shades of gray — World J Radiol 2014](https://www.wjgnet.com/1949-8470/full/v6/i8/607.htm); [Are Hounsfield units applicable? — PMC4277442](https://pmc.ncbi.nlm.nih.gov/articles/PMC4277442/)
3. **CBCT voxels are isotropic** (≈0.075–0.4 mm), which is what makes undistorted MPR / panoramic /
   cross-sectional reformation possible. [Scarfe & Farman 2008](https://wp.perfendo.org/wp-content/uploads/2021/02/CBCThowdoesitworkScarfeetal2008.pdf)
4. **In DICOM, dental CBCT is almost always exported as plain CT Image Storage** (one file per slice,
   Modality `CT`, UID `1.2.840.10008.5.1.4.1.1.2`) even though a purpose-built object exists
   (X-Ray 3D Craniofacial, `…13.1.2`). There is **no "CBCT" modality code**; `IO`/`PX` are 2D
   intra-oral/panoramic, not CBCT. Proprietary CD formats + Secondary-Capture misuse are common.
5. **AI auto-segmentation is now the headline differentiator** in shipping products — teeth, jaws,
   inferior alveolar canal, sinus, airway — with public benchmarks (ToothFairy2, MICCAI 2024) and a
   wave of **FDA 510(k) clearances** (Pearl Second Opinion 3D, Overjet CBCT Assist, both 2025).
6. **For AI-PACS:** it already has the imaging spine (DICOM viewer, MPR, a Dental Curve MPR
   panoramic tool, measurements). The biggest dental-specific gaps vs. leading workstations are
   **implant planning + nerve tracing, airway analysis, cephalometric tracing, TMJ corrected
   reconstructions, STL/guide export, scan superimposition, and AI auto-segmentation/reporting.**

---

## Part 1 — Clinical tools & workflows of dental CBCT workstations

### 1.1 Panoramic (OPG) reconstruction from the arch curve
The panoramic reformat is built on a **focal trough/layer** defined by a **dental arch curve** the
user draws (or the software auto-detects) on an axial slice; because enamel is densest, a
maximum-intensity approach along the arch helps define the curve, then **Curved Multi-Planar
Reformation (CMPR)** flattens the volume along it. Trough width/position are adjustable, and the
traced **mandibular canal/nerve can be overlaid** on the pan. [CBCT basics and applications in dentistry — PMC5750833](https://pmc.ncbi.nlm.nih.gov/articles/PMC5750833/); [MPR-Curves in i-Dixel — Dental TI](https://www.dentalti.com/post/a-different-perspective-mpr-curves-in-i-dixel); [Image Interpretation (CE531) — Dentalcare](https://www.dentalcare.com/en-us/ce-courses/ce531/image-interpretation)

### 1.2 Cross-sectional (orthogonal) slices + MPR
After the arch is drawn, the workstation **auto-generates cross-sections perpendicular to the
curve** at adjustable interval/thickness — commonly **~1.0 mm thickness at 1.0–2.0 mm spacing** for
implant work (operator-selectable, not a standard). Standard axial/sagittal/coronal MPR plus
**oblique** and **curved** planar reformation are provided. ⚠ The 1 mm/1–2 mm figures are typical
defaults, not a fixed standard. [The role of CBCT in implant planning — JADA](https://jada.ada.org/article/S0002-8177(14)63741-7/fulltext); [TMJ imaging using CBCT — doctorconebeam (PDF)](https://www.doctorconebeam.com/wp-content/uploads/2023/05/CBCT-and-TMJ.pdf)

### 1.3 Implant planning
The richest module in commercial products: **implant libraries** (Planmeca Romexis advertises models
from **130+ manufacturers**), prosthetic-/crown-driven "top-down" placement, **IAN / mandibular-canal
tracing with safety margins** to the implant apex, **bone-quality assessment at the site** (with the
HU caveat below), and **surgical-guide design exported as STL** for 3D printing (tooth-/mucosa-/bone-
supported; pilot vs fully guided). Guides require **registering the CBCT (DICOM) with an intraoral/
optical scan (STL)** via tooth-surface or fiducial matching. [Romexis 3D implantology — Planmeca](https://www.planmeca.com/dental-software/planmeca-romexis/3d-implantology-software/); [A review of virtual planning software for guided implant surgery — BMC Oral Health 2020](https://bmcoralhealth.biomedcentral.com/articles/10.1186/s12903-020-01208-1)

> ⚠ **Bone density caveat:** Only some planning systems even offer density readouts, and peer-reviewed
> consensus is that **CBCT "HU" are not valid** — use density as a *relative* pattern (cortical vs fine
> trabecular), never an absolute cross-device value. [BMC Oral Health 2020](https://bmcoralhealth.biomedcentral.com/articles/10.1186/s12903-020-01208-1); [Are HU applicable? — PMC4277442](https://pmc.ncbi.nlm.nih.gov/articles/PMC4277442/)

### 1.4 Airway & sinus
Airway tools report **total volume (mm³)** and **minimum cross-sectional area (CSAmin, mm²)** plus
A-P/lateral dimensions — the clinician outlines a region and the software auto-fills and measures the
constriction. Packages: Dolphin, Romexis, Invivo/Anatomage, OnDemand3D, 3Diagnosys. ⚠ **No consensus
measurement protocol** — numbers are not interchangeable across software/landmarks. Maxillary-sinus
assessment supports sinus-lift planning and graft-volume estimation. [Dolphin Treatment Simulation — Dolphin Imaging](https://dolphinimaging.it/products/dolphin-imaging/treatment-simulation/); [Reliability of three airway software packages on CBCT — PMC5606283](https://pmc.ncbi.nlm.nih.gov/articles/PMC5606283/); [CBCT & airway evaluation — Clarity Dental Radiology](https://claritydentalradiology.com/cbct-and-airway-evaluation-what-it-can-tell-you-what-it-cant-and-what-to-do-with-the-information/)

### 1.5 TMJ
Dedicated **"corrected" reconstructions**: sagittal images reconstructed perpendicular to the
condylar long axis and coronal images parallel to it (crosshairs adjusted per condylar angulation),
evaluating condyle/fossa at lateral and medial poles. [Using CBCT to screen and treat TMJ disorders — Dental Product Shopper](https://www.dentalproductshopper.com/article/-using-cbct-to-screen-and-treat-tmj-disorders); [TMJ imaging using CBCT — doctorconebeam](https://www.doctorconebeam.com/wp-content/uploads/2023/05/CBCT-and-TMJ.pdf)

### 1.6 Cephalometric & orthodontic / orthognathic
Workstations **synthesize a 2D lateral cephalogram from the 3D volume** (with magnification factored
in to stay compatible with norm values) and/or do **3D cephalometry**; standard analyses (Roth-Jarabak,
McNamara, etc.). Orthognathic modules simulate **Le Fort, BSSO, genioplasty, double-jaw** with soft-
tissue prediction (⚠ useful for rough preview, not sub-millimeter surgical accuracy). [Dolphin Ceph Tracing](https://dolphinimaging.it/products/dolphin-imaging/ceph-tracing/); [Romexis CMF surgery planning — Planmeca](https://www.planmeca.com/dental-software/planmeca-romexis/cmf-surgery-planning-software/)

### 1.7 Superimposition / scan fusion
Compare scans over time via **voxel-based registration** (automated; aligns gray values in a volume
of interest — less variable than surface-based) on stable references (anterior cranial base, zygomatic
arches). Fuse CBCT with intraoral/optical **STL** to build a "virtual patient." [Voxel- vs surface-based registration after orthognathic surgery — PMC3973674](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3973674/); [Fusion of intra-oral scans in CBCT — PMC7785548](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7785548/)

### 1.8 Endodontics, periodontics, rendering, reporting
Small-FOV/high-resolution CBCT for canal morphology, periapical disease, and **vertical root fracture**
(CBCT sensitivity ~97.5%, specificity ~95%; detection degrades as voxel size grows 0.125→0.4 mm) per
the **AAE/AAOMR joint position statement**. Plus periodontal bone-level measurement, **VRT/MIP volume
rendering**, tooth/bone **segmentation → STL**, linear/angular measurement, annotation, and PDF/structured
reporting. [AAE/AAOMR position statement — AAE](https://www.aae.org/specialty/clinical-resources/cone-beam-computed-tomography/); [Voxel size & VRF detection — PubMed 33337942](https://pubmed.ncbi.nlm.nih.gov/33337942/); [3D modeling from CBCT for periodontal treatment — PMC9503221](https://pmc.ncbi.nlm.nih.gov/articles/PMC9503221/)

---

## Part 2 — CBCT imaging science (understanding the images)

### 2.1 CBCT vs medical CT
CBCT uses a **cone-shaped beam onto a 2D flat-panel detector** and captures the whole FOV in **a
single rotation** (~150–600 planar "basis" projections; ~10–30 s), vs MDCT's fan beam + row detector
stacking slices over many rotations. The price is **much more scatter** and lower contrast resolution,
especially at large FOV. [What is Cone-Beam CT and how does it work? — Scarfe & Farman, Dent Clin North Am 2008](https://wp.perfendo.org/wp-content/uploads/2021/02/CBCThowdoesitworkScarfeetal2008.pdf); [Conebeam CT physical principles — AJNR 2009](https://www.ajnr.org/content/30/6/1088)

### 2.2 Reconstruction (FDK)
Most vendors use **Feldkamp-Davis-Kress (FDK)** filtered backprojection on a circular trajectory. FDK
is exact only at the mid-plane and the circular orbit **fails the Tuy data-sufficiency condition**, so
an **intensity fall-off along the rotation axis** is inherent and grows with cone angle. Iterative and,
increasingly, **deep-learning reconstruction** reduce noise/artifacts (reported PSNR gains >30% for DL
vs 3–13% for FBP/iterative). [Scarfe & Farman 2008](https://wp.perfendo.org/wp-content/uploads/2021/02/CBCThowdoesitworkScarfeetal2008.pdf); [Iterative & AI reconstruction in maxillofacial CBCT — systematic review, PMC12194620](https://pmc.ncbi.nlm.nih.gov/articles/PMC12194620/)

### 2.3 Isotropic voxels & FOV
Voxels are **isotropic**, set by detector pixel size (not slice thickness) — so measurements are equally
valid in all three planes. Typical sizes **~0.075–0.4 mm**. FOV is classified by scan-volume height:
localized ≤5 cm, single-arch 5–7 cm, interarch 7–10 cm, maxillofacial 10–15 cm, craniofacial >15 cm.
**Smaller FOV → less scatter, lower dose, finer effective resolution**; SEDENTEXCT mandates the FOV be
no larger than the region of interest. ⚠ Voxel floor quoted variously as 0.076 vs 0.09 mm (device
rounding). [Scarfe & Farman 2008](https://wp.perfendo.org/wp-content/uploads/2021/02/CBCThowdoesitworkScarfeetal2008.pdf); [FOV selection guide — Voxel Dental](https://learn.voxeldental.com/blog/dental-cone-beam-field-of-view-fov-selection-guide)

### 2.4 Gray values vs Hounsfield Units (the key reading-science point)
**CBCT gray values are not calibrated HU.** A voxel's value depends on scanner model, FOV, exposure,
and even the object's position in the FOV — because of **scatter** (scatter-to-primary ratio 0.4–2.0+
on CBCT vs ~0.01 on diagnostic CT, producing CT-number errors up to ~350 HU), **beam hardening**, the
**exomass/truncation effect** when the object exceeds the FOV, and **no standard calibration**. Pauwels
et al. measured 3.3–21.1% gray-value variability across seven units. The **AAOMR advises against** using
CBCT gray values as a calibrated density measure. ⚠ Per-device/protocol linear GV↔HU fits exist but do
**not generalize** across machines. [Shades of gray — World J Radiol 2014](https://www.wjgnet.com/1949-8470/full/v6/i8/607.htm); [Variability of CBCT grey values — Pauwels, Br J Radiol 2013](https://pubmed.ncbi.nlm.nih.gov/23255537/); [Can gray values be converted to HU? systematic review — PMC8693322](https://pmc.ncbi.nlm.nih.gov/articles/PMC8693322/)

### 2.5 Artifacts
The canonical taxonomy (Scarfe & Farman; Schulze et al. 2011): **beam hardening** (cupping, dark
bands), **scatter/noise**, **metal/streak** (restorations, implants — extreme beam hardening/photon
starvation), **motion** (misregistration), **ring** (detector calibration), and three cone-beam-inherent
types — **partial-volume averaging, undersampling/aliasing, and the cone-beam effect** (peripheral data
deficiency) — plus **exomass/truncation**. Mitigation: small FOV away from metal, head restraint, and
**Metal Artifact Reduction (MAR)**, increasingly deep-learning-based. [Scarfe & Farman 2008](https://wp.perfendo.org/wp-content/uploads/2021/02/CBCThowdoesitworkScarfeetal2008.pdf); [Artefacts in CBCT: a review — Schulze, Dentomaxillofac Radiol 2011](https://www.researchgate.net/publication/51242169_Artefacts_in_cbCT_a_review); [AI metal-artifact reduction in CBCT — PMC11203150](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11203150/)

### 2.6 Dose
CBCT delivers a **higher dose than any other dental exam** but far less than MDCT. Defensible modern
ranges (Ludlow et al. 2015 meta-analysis, ICRP-2007): standard-protocol means **large-FOV 212 µSv,
medium 177 µSv, small 84 µSv** (full reported spread 5–1073 µSv). ⚠ Dose spans 1–2 orders of magnitude
by FOV/protocol and ICRP weighting year — cite ranges, not point values. ALARA/justification is
mandatory; CBCT is complementary, not first-line. [Effective dose of dental CBCT — meta-analysis, PMC4277438](https://pmc.ncbi.nlm.nih.gov/articles/PMC4277438/); [Scarfe & Farman 2008](https://wp.perfendo.org/wp-content/uploads/2021/02/CBCThowdoesitworkScarfeetal2008.pdf)

---

## Part 3 — CBCT in DICOM (storage & interoperability)

### 3.1 What SOP Class / Modality CBCT actually uses
- **Dominant reality: CT Image Storage, one file per slice, Modality `CT`.** SOP Class UID
  **`1.2.840.10008.5.1.4.1.1.2`** (verified against two independent registries). Vendor exports confirm
  it (Carestream "CT (one file per slice)", Romexis "Set of Single Frame DICOM Files", etc.). [CT Image Storage UID — DICOM Library SOP registry](https://www.dicomlibrary.com/dicom/sop/); [Export CBCTs as DICOM — Apteryx/PlanetDDS](https://apteryximaging.planetdds.com/hc/en-us/articles/4407896506267-Export-CBCTs-as-DICOM-Format-in-Common-3rd-Party-Software)
- **Purpose-built but under-adopted:** **X-Ray 3D Craniofacial Image Storage**, UID
  **`1.2.840.10008.5.1.4.1.1.13.1.2`** (DICOM Supplement 116), designed exactly for cone-beam
  reconstructed dental volumes — but poorly supported by third-party viewers, so rarely the default. [Supplement 116: X-Ray 3D Storage — DICOM/NEMA](https://www.dicomstandard.org/News-dir/ftsup/docs/sups/sup116.pdf)
- **Enhanced CT (multiframe)** `…1.1.2.1` exists and *could* hold a volume in one object; rare in dental.
- **No dedicated "CBCT" modality code.** `IO` = intra-oral, `PX` = panoramic (both 2D), `OT` = other.
  A CBCT volume is Modality `CT`. [Modality defined terms (PS3.3 C.7.3.1.1.1) — Innolitics](https://dicom.innolitics.com/ciods/digital-intra-oral-x-ray-image/intra-oral-series/00080060)

### 3.2 Volume geometry & "pseudo-HU"
A volume = N single-frame CT slices sharing a **Frame of Reference UID**, ordered by **Image Position
(Patient)** with **Image Orientation (Patient)** direction cosines; isotropic spacing enables MPR. Pixel
values map to output via **Rescale Slope/Intercept (0028,1053/1052)** with **Pixel Representation
(0028,0103)** — but even when a CBCT file carries these and *looks* like CT, the resulting "HU" are
device-specific and not cross-comparable (some units, e.g. Morita, output bare gray values). [Image Acquisition & Reconstruction (CE531) — Dentalcare](https://www.dentalcare.com/en-us/ce-courses/ce531/image-acquisition-and-reconstruction); [Can gray values be converted to HU? — PMC8693322](https://pmc.ncbi.nlm.nih.gov/articles/PMC8693322/)

### 3.3 Interoperability reality
- **Standards body:** DICOM **WG-22 (Dentistry)**, secretariat = **ADA**; relevant supplements Sup 32
  (digital/intra-oral X-ray), Sup 116 (X-Ray 3D), Sup 205 (Encapsulated STL). [WG-22 Dentistry — DICOM](https://www.dicomstandard.org/activity/wgs/wg-22)
- **Proprietary containers + bundled CD viewers** are common; some native formats aren't DICOM until an
  explicit export/convert step (e.g., the open-source `glx2dicom` converts Sirona GALAXIS → DICOM).
  General viewers (Weasis, RadiAnt, MicroDicom, Horos/OsiriX) fill the gap for standard CT-format exports. [glx2dicom — GitHub gist](https://gist.github.com/maxnikulin/bd9f630466e1cac6aea162279ce5e15e); [Weasis DICOM viewer](https://weasis.org/en/)
- **Secondary-Capture misuse:** derived pano/ceph reformats and screenshots often ship as **SC
  (Modality `OT`)** with burned-in annotation, losing geometry/calibration/Frame-of-Reference. [Secondary Capture SOP Class — SIIM](https://siim.org/otpedia/secondary-capture-sop-class/)
- **STL lives outside DICOM:** guides/models are exchanged as bare STL; DICOM **Encapsulated STL (Sup
  205)** exists but adoption is limited. [DICOM Encapsulation of STL (Sup 205) — DICOM/NEMA](https://www.dicomstandard.org/news/supplements/view/dicom-encapsulation-of-stl-models-for-3d-manufacturing)
- ⚠ **No dedicated "IHE Dental" framework** was found — dental interop runs through ADA SCDI + DICOM
  WG-22; IHE Eye Care is only a *structural* analogy (ophthalmology).

---

## Part 4 — AI / automation state of the art

### 4.1 Segmentation (the headline capability)
- **Multi-structure CBCT segmentation** is now benchmarked publicly by **ToothFairy2 (MICCAI 2024)** —
  the first fully-annotated multi-structure CBCT dataset: **530 volumes (480 public train), 42 classes**
  (maxilla, mandible, individual FDI teeth, inferior alveolar canals, sinuses, pharynx, implants),
  0.3 mm isotropic. The **winning method scaled nnU-Net** to **mean Dice 0.9253**. [ToothFairy2 — Grand Challenge](https://toothfairy2.grand-challenge.org/); [Scaling nnU-Net for CBCT segmentation — MICCAI 2024 / arXiv 2411.17213](https://arxiv.org/pdf/2411.17213)
- **Tooth segmentation** reaches Dice ~90–98% (systematic review). [Tooth automatic segmentation from CBCT — systematic review, PubMed 37148371](https://pubmed.ncbi.nlm.nih.gov/37148371/)

### 4.2 IAN / mandibular canal
Automatic canal segmentation reaches **Dice ~0.95–0.96, ASSD ~0.04 mm** (internal/external test); the
predecessor ToothFairy (MICCAI 2023) was canal-only. Clinically critical for implants, third molars,
orthognathic surgery. [Deep learning mandibular-canal segmentation — BMC Oral Health 2025](https://link.springer.com/article/10.1186/s12903-025-07098-5)

### 4.3 Cephalometric auto-landmarking
3D landmarking now sits at **~1–2 mm mean radial error** (multi-center CBCT: MRE <1.3 mm), most
landmarks within the 2 mm clinical-acceptability threshold; dental landmarks more precise than bone. ⚠
Consensus is human oversight still required. [3D cephalometric landmarking, multi-center CBCT — PLOS One](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0305947)

### 4.4 Pathology detection & reporting
AI for periapical lesions reports **sensitivity 67–97%, specificity 77–99%, AUC 0.75–0.98** — ⚠ highly
variable by dataset/ground-truth. Products auto-generate **structured reports** (Diagnocat: 65+
conditions, color-coded chart) and **CBCT→STL virtual patients** (Relu: mandible/maxilla/teeth/sinus/
airway/canals in ~15 min). [AI in periapical lesion detection — systematic review, PMC12682738](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12682738/); [Diagnocat](https://diagnocat.com/us/); [Relu Creator](https://www.relu.ai/creator)

### 4.5 Regulatory-cleared AI (CBCT-relevant)
- **Pearl — Second Opinion 3D:** FDA 510(k) announced **May 2025**; auto-segments dentition, maxilla,
  mandible, IAN canal + mental foramen, sinus, nasal space, airway. [Pearl press release — BusinessWire](https://www.businesswire.com/news/home/20250527510723/en/Pearl-Becomes-First-Dental-AI-Company-Cleared-for-2D-and-3D-Imaging)
- **Overjet — CBCT Assist:** FDA 510(k) announced **Dec 2025**; perio bone levels, airway CSAmin,
  tooth-to-sinus and tooth-to-canal distances, MPR + 3D rendering. [Overjet press release](https://www.overjet.com/blog/overjet-announces-new-fda-clearance-for-cbct-3d-imaging)
- **Market context:** an AI-mined third-party analysis counts **~44 dental AI 510(k) clearances
  2021–2025**. ⚠ Exact K-numbers for the CBCT 3D products and Diagnocat/Relu's precise clearance scope
  were **not independently verified** against openFDA — confirm before quoting K-numbers. [Dental AI 510(k) clearances 2021–2025 — Innolitics](https://innolitics.com/articles/dental-ai-510k-clearances-2025/)
- Open data to build on: **ToothFairy/ToothFairy2** (CBCT), **3DTeethSeg'22** (1,800 intraoral scans /
  23,999 teeth, FDI labels). [3DTeethSeg — arXiv 2305.18277](https://arxiv.org/abs/2305.18277)

---

## Part 5 — Competitive product landscape + standards/regulatory

### 5.1 Products (notable 3D/CBCT capabilities)
- **Planmeca Romexis** — full implant planning (130+ implant libraries), guide design + STL, 2D & 3D
  cephalometry, CMF surgery planning, airway, and **AI auto-segmentation** (teeth/nerves/jaws/airways/
  sinuses). [Planmeca Romexis 3D implantology](https://www.planmeca.com/dental-software/planmeca-romexis/3d-implantology-software/)
- **Carestream CS Imaging (v8)** — unified 2D/3D viewing, implant/airway tools, exports CBCT as per-slice
  CT DICOM. [Export CBCTs as DICOM — Apteryx](https://apteryximaging.planetdds.com/hc/en-us/articles/4407896506267-Export-CBCTs-as-DICOM-Format-in-Common-3rd-Party-Software)
- **Dolphin Imaging 3D** — orthodontics/orthognathics leader: ceph tracing, surgical simulation (Le
  Fort/BSSO/genioplasty), airway, superimposition. [Dolphin Treatment Simulation](https://dolphinimaging.it/products/dolphin-imaging/treatment-simulation/)
- **Anatomage InVivo / Invivo 7** — implant library, TMJ workup, airway, volume rendering, IOS
  registration; FDA-cleared + CE 2797 (vendor labeling). [Invivo 7 (Anatomage)](https://www.dentalappiran.ir/en/invivo-7/)
- **Blue Sky Plan (Blue Sky Bio)** — ⚠ free to plan but a **per-case fee to export the guide STL**.
- **coDiagnostiX (Dental Wings/Straumann)** — implant planning/guide design; FDA 510(k) **K193301**
  (planning/guide-design intent, not primary diagnostic). [coDiagnostiX K193301 — FDA database]
- **Dentsply Sirona (Sidexis / Galileos Implant), Vatech (Ez3D-i, ~135 structures vendor-claim), J.
  Morita (i-Dixel)** — vendor 3D suites; Morita outputs bare gray values (no HU rescale).
- **Open-source / general:** **3D Slicer** (+ **DentalSegmentator**, peer-reviewed nnU-Net, 5
  structures, validated on 256 scans), **ITK-SNAP**, **Horos/OsiriX** (Horos = free LGPL fork; OsiriX MD
  = FDA-cleared K101342, Class II). ⚠ Free tools are **not regulatory-cleared for diagnosis**.

⚠ Most per-product feature claims are **vendor marketing**; exact 510(k) numbers for many suites were
not retrieved. **"3Diagnosys" appears legacy/renamed** — 3DIEMME's current flagship is **RealGUIDE**.

### 5.2 Standards & regulatory
- **DICOM (NEMA)** for data; **ADA SCDI + DICOM WG-22** for dental specifics (no separate IHE Dental
  domain). **FDA 510(k)** / **CE marking (EU MDR)** for software; a key distinction is **"diagnostic
  use" vs "treatment-planning only"** (e.g., coDiagnostiX is cleared for planning, not primary
  diagnosis). [WG-22 Dentistry — DICOM](https://www.dicomstandard.org/activity/wgs/wg-22); [Dental Cone-beam CT — FDA](https://www.fda.gov/radiation-emitting-products/medical-x-ray-imaging/dental-cone-beam-computed-tomography)

---

## Part 6 — AI-PACS: gap analysis & roadmap suggestions

*Mapping the findings to AI-PACS. "Has" is inferred from the repository (DICOM viewer, FAST + VTK
viewers, `modules/mpr` incl. zeta MPR, the Dental Curve MPR panoramic tool, measurement tools,
segmentation/surface modules, VRT presets, downloads). Confirm against the live product before acting.*

### 6.1 Likely already present (the imaging spine)
- DICOM ingest/viewing of CT-format CBCT (the dominant export), multi-slice volume handling.
- Axial/sagittal/coronal **MPR**, oblique/curved reformation, and a **Dental Curve MPR panoramic +
  cross-section** tool (the feature reviewed earlier this session).
- **Measurements/annotations**, window/level, **VRT/MIP** volume rendering, and some **segmentation /
  surface reconstruction**.

### 6.2 High-value gaps vs leading dental CBCT workstations
Ranked roughly by clinical value ÷ build effort:

1. **TMJ corrected reconstructions** — relatively low effort given existing MPR/oblique reslice; just
   add condylar-axis-aligned sagittal/coronal generation. (Part 1.5)
2. **Cross-section series export & a structured implant/endo report (PDF)** — leverages the existing
   curved-MPR cross-sections + measurements. (Parts 1.2, 1.8)
3. **Airway volume + CSAmin analysis** — bounded segmentation + volumetry; a recognized, shippable
   feature (and now an AI-cleared one). Note the no-consensus-protocol caveat. (Part 1.4)
4. **IAN / mandibular-canal tracing with safety margins**, overlaid on pano + cross-sections —
   clinically critical and a natural extension of the curve-tracing the Dental Curve MPR already does.
   AI auto-tracing is mature (Dice ~0.95). (Parts 1.3, 4.2)
5. **Implant planning module** (implant library, top-down placement, distance-to-canal/sinus) +
   **STL/guide export** and **CBCT↔intraoral-STL registration** — the biggest functional gap; highest
   effort but the core of a dental workstation. (Parts 1.3, 1.7)
6. **Cephalometric tracing** (synthetic 2D ceph from the volume + analyses; later 3D) — large but
   well-defined; AI auto-landmarking (~1–2 mm) is a credible accelerator. (Part 1.6)
7. **Scan superimposition** (voxel-based registration for follow-up). (Part 1.7)
8. **AI auto-segmentation** (teeth/jaw/canal/sinus/airway) — buildable on open models/datasets
   (DentalSegmentator/nnU-Net, ToothFairy2); pairs with #3–#6. (Part 4)

### 6.3 Imaging-science guardrails to bake in (low effort, high correctness value)
- **Never present CBCT gray values as Hounsfield Units / absolute bone density.** Label any density
  readout as *relative gray value, same-machine/protocol only*, with a caveat — this matches AAOMR
  guidance and avoids a real clinical-safety pitfall. (Part 2.4)
- **Handle the DICOM reality:** robustly read per-slice CT-format CBCT (Modality `CT`, Frame of
  Reference, isotropic spacing), tolerate missing/odd Rescale values and Secondary-Capture derived
  images, and consider an **STL import/export** path (guides, IOS fusion) since STL is the lingua franca
  outside DICOM. (Part 3)
- **Surface artifacts in UI:** metal-streak and beam-hardening are expected near restorations/implants;
  don't let auto-windowing or measurement tools mislead near them. (Part 2.5)

### 6.4 Differentiation opportunities
- A clean, fast **open viewer that reads the messy real-world CBCT exports** (proprietary-CD/SC quirks)
  is itself valuable — many practices fight bundled viewers.
- **AI auto-segmentation + structured reporting** is where the market is moving and where open
  models/datasets make a credible in-house build possible — but it carries **regulatory weight** (510(k)/
  CE) if marketed for diagnosis vs planning. Decide "diagnostic" vs "planning-only" positioning early.

---

## Confidence & flagged uncertainties
- **High confidence (triangulated):** CBCT gray-values ≠ HU; isotropic voxels ~0.075–0.4 mm; FOV
  categories; CT Image Storage as the dominant CBCT export (UID dual-verified); FDK + cone-beam
  artifacts; AI segmentation maturity (ToothFairy2).
- **Medium / single-source-or-wide-range (⚠ in text):** exact dose numbers (5–1073 µSv, weighting-
  dependent); 1 mm/1–2 mm slice defaults; per-product marketing feature claims; airway protocol
  variance; X-Ray 3D Craniofacial UID (standard-sourced, one registry).
- **Not independently verified — confirm before quoting:** specific FDA **K-numbers** and exact cleared
  *indications* for Diagnocat, Relu, Overjet CBCT Assist, Pearl Second Opinion 3D; existence/scope of any
  IHE Dental profile (appears not to exist); ADA SCDI Standard No. 1110-1 contents; "3Diagnosys"
  current status (likely renamed RealGUIDE).

---

## Sources (consolidated)

**Imaging science / physics**
- [What is Cone-Beam CT and how does it work? — Scarfe & Farman, Dent Clin North Am 2008 (PDF)](https://wp.perfendo.org/wp-content/uploads/2021/02/CBCThowdoesitworkScarfeetal2008.pdf)
- [Cone beam CT: basics and applications in dentistry — PMC5750833](https://pmc.ncbi.nlm.nih.gov/articles/PMC5750833/)
- [Conebeam CT of the Head and Neck, Part 1: Physical Principles — AJNR 2009](https://www.ajnr.org/content/30/6/1088)
- [Effective dose of dental CBCT — meta-analysis (Ludlow 2015) — PMC4277438](https://pmc.ncbi.nlm.nih.gov/articles/PMC4277438/)
- [Bone mineral density in CBCT: only a few shades of gray — World J Radiol 2014](https://www.wjgnet.com/1949-8470/full/v6/i8/607.htm)
- [CBCT bone quality: are Hounsfield units applicable? — PMC4277442](https://pmc.ncbi.nlm.nih.gov/articles/PMC4277442/)
- [Variability of CBCT grey values — Pauwels, Br J Radiol 2013](https://pubmed.ncbi.nlm.nih.gov/23255537/)
- [Can gray values be converted to HU? systematic review — PMC8693322](https://pmc.ncbi.nlm.nih.gov/articles/PMC8693322/)
- [Iterative & AI reconstruction in maxillofacial CBCT — PMC12194620](https://pmc.ncbi.nlm.nih.gov/articles/PMC12194620/)
- [Artefacts in CBCT: a review — Schulze 2011](https://www.researchgate.net/publication/51242169_Artefacts_in_cbCT_a_review)
- [AI metal-artifact reduction in CBCT — PMC11203150](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11203150/)
- [FOV selection guide — Voxel Dental](https://learn.voxeldental.com/blog/dental-cone-beam-field-of-view-fov-selection-guide)
- [Voxel — Dentalcare CE531](https://www.dentalcare.com/en-us/ce-courses/ce531/voxel)

**Clinical tools & workflows**
- [Image Interpretation (CE531) — Dentalcare](https://www.dentalcare.com/en-us/ce-courses/ce531/image-interpretation)
- [MPR-Curves in i-Dixel — Dental TI](https://www.dentalti.com/post/a-different-perspective-mpr-curves-in-i-dixel)
- [Role of CBCT in implant planning — JADA](https://jada.ada.org/article/S0002-8177(14)63741-7/fulltext)
- [A review of virtual planning software for guided implant surgery — BMC Oral Health 2020](https://bmcoralhealth.biomedcentral.com/articles/10.1186/s12903-020-01208-1)
- [Romexis 3D implantology — Planmeca](https://www.planmeca.com/dental-software/planmeca-romexis/3d-implantology-software/)
- [Reliability of three airway software packages on CBCT — PMC5606283](https://pmc.ncbi.nlm.nih.gov/articles/PMC5606283/)
- [CBCT & airway evaluation — Clarity Dental Radiology](https://claritydentalradiology.com/cbct-and-airway-evaluation-what-it-can-tell-you-what-it-cant-and-what-to-do-with-the-information/)
- [TMJ imaging using CBCT — doctorconebeam (PDF)](https://www.doctorconebeam.com/wp-content/uploads/2023/05/CBCT-and-TMJ.pdf)
- [Using CBCT to screen/treat TMJ disorders — Dental Product Shopper](https://www.dentalproductshopper.com/article/-using-cbct-to-screen-and-treat-tmj-disorders)
- [Dolphin Treatment Simulation](https://dolphinimaging.it/products/dolphin-imaging/treatment-simulation/) · [Dolphin Ceph Tracing](https://dolphinimaging.it/products/dolphin-imaging/ceph-tracing/)
- [Voxel- vs surface-based registration after orthognathic surgery — PMC3973674](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3973674/)
- [Fusion of intra-oral scans in CBCT — PMC7785548](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7785548/)
- [AAE/AAOMR CBCT position statement — AAE](https://www.aae.org/specialty/clinical-resources/cone-beam-computed-tomography/)
- [Voxel size & VRF detection — PubMed 33337942](https://pubmed.ncbi.nlm.nih.gov/33337942/)
- [3D modeling from CBCT for periodontal treatment — PMC9503221](https://pmc.ncbi.nlm.nih.gov/articles/PMC9503221/)

**DICOM / interoperability**
- [CT Image Storage UID & SOP registry — DICOM Library](https://www.dicomlibrary.com/dicom/sop/)
- [Export CBCTs as DICOM in 3rd-party software — Apteryx/PlanetDDS](https://apteryximaging.planetdds.com/hc/en-us/articles/4407896506267-Export-CBCTs-as-DICOM-Format-in-Common-3rd-Party-Software)
- [Supplement 116: X-Ray 3D Storage — DICOM/NEMA](https://www.dicomstandard.org/News-dir/ftsup/docs/sups/sup116.pdf)
- [Modality defined terms (PS3.3) — Innolitics](https://dicom.innolitics.com/ciods/digital-intra-oral-x-ray-image/intra-oral-series/00080060)
- [WG-22 Dentistry — DICOM/NEMA](https://www.dicomstandard.org/activity/wgs/wg-22)
- [Encapsulation of STL (Sup 205) — DICOM/NEMA](https://www.dicomstandard.org/news/supplements/view/dicom-encapsulation-of-stl-models-for-3d-manufacturing)
- [Image Acquisition & Reconstruction (CE531) — Dentalcare](https://www.dentalcare.com/en-us/ce-courses/ce531/image-acquisition-and-reconstruction)
- [Secondary Capture SOP Class — SIIM](https://siim.org/otpedia/secondary-capture-sop-class/)
- [glx2dicom (Sirona GALAXIS → DICOM) — GitHub gist](https://gist.github.com/maxnikulin/bd9f630466e1cac6aea162279ce5e15e)
- [Weasis DICOM viewer](https://weasis.org/en/)
- [Dental Cone-beam CT — FDA](https://www.fda.gov/radiation-emitting-products/medical-x-ray-imaging/dental-cone-beam-computed-tomography)

**AI / automation**
- [ToothFairy2 multi-structure CBCT challenge — Grand Challenge](https://toothfairy2.grand-challenge.org/)
- [Scaling nnU-Net for CBCT segmentation — arXiv 2411.17213](https://arxiv.org/pdf/2411.17213)
- [Tooth automatic segmentation from CBCT — systematic review, PubMed 37148371](https://pubmed.ncbi.nlm.nih.gov/37148371/)
- [Deep learning mandibular-canal segmentation — BMC Oral Health 2025](https://link.springer.com/article/10.1186/s12903-025-07098-5)
- [3D cephalometric landmarking, multi-center CBCT — PLOS One](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0305947)
- [AI in periapical lesion detection — systematic review, PMC12682738](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12682738/)
- [Diagnocat](https://diagnocat.com/us/) · [Relu Creator](https://www.relu.ai/creator)
- [Pearl Second Opinion 3D FDA clearance — BusinessWire](https://www.businesswire.com/news/home/20250527510723/en/Pearl-Becomes-First-Dental-AI-Company-Cleared-for-2D-and-3D-Imaging)
- [Overjet CBCT Assist FDA clearance — Overjet](https://www.overjet.com/blog/overjet-announces-new-fda-clearance-for-cbct-3d-imaging)
- [Dental AI 510(k) clearances 2021–2025 — Innolitics](https://innolitics.com/articles/dental-ai-510k-clearances-2025/)
- [3DTeethSeg'22 — arXiv 2305.18277](https://arxiv.org/abs/2305.18277)

**Products**
- [Planmeca Romexis CMF surgery planning](https://www.planmeca.com/dental-software/planmeca-romexis/cmf-surgery-planning-software/)
- [Invivo 7 (Anatomage)](https://www.dentalappiran.ir/en/invivo-7/)
- [3Shape Implant Studio (DICOM + STL)](https://www.3shape.com/en/software/implant-studio)

*Some sources were read via search-result extracts rather than full-text where pages were paywalled or
CAPTCHA-gated; those facts are corroborated by at least one additional source where possible. See the
inline ⚠ flags for residual uncertainty.*
