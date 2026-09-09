# Scout layout review and implementation design

Latest design direction: the center-owned preset and proportional scout section
below supersedes the earlier fixed two-row scout proposal. The first proportional
scout stage is now implemented as documented at the end of this record; center-owned
presets and free-rectangle packing remain design work.

## Scope

Investigation and concrete design for a larger reference image, paper-aware
layouts, and routine MR brain/lumbar presets. No production code changed in this
review. No patient data or physical printer was used. Suggested presets below
are engineering starting points, not clinical acquisition protocols or certified
vendor defaults. The proportion of local examinations they cover was not measured.

## Baseline implementation at the time of review

- `ui/printing_widget.py::_open_layout_dialog` offers row/column presets and custom
  values. `_layout_icon` draws equal boxes. `_update_page_display` subtracts one
  scout/placeholder from every multi-cell page, even if no scout is selected.
- `ui/printing_widget.py` series image selection exposes Set as Scout/Clear Scout.
  `ui/film_preview_widget.py::set_scout_path` rebuilds the current preview but does
  not request controller repagination. That signal boundary must change if scout
  presence or footprint affects image capacity.
- `layout/grid.py::GridLayoutEngine.compute_cells` returns equal rectangles in
  row-major order. It uses 0.02-inch separators, ignores the model's margin/gutter
  values, and fills the image area. The header currently takes 10% of film height.
- `ui/film_preview_widget.py` uses the first cell for scout placement and reference
  line clipping. `render/film_renderer.py` separately uses the same equal grid,
  but draws full-width/full-height grid lines that would cross a merged scout.
- Export is a flattened sheet for both OS printing and DICOM `STANDARD\1,1`.
  A larger scout therefore need not depend on a printer supporting CUSTOM layouts.
- `render/dicom_renderer.py::compute_scout_reference_lines` intersects image planes
  with the scout rectangle using orientation, position and spacing. It does not
  check matching FrameOfReferenceUID. It discards non-intersecting/invalid slices
  without retaining source indices. Preview/export then number the remaining
  lines consecutively and display odd indices only. Missing intersections can
  therefore associate a line with the wrong displayed image number; page-local
  line numbering also differs from the global image numbering on later sheets.

## Shared geometry design

Extend the immutable layout description with a scout footprint (row span and
column span) and a clear no-scout policy. One pure layout resolver must return
the scout rectangle, ordered diagnostic rectangles, image capacity and separator
segments. Preview, export, reference-line clipping, layout thumbnails, pagination,
page deletion and saved layout metadata must consume this same result.

The requested default is top-left scout spanning two rows and one column.
Merge cells at row 0/column 0 and row 1/column 0, including their internal gutter;
do not consume the first two cells of the flattened row-major list. Enumerate
remaining diagnostic cells left-to-right, top-to-bottom. A 4x4 grid then has one
scout and 14 diagnostic images, rather than 15. With no scout, use all 16 cells;
an optional placeholder must be explicit. A 1x1 grid must still show a diagnostic
image. Clamp or reject footprints that leave no diagnostic capacity.

Illustration for four rows and four columns:

```text
+---------+---------+---------+---------+
|         |    1    |    2    |    3    |
|  SCOUT  +---------+---------+---------+
|         |    4    |    5    |    6    |
+---------+---------+---------+---------+
|    7    |    8    |    9    |   10    |
+---------+---------+---------+---------+
|   11    |   12    |   13    |   14    |
+---------+---------+---------+---------+
```

A taller box does not guarantee a larger image: aspect-preserving fitting of a
square image into a narrow box remains width-limited. Offer a two-by-two scout
footprint as an alternative for approximately square reference images, while
retaining two-row/one-column as requested. Do not stretch anatomy or silently
crop image pixels to eliminate whitespace.

## Paper-aware starting points

Calculated from portrait paper dimensions, current 10% header and 0.508-mm gaps.
Square-image occupancy is the fraction of one diagnostic cell occupied by a
fitted square image, not whole-page utilization. Actual pixel spacing/aspect,
selected image count, margins and printer behavior alter the optimum.

| Paper | Rows x columns | Diagnostic cell mm | Square-image occupancy | Images with a two-row scout |
|---|---|---|---|---|
| A3 | 4 x 3 | 98.7 x 94.1 | 95% | 10 |
| A3 | 5 x 4 | 73.9 x 75.2 | 98% | 18 |
| A3 | 4 x 4 | 73.9 x 94.1 | 78% | 14 |
| 14x17 | 4 x 4 | 88.5 x 96.8 | 91% | 14 |
| 14x17 | 5 x 4 | 88.5 x 77.3 | 87% | 18 |

Use A3 4x3 for larger axial images and 5x4 for denser review; 14x17 4x4 is a useful
balanced starting point. These are computed suggestions, not modality standards.
Show page count and actual cell dimensions beside each option. Optimize across
page count, minimum readable image size, aspect fit and final-page emptiness;
minimizing whitespace alone can produce unreadably small images. Keep a common
image scale within a series rather than automatically enlarging the last page.

## Routine MR presets

- Lumbar MR axial: propose a sagittal reference image with the tall scout footprint;
  keep series/sequence boundaries visible and preserve all selected slices.
- Brain MR axial: propose an appropriate sagittal/coronal reference; compare tall
  and two-by-two footprints by reference aspect and resulting page count.
- Begin with manual Brain/Lumbar preset selection plus an editable recommendation.
  Later automatic suggestions can combine Modality, BodyPartExamined, coded
  anatomy, Study/SeriesDescription, ProtocolName and image orientation. Modality
  alone says MR, not brain or lumbar. Text fields are hints, not authoritative
  classification. Missing contrast metadata does not prove a noncontrast exam.
- Scout candidates must belong to the correct study and compatible frame of
  reference and intersect the selected slices. Retain manual choice. A series
  can use oblique planes; do not require exact 90-degree orientation.
- Preserve source identity and displayed numbering in each line result. Do not
  renumber after skipped intersections. Make line density a display policy while
  retaining the correct correspondence. Different series may require different
  scouts; a single document-global scout is insufficient for a complete study
  template with several planes/series.

## Implementation and verification sequence

1. Add pure shared geometry and tests for merged bounds, nonoverlap, area,
   row-major order, valid capacity and 1x1/no-scout behavior.
2. Connect scout/footprint changes to controller repagination; retain image
   identity and viewport edits; update icon, preview, export and metadata.
3. Preserve reference-line source indices/page numbering and validate geometry
   identity, with synthetic orthogonal/oblique/missing-intersection guards.
4. Add paper-aware selectable presets and dimensions/page-count explanations.
5. Add anatomy recommendations separately from clinical sequence selection.
6. Verify A3 and 14x17, all backgrounds, first/middle/last page deletion,
   selection/drag, save/reload and both print paths. Inspect synthetic rendered
   sheets, run focused tests, sync mirrors and verify builder parity. Actual
   film readability still needs source-app and physical-output review.

## Sources and interpretation

[DICOM PS3.3 C.13.3](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.13.3.html)
defines uniform, row/column and custom film arrangements and film sizes; it does
not prescribe one brain or lumbar MR grid. A3 and 14x17 are both recognized sizes.

[Siemens syngo MR DOTGO workbook](https://academy.siemens-healthineers.com/_/en-us/syngo-mr-systems-with-dotgo-turnover-workbook/)
documents selectable layouts, fit-to-segment and reference-image placement. This
supports configurable workflows, not a universal two-cell scout requirement.

[ACR MRI clinical image testing](https://accreditationsupport.acr.org/support/solutions/articles/11000061017-clinical-image-testing-mri-revised-7-29-2026-)
addresses exam quality and accreditation submission. It is not a universal
hardcopy-layout specification or a complete clinical exam protocol. No mandatory
anatomy-specific film grid was established by the sources reviewed here.

## Center-owned presets and proportional scout - follow-up

### Findings in the existing persistence and series boundaries

`core/config.py` stores global printing configuration with ordinary JSON writes.
It has no versioned center-owned preset repository or atomic update contract.
`data/filming_manager.py` and `_save_preview` store flattened PNG pages with patient
metadata, paper and row/column counts. They do not save reconstructible source
roles, series matching rules, placements or editable page groups. Existing PNG
pages cannot reliably be converted into reusable presets.

`data/series_repository.py::get_series_for_study` exposes series description,
modality, series number/UID and count. It does not expose a normalized sequence,
plane, protocol or contrast classification. A bounded background metadata service
is needed for matching; do not add header scans inside the layout dialog handler.
The current flattened image-path list and document-global scout must become a
composition with ordered series groups before saving a complete exam template.

### User workflow inside Layout

Add a Presets section beside Manual Layout. Offer center selection, preset list,
Apply, Save Current Layout as Preset, Update, Duplicate, Rename, Delete and
Import/Export. Normal saving must not require writing rules or regular expressions.

1. The operator arranges the current study and selects Save Current Layout as
   Preset. This captures all chosen series groups and pages, not just a screenshot
   of the visible sheet.
2. The save dialog asks for a name and shows one row per group: example source
   series, editable role (for example Axial T2), plane, required/optional state,
   ordering, page break policy and scout role. Proposed matches are visible.
3. Save the reviewed rules and layout under the explicitly chosen center profile.
   Examples include Brain Routine, Brain With Contrast, Lumbar Routine, and local
   names. Do not infer the center from patient institution fields or silently
   synchronize between workstations.
4. On the next study, Apply resolves each role to candidate series and shows
   Matched, Multiple Candidates, Missing, or Incompatible, with the reason.
   Unmatched extra series remain visible. There is no implicit printing.
5. Unique validated matches can populate the preview immediately. Ambiguous or
   missing required groups need user resolution before that preset is considered
   complete. Never replace a missing sequence with a merely similar series.
6. Let the user apply a mapping once or explicitly save it as a center alias.
   Duplicate gives a new preset; Update changes the selected preset revision.

### What the preset contains

Separate a reusable recipe from a study-specific composition:

- Recipe: schema version, stable preset ID/revision, explicit center profile,
  name, paper/orientation variants, background, header style, ordered series
  roles, matching aliases and restrictions, per-group page policy, image selection
  policy, scout role/size/placement, and fit behavior.
- Composition: study identity, resolved series/frame identities, actual selected
  images and exclusions, concrete page assignments, scout instances, and current
  viewport edits. This is patient-associated state, stored separately if resumable
  editing is added.
- A recipe must not contain source paths, patient fields, Study/Series/SOP UIDs,
  screenshots, exact slice counts, patient-specific crop offsets or the precise
  frame chosen as scout. Sample labels remain transient during save. Persisted
  aliases must be explicitly reviewed because free-text DICOM descriptions can
  contain identifiers.
- Image policy defaults to all images in the matched group. If operators excluded
  images while arranging, Save must expose how that selection generalizes; it
  cannot silently carry the old patient's exclusions into the next examination.
- Scout policy can propose the central geometrically compatible reference frame,
  but must allow replacement and show it before output. Exact old frame numbers
  are not portable. Page count derives from the new study, never the saved count.
- Keep printer connection credentials/queue details outside the recipe. A preset
  may choose a paper variant but must not silently redirect a print destination.

### Matching rules

Resolve only within the active study. Use reviewed center/scanner aliases plus
plane and normalized metadata as independent constraints. Offer exact normalized
aliases first; optional advanced patterns must be bounded and validated. Do not
use raw substring T2 as the whole rule: it can match T2 FLAIR or T2-star sequences.
Do not treat a fixed SeriesNumber as a portable sequence identity.

Support include/exclude aliases, sequence family, plane and required/optional
roles. Derive plane from geometry where available; treat description labels as
hints. Contrast state needs explicit evidence or user classification; absent
contrast metadata is unknown, not proof of a noncontrast exam. Repeated acquisitions,
derived images, several matching stacks and incomplete downloads remain distinct
candidates. Match explanations must be deterministic and reviewable. The design
does not require an external AI service or exporting clinical metadata.

### Scout at 150 percent in both dimensions

The requested default becomes width_scale=1.5 and height_scale=1.5 relative to the
diagnostic tile's nominal rectangle; area becomes 2.25 times the original. Increase
the box in both dimensions while retaining the image aspect ratio. This improves
both elongated and square references; it does not stretch anatomy. The reference
line transform and clipping must use the same resolved image rectangle.

This cannot be implemented safely as a larger pixmap over the existing equal-cell
grid. Use explicit non-overlapping rectangles: reserve a top-left scout region,
then place diagnostic tiles in the remaining regions to its right and below.
The solver may adjust the diagnostic tile size or reduce capacity and repaginate.
Fractional footprints do not always tile a page perfectly; compare candidate
placements with minimum tile size, consistent series scale and page-count limits.
Do not promise zero whitespace or unchanged capacity.

Suggested controls: Scout Size 100%, 125%, 150%, 175%, 200%; 150% default for the
new preset workflow, linked width/height scaling by default. Advanced independent
width/height values may size the box only. Store layout variants for A3 and 14x17;
changing paper reruns geometry, not uniform screenshot scaling. The 1x1/no-scout
fallback and no-overlap constraints remain mandatory. Layout thumbnails must show
the actual enlarged reference and the resulting diagnostic capacity.

### Architecture, storage and staged delivery

Introduce small services for preset models/repository, metadata matching,
composition planning and rectangle geometry; avoid further expanding the widget.
Use schema-versioned per-center storage, atomic replace and revision checks.
Validate imported file size/schema/rules, preserve old revisions on errors, and
never deserialize executable content. Imports must ask how to handle conflicting
preset IDs instead of silently overwriting a center's edits. Explicit export/import
supports transfer between workstations without introducing automatic network sync.

Delivery order:

1. Shared geometry with proportional scout and coherent preview/export/pagination.
2. Ordered series composition and corrected reference identity/numbering.
3. Save/Apply presets with manual role mapping and center aliases.
4. Metadata-assisted suggestions, then paper-specific recommendations.

Guards must include new-patient identity isolation, T2 versus FLAIR/T2-star,
duplicate/missing/optional series, changed slice counts, different scanner aliases,
unknown contrast, incomplete download, scout frame-of-reference mismatch, 150%
geometry at multiple aspects, paper switching, page deletion, save/import version
handling and preview/export equality. Source/mirror parity and synthetic rendering
review apply when implementation begins. Center-specific clinical readability and
real film quality remain distinct from automated geometry tests.

## Implemented first stage: default scout size

Scout boxes now default to 150% of the former regular-cell width and height
when an actual scout is present. Layout offers 100%, 125% and 150%; selection
persists in printing configuration and saved-page metadata. The config default
also provides 150% on first use. A reopened-widget guard verifies persistence.

This first stage uses independent non-overlapping rectangles: one enlarged scout
at the top-left and equal-size diagnostic tiles in the remaining regions. Diagnostic
capacity/order stay unchanged; the diagnostic tiles get smaller (especially in
2x2), and unused page space is not filled by unequal tiles. It is not the future
free-rectangle packing/preset engine. No-scout layouts remain regular. A single row
or column cannot enlarge along the already full-sheet dimension; 1x1 retains the
existing diagnostic-only behavior. All image fitting preserves aspect ratio.

Preview, export, reference clipping and separator positions use the same cells.
Nine new cases cover enlarged geometry across six shapes, persistence/reopen,
preview/export layout parity and absence of a separator through the scout.
Eight cases failed before implementation. A synthetic 14x17 render was visually
inspected: enlarged scout and nonoverlapping cells confirmed; offscreen fonts
rendered as missing glyphs, so this is not a live typography check.

The full printing suite passed 82 tests; the combined printing and plugin-package
parity selection passed 86 tests with 4 release-candidate cases deselected
(6 pre-existing SWIG warnings). All 462 mirror pairs matched. No physical
print or live source UI run occurred. Presets remain a separate next stage.

## Corrected diagnostic box uniformity

The initial weighted-row/column implementation expanded unrelated boxes in the
first row and column. The reported screenshot exposed this defect. Geometry now
returns one independent enlarged scout rectangle and equally sized diagnostic
rectangles to its right and below it. Preview and export draw each actual box's
borders rather than extending first-row/column separators across the sheet.
The configured scout size and diagnostic count/order remain unchanged. Residual
space beside the scout and at the right edge is permitted; this correction does
not claim optimal packing. No anatomy is stretched or implicitly cropped.

The existing geometry guard was strengthened to require equal width and height
for every non-scout box. Three multi-row/multi-column cases failed before the
correction. All focused printing and builder checks now pass: 98 tests, two
candidate-only deselections and six existing SWIG warnings. All 462 mirror pairs
match. A synthetic 4x5 export was visually reviewed for independent scout bounds
and uniform diagnostic boxes; missing offscreen font glyphs remain outside this
geometry validation. No clinical screenshot was copied into repository artifacts.
Live source UI and physical printing remain unverified.
