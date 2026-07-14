# Exported images show as BLACK in the radiotherapy planning software — root cause

**Date:** 2026-07-14
**Patient:** PESTE BEIGI ZADE^NARGES (ID 14741), Study `1.3.12.2.1107.5.1.7.112716.30000026071409115427200000003`
**Chain:** AI-PACS export → Limbus Contour (segmentation OK) → RT planning system (**images black**)
**Status:** Root cause **PROVEN**. Fix not yet implemented (needs approval + a server-side change).

---

## 1. Verdict in one line

Every DICOM image AI-PACS stores and exports has its **multi-valued string elements collapsed into a
single value holding a *Python list repr*** — most importantly **(0008,0008) Image Type**, which is a
**Type 1 (mandatory)** element of the CT Image IOD and whose value now contains characters that are
**illegal for VR CS**:

| | (0008,0008) Image Type |
|---|---|
| **Our export** | `"['ORIGINAL', 'PRIMARY', 'AXIAL', 'CT_SOM5 SPI']"` — **one** value, 52 bytes, contains `[` `]` `'` `,` |
| **Working export** | `ORIGINAL\PRIMARY\AXIAL\CT_SOM5 SPI` — **four** values (VM=4), 38 bytes |

PS3.5 restricts VR **CS** to uppercase `A–Z`, `0–9`, space and underscore. `[`, `]`, `'` and `,` are
**not permitted**. Limbus (a tolerant, pydicom-class reader that only needs geometry + pixels) accepts
it and segments correctly. The RT planning system uses a **strict** DICOM parser, cannot accept the
mandatory Image Type, and therefore fails to build a usable image set — the images render black while
the RTSTRUCT (which it parses independently and whose references all resolve) is accepted.

## 2. What is NOT the problem — ruled out by direct comparison

All 123 CT instances exist in **both** exports under the **same SOPInstanceUIDs**. Comparing them:

* **Pixel data — byte-identical.** `PixelData` compares equal for **123/123** instances (524,288 bytes each).
* **Transfer syntax — identical.** Explicit VR Little Endian `1.2.840.10008.1.2.1`, uncompressed, in both.
* **Compression — none, in both.**
* **Rescale — identical.** `RescaleIntercept -8192`, `RescaleSlope 1`, `RescaleType HU`.
* **Windowing — identical.** `WindowCenter 40`, `WindowWidth 400`.
* **Pixel encoding — identical.** 16/16/15, `PixelRepresentation 0`, `MONOCHROME2`, 512×512.
* **Geometry — identical.** `ImagePositionPatient`, `ImageOrientationPatient`, `PixelSpacing`,
  `SliceThickness`, `SliceLocation`, `PatientPosition HFS`.
* **UIDs — preserved.** Study/Series/SOP UIDs are the originals; nothing regenerated.
* **Frame of Reference — identical** (`…300000087`) and matches the RTSTRUCT.
* **DICOMDIR — structurally valid.** 127 records (1 PATIENT / 1 STUDY / 2 SERIES / 123 IMAGE),
  the (0004,1200)/(0004,1400)/(0004,1420) linked-list offsets are correct, a strict reader reaches
  **127/127** records, and **0** referenced files are missing on disk.
* **Folder structure / file naming — conformant** (`PT000000/ST000000/SE00000n/IM00000n`, ≤ 8-char
  File-ID components). Ours is *more* standards-compliant than the working export (`Series0002/<56-char UID>`).
* **RTSTRUCT — sound.** Limbus produced 11 ROIs from our export, referencing 121 images; every
  `ContourImageSequence` reference resolves against our image set.

**None of DICOMDIR, folder structure, pixel data, transfer syntax, compression, windowing, rescale,
UIDs, frame of reference or geometry is the cause.** Do not spend time there.

## 3. The complete set of differences (all 123 instances)

Raw byte-level element walk of our export vs the working export:

| Tag | Element | VR | Ours | Working | Verdict |
|---|---|---|---|---|---|
| (0008,0008) | **Image Type** | CS | list-repr string, VM=1, **illegal CS chars** | `ORIGINAL\PRIMARY\AXIAL\CT_SOM5 SPI`, VM=4 | **DEFECT — Type 1, non-conformant** |
| (0018,1210) | Convolution Kernel | SH | `"['Br40f', '3']"`, VM=1 | `Br40f\3`, VM=2 | DEFECT — same class |
| (0008,0050) | Accession Number | SH | `"0"` (fabricated) | `""` (empty) | DEFECT — Type 2, must stay empty |
| (0002,0016) | Source AE Title | AE | absent | `SANTESOFT` | benign (optional) |

### Proof the diagnosis is complete

Repairing **only** those three elements in our 123 exported files makes the datasets
**byte-identical to the export that works** (`0/123` remaining differences). Nothing else is wrong.

## 4. Where the corruption enters — it is NOT the export code

* The download manager writes the **server's bytes verbatim** — base64-decode → gunzip → `.part` →
  `os.replace` (`modules/download_manager/network/socket_client.py:1725-1747`). It never re-encodes a dataset.
* A scan of the **local store** (`user_data/patients/dicom`, 306 studies) found the corruption in
  **251 of 255** sampled downloaded instances — i.e. it is already present **before any export runs**:
  * (0008,0008) `ImageType` — 251 files, e.g. `"['ORIGINAL', 'PRIMARY']"`
  * (0018,5010) `TransducerData` (ultrasound, LO) — 9 files
* Therefore the defect is **upstream of the workstation**: the AI-PACS **server** (its socket API, or its
  ingestion) writes elements back with `str(MultiValue)` instead of the list itself, collapsing VM to 1.
* **This bug class was already known and band-aided.** The client carries **three** separate
  `_sanitize_specific_character_set()` helpers that undo exactly this corruption for
  `(0008,0005) SpecificCharacterSet` (`PacsClient/pacs/patient_tab/utils/utils.py:75`,
  `modules/viewer/fast/lightweight_2d_pipeline.py:157`, `modules/viewer/fast/decode_service.py:56`) —
  one of them even rewrites the file in place. Nobody realised the same collapse was hitting **every**
  multi-valued string element, including the mandatory `ImageType`.

**Open question for the center (one answer localises the server defect):** how did the other
workstation retrieve these images — via the server's **DICOM Q/R port** or via our **socket API**? If it
used the DICOM port, the corruption is confined to the socket API's DICOM serialisation.

## 5. Required changes

**5.1 Server — the root cause (must fix; everything else is mitigation).**
Never assign `str(value)` back into a DICOM element. Either pass the **original file bytes** through
untouched (safest), or assign the real list (`ds.ImageType = ["ORIGINAL", "PRIMARY", "AXIAL", …]`),
which pydicom encodes as backslash-separated with the correct VM. This silently corrupts **every**
image the PACS has served to date.

**5.2 Client — one normalisation authority at ingestion (immediate protection).**
At the single choke point where a downloaded instance is written (`socket_client.py`, before
`os.replace`), repair a VM-collapsed string element: if a string-VR value matches `^\[.*\]$` and
`ast.literal_eval`s to a list of `str`, assign the list. Then retire the three ad-hoc
`_sanitize_specific_character_set` copies onto that one authority — per the project directive, *route
the decision through the one authority, do not add a fourth bespoke check*. Pixels and UIDs are never
touched.

**5.3 Export — stop fabricating values into the instance files.**
`modules/dicom_media/dicomdir.py:41-48` backfills `AccessionNumber="0"` (and `PatientID="ANONYMOUS"`,
`StudyID="1"`, `Modality="OT"`) into the **datasets that are written out**, because pydicom's
`FileSet.add()` over-strictly demands non-empty values. Accession Number is **Type 2** — an unknown
accession must remain empty. Keep the filler **only inside the DICOMDIR record**, or restore the
original bytes of each instance after `fs.write()`.

**5.4 Guardrails.**
* Export-time conformance check: reject/flag any written element whose value matches a Python list
  repr, and any CS/SH/LO value containing characters outside its repertoire.
* Regression test asserting that no exported element value matches `^\[.*\]$`.

## 6. Unblocking the center today

`tools/diagnostics/repair_dicom_vm_collapse.py` (added with this report) repairs an already-exported
folder in place: restores the true VM of list-repr elements and empties the fabricated Accession
Number. It **never** touches pixel data, UIDs, geometry or the transfer syntax, is **dry-run by
default**, and backs up before writing.

```
python tools\diagnostics\repair_dicom_vm_collapse.py "<export folder>"          # report only
python tools\diagnostics\repair_dicom_vm_collapse.py "<export folder>" --apply  # repair in place
```

Re-run the center's workflow with a repaired export (Limbus → RT planning). Because a repaired export
is byte-identical to the export that already works, the images must display.

## 7. Honest limits of this analysis

The Image Type violation is the **only** DICOM-conformance defect in our export, and removing it (plus
the two cosmetic ones) reproduces the working export exactly — so it is the cause. The precise internal
mechanism by which the RT planning system turns "unparseable Type 1 Image Type" into "black images"
cannot be confirmed without knowing which product it is; that name is still unknown. The decisive
confirmation is the re-run in §6.
