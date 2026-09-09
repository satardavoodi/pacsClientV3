# Print transport and image fidelity audit - 2026-09-09

## Outcome and evidence boundary

The current implementation has a recognizable DICOM Print Management workflow
and uses Qt's native Windows print integration, but cannot yet be described as
fully conformant or image-fidelity verified. This pass is an audit: production
behavior was not changed. Earlier uncommitted printing changes were preserved.
No clinical images, live database, printer queue contents, or device submission
were used. No DICOM association was made to a configured printer.

Runtime measured: pydicom 2.4.5, PySide6 6.10.2, pynetdicom 2.1.0. Windows Spooler
was Running/Automatic. Read-only WMI inventory found 13 queues across 12 driver
names, including physical-device and virtual drivers. Inventory does not prove
device reachability, paper availability, negotiated resolution, or output quality.

## Confirmed defects

| Priority | Finding and evidence | Affected seam |
|---|---|---|
| High | Window/level output is normalized again to the minimum/maximum of the current image or crop. Synthetic values 100/110/120 at width 400, center 200 become 0/127/255 instead of approximately 64/70/77 under DICOM LINEAR. Uniform images become black. This can defeat manual settings and change contrast after cropping. | `render/dicom_renderer.py::_apply_window_level`, `_normalize_to_uint8`, `load_dicom_as_pixmap`; both print routes and preview |
| High | Native YBR_FULL is passed directly to QImage RGB888. A synthetic YBR red pixel 76/85/255 rendered as RGB 76/85/255; installed pydicom's color converter gives 254/0/0. | `render/dicom_renderer.py::load_dicom_as_pixmap`; color source images in both routes |
| High | Only Explicit VR Little Endian is offered for every presentation context. The default Implicit VR Little Endian is absent; the PS3.5 default-syntax requirement applies to this generated uncompressed payload. Mock AE capture confirmed absence. | `printers/dicom_printer.py::send_print_job` |
| High | Windows handler returns True even when QPainter.end() returns False. A synthetic accepted-dialog/active-painter probe reproduced false success. The caller can then mark the study printed. | `printers/os_printer.py::print_film`, UI print status |
| Medium | Every nonzero DICOM status is reduced to failure, and worker exceptions become a boolean. B605 warning was reproduced as False. Operation, warning meaning, and acceptance certainty are lost. Warning-specific policy is needed; cropping warnings must not simply be accepted as ordinary success. | DICOM handler and worker |
| Medium | RGB branch returns before `_apply_viewport`, so color pan/zoom state is not applied by the image renderer. | `render/dicom_renderer.py::load_dicom_as_pixmap` |

## Compatibility and quality gaps from code inspection

- DICOM output is one flattened current sheet, `STANDARD\1,1`, unsigned 8-bit
  MONOCHROME2. Header and edits are baked into the raster. Basic Color Print and
  12-bit grayscale output are not implemented. Eight-bit grayscale is a valid
  capability, not itself a standards violation; it cannot preserve color or
  provide the tonal precision of a supported higher-bit-depth path.
- Both routes render at fixed 300 DPI before printer selection/dialog completion.
  A 14x17-inch sheet is 4200x5100 pixels (21.42 million pixels); resampling this
  raster to a higher driver resolution does not recover source detail. There is
  no universal 300-DPI requirement for DICOM printers. Device conformance and
  supported matrix/film combinations must inform the profile. Multiple full-size
  color/gray buffers are allocated during preparation.
- Windows uses QPrinter HighResolution, selected queue, custom physical page size,
  native QPrintDialog, aspect-preserving scaling, and centering in the paintable
  area. Driver settings can change the paper/orientation/resolution after the
  raster was composed. The full sheet is fitted into printable margins, so this
  is not a calibrated true-size output path. Page-size acceptance and final
  printer error/abort state are not checked.
- Local color/duplex/tray/copies are delegated to the native dialog and driver.
  There is no application-level ICC/GSDF calibration contract. Correct digital
  RGB values do not independently establish paper/film color or density accuracy.
- DICOM settings expose address, port, AE titles, orientation, medium, destination,
  and priority. Port input is bounded; AE strings lack explicit format/length
  validation. `BIN_i` is exposed literally rather than a configured bin number.
  No device profile constrains supported media, film sizes, or optional attributes.
- REPLICATE magnification and MEDIUM smoothing are hardcoded defaults; smoothing
  is sent unconditionally. Support for optional smoothing, density and trim values
  must be matched to each printer's conformance statement. No resolution choice,
  Presentation LUT negotiation, or printer-specific ConfigurationInformation is
  exposed in the current UI.
- No Printer N-GET readiness/status probe, useful N-EVENT-REPORT handling, or Print
  Job completion tracking is implemented. Association/N-ACTION acceptance is not
  physical printing. Automatic retry is correctly absent.
- Source display transformations also omit explicit palette-color handling,
  Modality LUT Sequence, VOI LUT Sequence/function selection, and physical pixel
  aspect correction in the rendered aspect ratio. Multiframe input selects frame
  zero rather than exposing a frame-aware print selection. These are inspection
  findings, not an exhaustive modality/codec validation.
- DICOM network submission runs in a QRunnable with ACSE/DIMSE/network timeouts
  and association release in finally. However, export/decode, grayscale conversion,
  and local driver painting remain reachable synchronously from the GUI handler.
  Large sheets or slow drivers can stall the interface; no latency benchmark was
  performed in this audit.

## Existing behavior verified

The focused printing and adjacent builder suite passed: **67 passed, 2 deselected,
6 existing SWIG deprecation warnings**, pytest process exit code 0. The excluded
`current_stage` cases require a release candidate; this was not a release run.
All **462** source/payload mirror pairs matched. Existing tests cover page
composition, transparent-gap flattening, packed grayscale scanlines, physical
page-size forwarding, meta-context use, missing image-box rejection, and empty
status handling. Those passes do not cover away the confirmed defects above.

Additional in-memory probes, process exit code 0, reproduced the window mapping,
YBR color error, absent default transfer syntax, B605 classification, and false
Windows success. Transport and painter were mocked; no paper or film was used.

## Recommended correction order and remaining device checks

1. Correct shared grayscale/color transforms with synthetic pixel-level guards.
2. Correct transfer negotiation, validate settings/payloads, and return structured
   operation/status results without automatic retransmission.
3. Honor Windows end/abort/error results and reconcile final dialog page settings
   with image rendering, orientation, margins, and resolution policy.
4. Introduce validated per-device profiles for the required color/grayscale,
   media, sizes, magnification and density features; avoid unsupported options.
5. Test a synthetic target on each actual DICOM model and each relevant Windows
   driver: grayscale ramps, color patches where supported, fine lines, header,
   orientation, margins, aspect ratio, cancellation, offline/paper-out states and
   queue acceptance versus physical completion. Obtain the printer model/firmware
   conformance statement before claiming model-specific DICOM interoperability.

## Primary references

- [DICOM PS3.5 10.1, default transfer syntax](https://dicom.nema.org/medical/dicom/current/output/chtml/part05/chapter_10.html)
- [DICOM PS3.4 H.4.2.2, Film Box attributes and warnings](https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_H.4.2.2.html)
- [DICOM PS3.4 H.4.3, Grayscale Image Box and statuses](https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_H.4.3.html)
- [DICOM PS3.3 C.11.2, VOI/window transform](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.11.2.html)
- [Qt QPrinter](https://doc.qt.io/qt-6/qprinter.html)
- [Qt QPainter end](https://doc.qt.io/qt-6/qpainter.html#end)

Current official Qt pages resolve to a newer release than installed Qt 6.10.2;
the reproduced defects use installed APIs and synthetic boundary probes.

## Authorized correction follow-up

The subsequent authorized implementation corrects the six confirmed defect seams:
DICOM LINEAR window mapping (including width-one threshold) now produces fixed
8-bit display values before cropping; native YBR is converted to RGB; RGB uses
the same crop/pan geometry; Implicit VR Little Endian is offered with Explicit VR;
Windows success requires painter.end() and a non-error/non-aborted printer state;
and DICOM operation/status details survive the worker boundary to the UI.

DICOM warnings remain an explicit stop policy: altered density, demagnification,
cropping or decimation are described rather than silently accepted as normal
success. There is no automatic retransmission. Invalid AE titles, ports, basic
film destination/orientation/copy settings and inconsistent grayscale payloads
are rejected before association. Optional smoothing is omitted by default and
the literal BIN_i UI placeholder was removed. Confirmed N-ACTION acceptance is
not undone by a later association-release exception. Automatic window estimation
now uses modality-transformed values and DICOM LINEAR bounds.

Verification: 22 additional cases, including 16 demonstrated fail-before cases.
The final focused printing/builder suite passed 89 tests with 2 candidate-only
cases deselected and 6 existing SWIG warnings (exit 0). All 462 mirror pairs match.
No device submission or live source-app validation was performed. Source changes
are in the printing renderer, DICOM/OS handlers and printing widget; mirrors were
updated with the repository sync tool. Existing staged work was preserved.

Remaining audit gaps are not claimed resolved: fixed 300-DPI composition, final
Windows dialog geometry reconciliation, optional color DICOM / higher precision
profiles, complete VOI/palette/physical-spacing handling, GUI-thread preparation,
and per-model physical output/completion validation. The current correction is
not a general print-device certification or a release.

Rollback: revert only this follow-up's focused hunks and paired mirror changes;
do not reset the pre-existing staged printing work. There is no new feature flag.
