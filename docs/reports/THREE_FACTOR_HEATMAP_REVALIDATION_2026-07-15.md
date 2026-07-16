# Three-factor cross-view heatmap — stage-by-stage revalidation (2026-07-15)

Each calculation stage was validated **independently**, across every relevant
configuration, before checking the combination. **35/35 checks passed.**

Method: the pure/numpy modules were driven directly (`geometry`,
`geometric_model`, `candidate_matching`, `cross_view_heatmap`,
`appearance_similarity` — all the real code). The `SearchRegion` wrapper could not
be imported in the offscreen sandbox (a FUSE mount truncation on the largest file),
so it was exercised through a byte-faithful mirror of the host-verified code; the
**real** wrapper is covered natively by the Windows guard suite
(`tests/code/ai_imaging/test_cursor3d_two_stage.py`). Two live clinical cases
(50258, 50274) corroborate the geometric direction.

---

## Stage 1 — geometric localization (GM locus) — 19/19

Validated for **R and L breast × CC→MLO and MLO→CC** (4 configurations):

| Check | Result |
|---|---|
| Valid GM region (`ok`, `method=gm`, `kind=anterior`) | ✓ all 4 |
| Anterior distance **preserved** from the source (nipple→lesion) | ✓ all 4 (49.8 mm in, 49.8 mm out) |
| Locus on the **correct chest-wall side** of the nipple (R = +x, L = −x) | ✓ all 4 |
| Deviation ≈ 0 on the locus | ✓ all 4 |

Interpretation of the landmarks, verified explicitly:

- **Nipple** — shifting the target nipple by +120 px moved the locus by +120 px
  (1:1). The region is measured *from* the nipple, correctly.
- **Pectoralis / MLO angle** — changing the pectoral angle 20°→50° left the
  anterior distance **unchanged** (49.8 mm) but moved the nominal **height** marker
  (−15.6 → −10.7 mm). This is the intended GM property: the angle sets *where along*
  the locus the peak sits, not the anterior placement (which is why GM is robust to
  the angle where SS was fragile).
- **Laterality / orientation** — the chest-wall side flips correctly between R and L.

**Layout 1 vs Layout 2:** the calculation takes **no layout/viewport parameter** —
it operates on the per-view geometry (`ViewData`/nipple/spacing/laterality). Layout
only decides *which viewport renders* the overlay, never the math; a determinism
check confirms identical inputs give an identical region. (The *rendering* into a
given layout cell still needs the live source-build check — VTK is not exercisable
in the sandbox.)

---

## Stage 2 — CC medial-lateral → MLO height — 7/7

The intended relationship (lateral-in-CC → higher-in-MLO, medial → lower), verified
for **R and L**:

| Check | R | L |
|---|---|---|
| Greater CC displacement → greater MLO height (monotonic): 0/25/50 mm → | 0/19.1/38.1 mm ✓ | 0/19.1/38.1 mm ✓ |
| **Central** lesion (on the nipple line) → ~0 bias (the overlap region) | ✓ | ✓ |
| Opposite sides of the nipple line → **opposite-sign** bias | ✓ | ✓ |
| Left/right **symmetric** (mirror lesion → mirror-equal height) | R = −19.1, L = +19.1 ✓ | |

- Far-lateral / far-medial (50 mm) → the strongest bias (38 mm); central →
  ~0 — exactly the "overlap in the middle, strong at the edges" behaviour requested.
- **The absolute direction** (which CC side is *lateral* → which MLO way is *up*)
  depends on the CC display convention; it was confirmed **empirically on the two
  live cases** (50258, 50274 — both had the true detection on the anatomically
  correct side of the nominal). The structural properties above are convention-free.
- **It stays a WIDE, SOFT prior** (σ = 35 mm): 50258 showed the height is only ~34 %
  determined by CC — so factor 2 biases the peak, never pins it (already guard-tested
  separately).

---

## Stage 3 — density / histogram / pattern similarity — 4/4

Source box analysed for its intensity signature over a shared p1–p99 range:

| Check | Result |
|---|---|
| Source box density + histogram computed | ✓ |
| **Dense** source (microcalc-like) matches a dense candidate, rejects a fatty one | dense 0.99, fatty 0.00 ✓ |
| **Iso-dense** candidate (same signature) scores high | 0.99 ✓ |
| **Texture** — a heterogeneous source matches a heterogeneous candidate over a flat one | 0.99 > 0.47 ✓ |
| No pixels → **neutral 0.5**, never a penalty | ✓ (separate guard) |

Density (mean level), histogram (distribution shape), and texture (variance/
heterogeneity) are all reflected: the score combines histogram intersection (shape)
with mean agreement (density level).

---

## Stage 4 — final combination — 5/5

| Check | Result |
|---|---|
| `combine` renormalises over available factors (uniform-0.6 → 0.6 with **and** without appearance) | ✓ |
| Appearance genuinely participates (low appearance lowers the score) | ✓ |
| Candidate scoring: factor 3 **excluded** without pixels, **included** with | ✓ |
| Factors 1 + 2 always present in the score | ✓ |
| The dense heatmap field carries the geometric + height components and a peak | ✓ |

The final heatmap = `combine(geometric, height, appearance)` over the target region
— bright where all three agree, fading along the uncertain height direction.

---

## Status of each stage (live)

- **Stage 1 (GM)** — live default, validated in sandbox + on 50258/50274.
- **Stage 2 (height)** — live in scoring, validated.
- **Stage 3 (appearance)** — flag-gated `AIPACS_CURSOR3D_APPEARANCE=1` (reads pixels
  on the GUI thread; move off-thread before default-on).
- **Visual heatmap render** — flag-gated `AIPACS_CURSOR3D_HEATMAP=1`; **NEEDS LIVE
  SOURCE-BUILD VERIFY** (VTK). Confirmed rendering on 50274 (the green/red band).

## Reproduce

Sandbox (real modules + faithful wrapper): the two scripts under `/tmp/reval`.
Native (real wrapper): `tests/code/ai_imaging/test_cursor3d_two_stage.py` — the new
`test_factor1_gm_valid_across_all_configurations` (parametrised R/L × CC↔MLO),
`test_factor2_monotonic_symmetric_and_central_overlap`, `test_factor3_texture_similarity`,
`test_layout_independence_calc_is_deterministic`, run with:

    .venv\Scripts\python.exe -m pytest tests\code\ai_imaging\test_cursor3d_two_stage.py -p no:debugging -q
