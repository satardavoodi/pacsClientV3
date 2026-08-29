"""Contact sheets for one Eagle Eye session, for eyeballing a run.

Reads the manifests (never the folder listing) so the sheet is ordered by
CAPTURE INDEX and each tile can be labelled with what that frame actually is.
A sheet built from a glob would look identical and prove nothing.

Protocol-generic since v1.1.0: the passes come from ``session.json`` and the
panes are read by SEMANTIC ROLE out of ``captures[].panes`` rather than from
lumbar-specific keys, so this works for any protocol's capture sessions
without edits.

    python eagle_eye_contact_sheet_2026_08_26.py <session_dir> [out_dir]
"""

import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

TILE_W = 620          # per-tile width; 3-5 across is readable without being huge
LABEL_H = 26
PAD = 6
BG = (12, 18, 28)
FG = (226, 232, 240)
ACCENT = (250, 204, 21)


def _pane_bits(cap):
    """One short token per pane, driving pane first, then in manifest order."""
    driving = cap.get("driving_pane")
    panes = cap.get("panes") or {}
    order = ([driving] if driving in panes else []) + [k for k in panes if k != driving]
    bits = []
    for role in order:
        pane = panes[role]
        token = f"{pane.get('label', role)} #{pane.get('slice_index')}"
        if pane.get("parked"):
            token += " park"
        elif pane.get("followed_by"):
            token += f" [{pane['followed_by']}]"
        bits.append(token)
    return "  ".join(bits)


def _label_for(cap):
    ctx = cap.get("spatial_context") or cap.get("axial_context") or {}
    where = ""
    if "side" in ctx or "region" in ctx:
        where = f"  {ctx.get('side', '?')}/{ctx.get('region', '?')} {ctx.get('offset_mm', '?')}mm"
    elif "level" in ctx:
        where = f"  {ctx['level']}"
    elif "z_lps" in ctx:
        where = f"  z={ctx['z_lps']}"
    # which panes are kept clean is constant per session and already printed in
    # the sheet header, so the per-tile label stays short enough not to run
    # into its neighbour
    return f"#{cap['index']:02d}  {_pane_bits(cap)}{where}"


def build(session_dir: Path, directory: str, out_dir: Path, columns: int) -> Path:
    manifest = json.load(io.open(session_dir / directory / "manifest.json", encoding="utf-8"))
    caps = manifest["captures"]

    first = Image.open(session_dir / directory / caps[0]["image"])
    scale = TILE_W / first.width
    tile_h = int(first.height * scale)

    rows = (len(caps) + columns - 1) // columns
    sheet_w = columns * TILE_W + (columns + 1) * PAD
    sheet_h = rows * (tile_h + LABEL_H) + (rows + 1) * PAD + 34
    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)

    order = manifest.get("capture_order") or {}
    draw.text((PAD + 2, 9),
              f"{manifest['session_type']}   {len(caps)} frames   "
              f"direction={order.get('direction')}   axis={order.get('axis')}   "
              f"driving={order.get('driving_slot')}   "
              f"lines hidden on {order.get('reference_lines_hidden_on')}   "
              f"session {manifest['session_id']}   v{manifest.get('eagle_eye_version')}",
              fill=ACCENT)

    for i, cap in enumerate(caps):
        r, c = divmod(i, columns)
        x = PAD + c * (TILE_W + PAD)
        y = 34 + PAD + r * (tile_h + LABEL_H + PAD)
        img = Image.open(session_dir / directory / cap["image"]).convert("RGB")
        sheet.paste(img.resize((TILE_W, tile_h), Image.LANCZOS), (x, y))
        draw.text((x + 3, y + tile_h + 6), _label_for(cap), fill=FG)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"eagle_eye_{directory.lower()}_contact_sheet.png"
    sheet.save(out, optimize=True)
    print(f"{out}  {out.stat().st_size / 1e6:.1f} MB  {sheet.size}")
    return out


def main() -> int:
    session_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else session_dir / "_contact_sheets"
    session = json.load(io.open(session_dir / "session.json", encoding="utf-8"))
    for name, spec in (session.get("passes") or {}).items():
        directory = spec.get("directory") or name.title()
        count = spec.get("capture_count") or 0
        build(session_dir, directory, out_dir, columns=3 if count <= 12 else 5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
