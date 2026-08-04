# Compressed DICOM transfer-syntax support — review

**Date:** 2026-08-04
**Scope:** Fast Viewer (pydicom), Advanced Viewer (SimpleITK/GDCM → VTK), ingest routes, frozen-build codec bundling
**Status:** Review complete. No code changed. Findings below are all empirically verified, not inferred.

---

## 0. Executive summary

The app's current answer to compressed DICOM is **"normalize at import"** — not "decode in the viewer".
`import_preview_dialog._decompress_file_to_destination()` converts compressed sources to Explicit VR
Little Endian while copying into AI-PACS storage, and its own docstring states the intent:

> *"…so the imported study never depends on runtime codecs again — viewers, the thumbnail pipeline,
> the pixel cache, and FROZEN builds (whose codec set may differ from this machine's) all read plain
> uncompressed files."*

That invariant — **"pixel data on disk is always uncompressed"** — is what both viewers were built
against. Server-side compression breaks it, because **the network download path does not normalize
transfer syntax.** Three independent defects then combine:

| # | Defect | Effect |
|---|---|---|
| **A** | The download manager writes server bytes verbatim; its `is_compressed` flag is a **gzip transport envelope**, not a DICOM transfer syntax | Compressed pixel data lands in patient storage, bypassing the only normalization the app has |
| **B** | The **shipped installer spec never asked for codec entry-point metadata** — it arrived incidentally, unguaranteed and ungated | One PyInstaller upgrade, `--clean` rebuild or ARM64 build away from pylibjpeg registering **0 decoders** and JPEG/J2K/JPEG-LS silently failing |
| **C** | The import-preview capability gate is **import-based**, so it reports "codecs OK" in exactly the build where they don't work — and separately mis-classifies JPEG-LS as unsupported when it does work | Operator is told a study is fine, then the pixels fail |

Defect **A** is the architectural gap. Defect **C** is why it wasn't caught earlier.

> **Correction, recorded deliberately.** An initial static reading of the build scripts concluded the
> shipped installer *was already* shipping without codec metadata and therefore already failing on
> JPEG 2000. **Inspecting the actual staged artifact disproved that** — see §4.1. The metadata is
> present in the current build. The defect is that **nothing guaranteed it**; it was incidental. The
> fix and the gates below stand on their own merits, but the severity of B is "fragile and ungated",
> not "currently broken".

---

## 1. Environment ground truth (dev venv)

`pydicom 2.4.5` (legacy `pixel_data_handlers` API — **not** the 3.x `pydicom.pixels` API).

| Handler | Available | Notes |
|---|---|---|
| Numpy | ✅ | uncompressed only |
| **GDCM** | ❌ | `python-gdcm` not installed |
| Pillow | ✅ | 12.2.0, undeclared (transitive) |
| **JPEG-LS (`pyjpegls`)** | ❌ | not installed |
| pylibjpeg | ✅ | 2.1.0 + plugins `libjpeg` 2.4.0, `openjpeg` 2.5.0, `rle` 2.2.0 |
| RLE (pydicom native) | ✅ | pure-Python, needs no plugin |

**pylibjpeg registers 12 decoders — all via `importlib.metadata` entry points:**

```
1.2.840.10008.1.2.4.50/.51/.57/.70   -> libjpeg:decode_pixel_data   (JPEG baseline/extended/lossless)
1.2.840.10008.1.2.4.80/.81           -> libjpeg:decode_pixel_data   (JPEG-LS)
1.2.840.10008.1.2.4.90/.91           -> openjpeg:decode_pixel_data  (JPEG 2000)
1.2.840.10008.1.2.4.201/.202/.203    -> openjpeg:decode_pixel_data  (HTJ2K)
1.2.840.10008.1.2.5                  -> rle:decode_pixel_data       (RLE)
```

Note JPEG-LS is served by **pylibjpeg-libjpeg**, not by `pyjpegls`/GDCM — which matters for §4.

---

## 2. Decode capability matrix (measured, not assumed)

Run over pydicom's own reference corpus (`_recovery/probe_ts_real.py`) plus a synthetic corpus
(`_recovery/probe_ts_matrix.py`). Both viewer substrates exercised directly.

| Transfer syntax | UID | pydicom (**Fast**) | SimpleITK/GDCM (**Advanced**) |
|---|---|---|---|
| RLE Lossless | `…1.2.5` | ✅ 9/9 | ✅ 9/9 |
| JPEG Baseline (P1) | `…4.50` | ✅ 13/13 | ✅ 13/13 |
| **JPEG Extended (P2/4)** | `…4.51` | ⚠️ **1/2** | ✅ 2/2 |
| JPEG Lossless P14 SV1 | `…4.70` | ✅ 1/1 | ✅ 1/1 |
| JPEG-LS Lossless | `…4.80` | ✅ 1/1 | ✅ 1/1 |
| JPEG 2000 Lossless | `…4.90` | ✅ 3/3 | ✅ 3/3 |
| JPEG 2000 lossy | `…4.91` | ✅ 3/4 † | ✅ 3/4 † |

† The single `.91` failure is `JPEG2000-embedded-sequence-delimiter.dcm`, a deliberately malformed
pydicom fixture. It fails identically on both paths. **Not a capability gap** — reported here only so
it is not mistaken for one later.

### The one real cross-viewer divergence

**12-bit JPEG Extended (`…4.51`) fails in the Fast viewer and succeeds in the Advanced viewer.**

```
JPEG-lossy.dcm  MONOCHROME2 16-bit
  pydicom  -> FAIL  RuntimeError: libjpeg error code '-1038' from Decode()
  Pillow   -> FAIL  "Unsupported JPEG data precision 12"
  SimpleITK-> PASS
```

This matters in practice: **12-bit JPEG is common in CR, DX and mammography.** A study in this syntax
would render in the Advanced viewer and fail in the Fast viewer — exactly the "layout/viewport could
not display the image" signature.

### MONOCHROME1 divergence (pre-existing, not compression-specific)

Verified on identical uncompressed input:

```
MONOCHROME1 source
  pydicom   -> raw values, NOT inverted   (min 64275, max 65535)
  SimpleITK -> inverted to MONOCHROME2    (min -1024, max 236 — identical to the MONOCHROME2 file)
```

GDCM normalizes MONOCHROME1 → MONOCHROME2; pydicom does not. Both viewers must (and appear to)
compensate independently. Flagged because the brief asks about MONOCHROME1/2 — but this predates
compression and is **not** caused by it.

---

## 3. Defect A — ingest routes do not normalize transfer syntax

Storage layout: `{SOURCE_PATH}/{study_uid}/{series_number}/Instance_NNNN.dcm`.

| Route | Entry point | Decompresses? | Evidence |
|---|---|---|---|
| **Folder import (Import Preview)** | `import_preview_dialog.py:674` | **YES** (default on) | `:660` `ds.decompress()`; `:661` `TransferSyntaxUID = ExplicitVRLittleEndian` |
| **Download manager — socket retrieve (production network path)** | `download_manager/network/socket_client.py:1046` | **NO** | `:1359-1361` `if is_compressed: gzip.decompress(...)` — **gzip transport only**; bytes written verbatim `:1375-1377` |
| Legacy gRPC streaming | `network/dicom_downloader.py:123` | **NO** | gzip only `:158-160` |
| gRPC `GetDicomImages` | `network/grpc_client.py:182` | **NO** | raw passthrough `:204-205` |
| `network/multi.py` | `:114` | **PARTIAL — corrupting** | `:141` stamps `ExplicitVRLittleEndian` **without ever calling `ds.decompress()`** → relabels encapsulated data as raw |
| Offline-cloud / cloud-consultation import | `offline_cloud.py:1840` | **NO** | `shutil.copy2` `:2045` |
| Demographics edit (in-place rewrite) | `dicom_demographics_edit.py:446` | **NO** | preserves existing TS |

**The decompression helper `_decompress_file_to_destination` (`import_preview_dialog.py:642`) is
module-private and has exactly one caller.** Repo-wide, only three sites call `ds.decompress()`:
that one, the CD-burner export, and a test. There is no shared decoder to reuse.

Two consequences worth planning for:

- **`multi.py:141` is a latent corruption bug** independent of this rollout.
- **Resume logic keys on file presence + a ≥128-byte size check** (`socket_client.py:1338-1341`), so
  a study already downloaded in compressed form is treated as complete and never re-fetched. **A
  server-side or client-side fix alone will not repair studies already on disk** — those need an
  explicit re-fetch or an on-disk migration pass.
- The client never negotiates transfer syntax: the request is
  `{action: "GetSeriesImages", series_uid, batch_size, batch_index, metadata_only}` (`:1018-1024`).
  There is no field with which the client could ask for uncompressed data.

---

## 4. Defect B — the shipped installer bundles codecs without their entry points

Four build targets exist. **Three handle this correctly. The one that builds the customer installer does not.**

| Build target | Codec modules | Entry-point metadata | Evidence |
|---|---|---|---|
| **MAIN release (shipped)** `build.py` → `builder/build_release.py` → `builder/spec/appA_workstation.spec` | incidental only | ❌ **NONE** | `:144-150` hidden-imports list only `pydicom.*`; **no `copy_metadata` anywhere in the file** |
| Legacy root spec (`AIPacs.spec`) | ✅ | ✅ | `:20-29` `copy_metadata` loop; `:209-217` hidden imports |
| Nuitka release | ✅ | ✅ | `AIPacs_nuitka.spec.py:92-97` `--include-distribution-metadata` |
| Lite Viewer (CD) | ✅ | ✅ | `build_lite_viewer.py:55-61` `CODEC_PACKAGES`; `:394-400` `--copy-metadata` |

The Nuitka spec even carries the warning verbatim — *"Bundling the modules alone leaves pylibjpeg
reporting ZERO decoders, so every JPEG 2000 / JPEG-lossless / RLE image silently fails to decode in
the frozen build"* — but `appA_workstation.spec` never got it.

### Proven, not theorised

`_recovery/probe_entrypoints.py` strips `importlib.metadata.entry_points` while leaving every module
importable — exactly the frozen-build shape:

```
decoders registered (normal):            12
decoders registered (metadata stripped):  0
```

…while the import-based capability check still reports **every codec present**. The modules are
physically in the bundle; only the wiring is missing. This is why the failure is silent.

### 4.1 What the actual staged artifact shows — and why the static conclusion was wrong

Static reading of `appA_workstation.spec` says no metadata is bundled. **The staged build contradicts
that.** Inspecting `builder/output/stage/core` (PyInstaller onedir, `engine/` layout, built
2026-08-02 20:54 by `SPEC_FILE = builder/spec/appA_workstation.spec`, `build_release.py:44`):

```
engine/pylibjpeg-2.1.0.dist-info            entry_points.txt = False   (pylibjpeg itself has none)
engine/pylibjpeg_libjpeg-2.4.0.dist-info    entry_points.txt = True
engine/pylibjpeg_openjpeg-2.5.0.dist-info   entry_points.txt = True
engine/pylibjpeg_rle-2.2.0.dist-info        entry_points.txt = True
engine/_libjpeg.cp313-win_amd64.pyd         3,513,856 bytes
engine/_openjpeg.cp313-win_amd64.pyd          716,288 bytes
engine/rle/rle.cp313-win_amd64.pyd            263,168 bytes
```

Both halves are present, so **the current build decodes compressed DICOM correctly.** Eleven
dist-info directories are in the bundle overall (numpy, cryptography, pydantic, tqdm, …), which is
the fingerprint of PyInstaller 6.20's own hook set rather than anything this repo asked for. No local
hook calls `copy_metadata`, hooks-contrib has **no** pylibjpeg hook, and its `hook-pydicom.py` does
not copy metadata either — so the codec metadata was arriving through an **incidental** path in
PyInstaller 6.20's dependency graph.

That is the real finding: **a clinical decode capability was depending on undocumented, version-specific
behaviour of the build tool, with no declaration and no gate.** It survives today and would vanish
silently on a PyInstaller upgrade, a `--clean` rebuild, or an ARM64 build — where
`setup_arm64_env.ps1:63-75` installs the codec block as `#OPTIONAL`, warns in yellow on failure, and
lets the build proceed. `builder/release_gate.py` had no codec check at all.

**Fix applied:** the spec now declares both halves explicitly, and two gates enforce them (§8).

---

## 5. Defect C — the capability gate is wrong in both directions

`import_preview_dialog._detect_decoder_capabilities()` (`:162-176`) probes by **module import**.
`image_io._missing_decoder_packages()` (`:361-375`) probes by **distribution metadata**. In a frozen
main-app build these two disagree: the first says "all present", the second says "all missing". The
second is correct.

Separately, `_is_transfer_syntax_supported()` (`:179-220`) hard-codes:

```python
if uid in {"…4.80", "…4.81"}:            # JPEG-LS
    ok = bool(caps.get("pyjpegls") or caps.get("gdcm"))
```

Neither `pyjpegls` nor GDCM is installed — yet **JPEG-LS decodes correctly** here via
pylibjpeg-libjpeg (§1). So the gate **refuses JPEG-LS studies that would work**, while
**green-lighting J2K studies that won't** in the frozen build.

---

## 6. Recommended architecture

The brief asks for one shared decoding layer both viewers consume. Two placements are viable and they
are not mutually exclusive:

**Layer 1 — normalize at the storage boundary (extends today's proven design).**
Give the download manager the same normalization the folder import already has, so the
"uncompressed on disk" invariant holds again for every ingest route. Cheapest, lowest-risk, and it
immediately protects every downstream consumer — thumbnails, pixel cache, MPR, Curved MPR, VRT,
dental, stitching, Eagle Eye — with no change to any of them.
*Cost:* decode-on-ingest CPU, and larger local storage (the bandwidth saving is on the wire, which is
what was actually asked for, so this is usually the right trade).

**Layer 2 — a real shared runtime decoder** (`decode_dicom_frames(path) -> NormalizedFrames`)
returning the normalized structure from the brief (pixels, transfer syntax, rows/cols, frames,
spacing, orientation, position, slice spacing, photometric, bit depth, rescale, window, identifiers).
Both viewers consume it; VTK receives already-decoded frames + geometry rather than reading
compressed DICOM itself. This is the durable answer and the one that lets you *keep* pixel data
compressed on disk later if storage matters.

**Sequencing I would recommend:** fix §4 (one file, unblocks the frozen build) → §3 Layer 1 (restores
the invariant, makes compressed studies work end-to-end now) → §6 Layer 2 (consolidates the two
decode substrates and removes the 12-bit-JPEG divergence) → then §5 as a correctness cleanup.

Note Layer 2 alone does **not** fix the Advanced viewer, because SimpleITK reads the file itself; that
path must be changed to accept pre-decoded frames, which is the larger piece of work.

---

## 7. Test matrix still to cover

Verified here: RLE, JPEG Baseline, JPEG Extended, JPEG Lossless, JPEG-LS, J2K lossless/lossy;
MONOCHROME1/2; RGB and YBR_FULL; single- and multi-frame; 8/16/32-bit.

Not yet covered, and named in the brief:
- Mammography specifically (MG + compression + the CC/MLO pairing path)
- Mixed studies — some series compressed, others not, in one study
- Large studies — hundreds of compressed slices (decode cost on the scroll hot path)
- Lossy-vs-lossless pixel fidelity assertions
- End-to-end through the actual viewers (this review tested the decode substrates, not the full
  render path)

---

## 8. What was CHANGED in this pass (scope: build fix + detection only)

Agreed scope: make the codec bundling explicit and gated; flag affected on-disk studies but do not
migrate them. Ingest normalization (§3) and the shared decoder (§6) were **not** implemented.

| File | Change |
|---|---|
| `builder/spec/spec_utils.py` | **NEW** `CODEC_PACKAGES` (single source of truth, import-name → dist-name), `codec_hiddenimports()`, `codec_metadata_datas(copy_metadata)`. A codec missing from the build env is reported and skipped, never fatal — the gate is what stops the build. |
| `builder/spec/appA_workstation.spec` | imports `copy_metadata`; adds `*codec_hiddenimports()` to the hidden-import list and `codec_metadata_datas(copy_metadata)` into `datas` **before** the dedup line. Both halves now declared. |
| `builder/release_gate.py` | **NEW** `check_codec_plugins_available()` (pre-build: the build env registers a decoder for all 7 required transfer syntaxes) and `check_stage_codec_metadata()` (post-stage: the staged tree carries each codec's dist-info **and** its `entry_points.txt`). Wired into `run_pre_build_gate()` / `run_post_stage_gate()`. |
| `tools/diagnostics/scan_compressed_studies.py` | **NEW**, read-only. Reports which locally-stored studies hold compressed pixel data, which are mixed, and the syntaxes involved. `--json` for a machine-readable report. Guard-tested to contain no mutating call. |
| `tests/code/builder/test_codec_bundling.py` | **NEW**, 18 tests. |

**Verification**

- `tests/code/builder/test_codec_bundling.py` — **18 passed**, including a test that reproduces the
  zero-decoder failure by stripping entry points, and two that assert the post-stage gate fails both
  when dist-info is absent *and* when it is present without `entry_points.txt`.
- Live gate run: `codec_plugins_build_env` **PASS** (4 distributions, 12 decoders, all 7 required
  syntaxes); `codec_entrypoint_metadata` **PASS** against the real staged build.
- `appA_workstation.spec` and `spec_utils.py` both parse; `codec_metadata_datas()` returns the 4
  expected dist-info entries under real PyInstaller.
- Regression: `tests/code/system` 322 passed / 4 failed — the 4 are the **documented pre-existing**
  `test_local_search_progressive` failures, in an area this pass did not touch.

### On-disk scan result (real storage, today)

```
6714 instances probed across 499 studies; 5 affected

4 studies  JPEG Lossless, Non-Hierarchical, First-Order Prediction (…1.2.4.70)
1 study    RLE Lossless (…1.2.5)
0 studies  JPEG 2000
```

No JPEG 2000 has reached local storage yet, so the server rollout has not landed here — consistent
with this being caught during testing. The 5 affected studies are single-series each and none is
mixed. Under the current build all 5 decode; they are listed in
`_recovery/compressed_scan.json` for when you decide on migration.

---

## Appendix — probes written for this review

All under `_recovery/` (scratch, git-excluded):

| Script | Purpose |
|---|---|
| `probe_decoders.py` | environment/handler inventory |
| `probe_ts_matrix.py` | synthetic corpus across syntaxes + photometrics, both substrates |
| `probe_ts_real.py` | pydicom reference corpus, both substrates, per-syntax rollup |
| `probe_j2k_detail.py` | isolates the malformed-fixture J2K failure |
| `probe_entrypoints.py` | proves the frozen-build zero-decoder failure mode |
