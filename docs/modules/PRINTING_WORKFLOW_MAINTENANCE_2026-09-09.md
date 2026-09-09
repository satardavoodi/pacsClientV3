# Printing workflow maintenance — 2026-09-09

## Corrected contract

Each generated document belongs to one study. Replacing the patient selection clears its image paths, preview, Scout, viewport history, export cache and queued interaction timer. Viewport values are retained per source path within the document across pagination, layout, header and theme redraws. Deleting selected tiles changes only those selected images, preserves other pages, and recalculates pagination. One-cell layouts display the selected image rather than consuming the only cell for a Scout.

Image/series range changes invalidate the selection; print/save regenerate it before consuming a page. Selection debounce is flushed before actions. Saving reuses a cache only until content changes. Viewing an archived PNG does not replace or silently reprint the active document. Header settings persist and the shared right-block font controls agree.

Both print destinations consume the composed **current page**. DICOM sends the whole sheet as one grayscale Image Box (`STANDARD\1,1`), preserving the header, grid, visible page and image adjustments. Native Qt buffer row alignment is removed before constructing Pixel Data. The Calling AE setting is used, Meta SOP presentation contexts are supported with individual-context fallback, and only printer-returned Image Box identities are updated. Missing/malformed status or Image Boxes fail without N-ACTION. Reference lines share the same integer crop as the Scout pixels and are clipped to the fitted image.

DICOM transport runs in a pool job holding captured settings, pixel bytes and study identity. One job can be in flight per widget. Association timeout is 10 s; DIMSE/network timeouts are 30 s. No retry is automatic because a lost response may follow an accepted print. The result means **accepted submission**, not verified physical output. The OS dialog receives the selected physical page size and retains the driver's final user-controlled settings.

Protocol references: [pynetdicom print example](https://pydicom.github.io/pynetdicom/dev/examples/print.html) and [DICOM Basic Film Box Presentation](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_c.13.3.html). The installed library's `meta_uid` signatures were verified locally.

## Verification

- Before corrections: 22 behavioral failures across staged runs (12, 4, 2, 3, 1); exit 1.
- After corrections: 28 tests in `tests/code/printing`; exit 0. Includes a held synthetic transport to verify non-GUI execution and captured-study completion, and a pixel-level Scout line check. Existing SWIG deprecation warnings remain.
- Tests isolate storage and assert SQLite connection targets. No clinical DICOMs, patient records or printer endpoints were used. A synthetic attachment created by an initial missing attachment-path patch was removed; subsequent tests isolate the attachment root too.
- An initial OS-page-size test constructed native QPrinter and emitted a Windows COM diagnostic despite test exit 0. The test now replaces the device with an in-memory page-layout adapter; final runs do not instantiate a printer or emit that diagnostic.
- Seven changed runtime files were synchronized with the printing payload. Mirror verification: 462/462 pairs match, exit 0. Combined printing, package-registry and source release-parity guards: 44 passed, 2 current-stage tests deselected, exit 0. Current-stage installer checks require a release candidate and were not run. Syntax and focused diff checks pass; no lint pass is claimed.

## Remaining boundaries

This is corrective maintenance, not a UI redesign, a complete asynchronous renderer, or a release. Filesystem enumeration, DICOM decoding, image composition and some storage writes remain synchronous and need measured follow-up under OPT-01. Existing header layout/theme differences, responsive sizing and full-document print selection are not redesigned here. Archived pages remain PNG plus summary metadata rather than editable projects.

Live gates: human-launched source build, two synthetic studies switched repeatedly, page editing/navigation, Scout zoom/pan, A4 and film sizes, portrait/landscape, and actual device conformance for the composed grayscale page. Observe physical output before making any clinical or device-compatibility claim. No application launch, physical print, installer build, commit, push or deployment was performed.

Rollback is limited to this maintenance patch and its corresponding printing payload mirrors; do not reset the dirty worktree or revert unrelated plan/index changes. There is no switch back to the known wrong-study behavior.

## Page background selection - 2026-09-09

The toolbar now provides White, Dark and No background. The global preference is stored as `background_mode` in printing configuration (legacy/invalid values default to dark). Changing it rebuilds the current preview while retaining image adjustments and invalidates saved exports. Filming metadata also records the selected mode.

Dark is neutral black, independent of the application theme. White fills only the sheet outside images; image pixels and their internal backgrounds are not modified. No background preserves alpha in PNG/Qt output, omits gap grid lines and the header separator, and retains the existing header and image annotations. Preview shows transparent space against white paper, not against the blue application theme. White/transparent pages use black header text; dark pages use light text. White mode also leaves inter-image grid space white rather than drawing ink-consuming dark borders.

OS output retains the transparent pixmap, leaving those regions unpainted through Qt. Basic Grayscale DICOM has no alpha: the composed sheet is explicitly flattened on white before conversion, with white Film Box border/empty density for White and No background. The device/driver ultimately controls ink and film density; no measured ink-saving or physical-printer claim is made.

Validation: five new cases (four failed before implementation, one protected existing dark/image behavior) cover pixel preservation, white/transparent gaps including grid areas, persistence, live preview invalidation, packed DICOM white-background bytes and border density. A synthetic three-mode render was visually inspected for background/alpha behavior. Offscreen host font rendering is not a live typography check.

## Mouse multi-selection correction - 2026-09-09

Root cause: selecting a tool did not clear selection, but the next plain press on an already-selected tile unconditionally cleared the group before beginning the adjustment. Selection gestures with Shift/Ctrl also entered the edit path; an empty selection implicitly edited the first tile. Decorative labels could hide the actual tile from hit testing, and secondary mouse buttons were forwarded to Qt's separate selection handling.

All three mouse buttons now use one viewport gesture path. Pressing an already-selected tile retains the group. Clicking an unselected tile selects it alone; Ctrl toggles membership and Shift selects a range. Modifier-selection gestures do not edit pixels. Pan, zoom and window/level operate on the selected group; the existing explicit Sync option still applies to all current-page tiles. Empty selection performs no implicit first-image edit. Tool changes, focus loss and document rebuilds cancel unfinished drags without clearing selection. Hit testing looks through decorative overlays. Default buttons remain left window/level, right zoom, middle pan.

Six behavioral tests failed before the correction. Ten new mouse cases exercise tool switching and ten-image Shift selection, group drag, modifier suppression, empty selection, secondary buttons, ordinary selection replacement and overlay hit testing. Events are delivered through `QApplication.sendEvent` to the real offscreen viewport. Source/device validation remains distinct from these synthetic checks.

## Ctrl sparse selection and stable Shift anchor - 2026-09-09

The initially highlighted image was automatic, so Ctrl-clicking image 1 as the first explicit selection toggled it off. The first explicit click now confirms an automatically selected image; later Ctrl clicks toggle only the clicked image. Ctrl-clicking 1, 3 and 5 selects exactly those images, and group pan changes no intervening images. A normal first click followed by Ctrl additions has the same result. Ctrl-clicking 3 again removes only 3.

Shift keeps the original selection anchor rather than moving it on every Shift click: click 1, Shift-click 10, Shift-click 5 selects 1-5 on the last step. Blank plain-click clears the anchor. Three synthetic Qt event cases cover these paths; two failed before correction and all pass after. Existing group-drag behavior is preserved. Live source UI validation remains pending.
# Sheet removal controls

The bottom action bar offers Delete Selected Images, Delete Current Page, and
Clear All Sheets. Page deletion removes all paths on the displayed sheet even
with no selected tile, repaginates surviving images, and clamps navigation when
the last page is removed. Clearing removes the in-memory composition and scout;
source DICOM files, selected series, and saved filming pages remain intact.
An explicitly emptied composition stays empty on Print or Save until Generate
Preview is used or the series selection changes.

Synthetic offscreen guards cover first/middle/last page removal and both emptying
actions, including navigation, implicit print/save regeneration, and explicit
regeneration. These five cases failed before implementation (missing controls).
Live source-app interaction and physical printing have not been exercised.
