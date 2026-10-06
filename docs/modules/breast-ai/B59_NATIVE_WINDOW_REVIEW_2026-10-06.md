# B59: Native signal windowing for the B55 physician review

Date: 2026-10-06. Scope: the protected, standalone 24-case B55 review bundle.
The physician reports reviewing through case 11 and inadequate window/level during
zoom. This is a display correction, not detector/classifier training or acceptance.

## Reproduced cause

B55 preserves native spatial dimensions but supplies 8-bit PNG display values.
Its brightness/contrast sliders apply CSS filters after that conversion. Values
clipped or quantized by the earlier conversion cannot be recovered with CSS.
Native spatial resolution and native signal precision are separate properties.

## Correction contract

Decode the source DICOM signal on authorized infrastructure and preserve its range
in protected assets. Apply supported modality transformations before browser VOI
windowing, respect source polarity and exclude padding. Record unsupported transforms
explicitly. Window/level controls operate on the retained signal, not a PNG filter.
The display framebuffer may be 8-bit; the source must remain available at its original
precision so each window adjustment is recomputed from that source.

Keep the current page path, case ordering, model scores, source boxes, bundle identity,
and feedback validation unchanged. Preserve existing clinical answers and finished
flags. Store native display adjustments separately, with an export path. Snapshot
existing feedback before startup writes and abort on invalid saved state rather than
silently replacing it. Do not refresh the user's open page automatically.

Use per-panel controls and native-pixel zoom; load only the active case. Explicit
unavailability must not masquerade as successful native rendering. No new server,
browser-policy workaround, clinical inference route or workstation viewer change.

## Standards reference

[DICOM PS3.3 C.11.2](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.11.2.html)
defines VOI windowing after modality transformation, including fractional window
values, LINEAR width-one behavior, and presentation/polarity considerations.

## Verification status

Implemented in the existing B55 bundle path. 23/24 cases have all four native panels
(92 assets, approximately 247 MB compressed scripts). Case012 primary and companion
source files no longer resolve in the recorded source folder; a search of the dataset
root and Linux research candidates did not recover them. Retain its old PNG files,
report native display unavailable and do not fabricate a precision upgrade.

All 92 assets match prior image geometry, preserve modality values exactly as Float32,
contain more than 256 signal levels, and pass gzip signal/mask round-trip and transfer
hash checks. 76 assets originate from 12-bit data and 16 from 16-bit data. Photometric
and presentation combinations are MONOCHROME2/IDENTITY (80) and MONOCHROME1/INVERSE (12).
Polarity is applied once to the retained signal; window center is consequently in
polarity-adjusted modality units. Existing vendor VOI LUTs are present in 76 assets.
Manual LINEAR windowing deliberately overrides those LUTs; this is not a reproduction
of manufacturer VOI rendering or a complete general DICOM workstation.

Per-panel window controls, region-auto windowing, native-pixel zoom and separate
display persistence replace CSS brightness/contrast. A single verified migration
backup is created before loading saved feedback. Local/context panels initially use
region-auto settings unless a signal-matching saved setting exists; full/companion
panels retain image-wide defaults. The image-reset and full-range buttons remain.
A single verified migration
backup avoids unbounded storage growth. Saved clinical fields and finished flags are
not changed by display controls. Invalid saved feedback aborts startup without
overwriting it. Settings are bound to signal hashes; assets load on demand and stale
renders are discarded. Explicit stage geometry keeps the reference overlay tied to
the canvas, with live browser geometry acceptance still outstanding.

Primary reran 13 native-window guards and the 14 existing feedback guards: all pass.
The real-asset gzip/Float32/hash/raster guard and JavaScript syntax checks also pass.
The source regression fails on the backed-up old CSS implementation and passes on
the replacement. Synthetic tests include high-bit differences under narrow windows,
fractional centers, width-one threshold, polarity, padding, malformed/quota storage,
single backup and preservation of 11 completed records. Those are synthetic records,
not a claim to have accessed the physician's actual browser storage. A 1MP Node raster
took about 18 ms; this does not establish full browser response time.

Case011 offline numerical rendering was visually inspected: region-auto windowing
reveals texture washed out by the original image-wide preset; a narrower window can
again clip highlights. Clinical visual acceptance is still required. The known
local-file browser-control restriction prevents an automated live GUI pass; no
alternative server or browser-control route was attempted.

Protected evidence: `P/b55-native-window-assets-20261006/receipt.json`,
`transfer-verification.json`, `bundle-copy-verification.json`, and
`P/b55-model-assisted-review-20261006/native-window-test-receipt.json`.
Unchanged hashes were independently checked for cases, provenance, bundle data,
review validation and inference. No training or clinical inference was changed.
