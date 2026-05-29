"""KPI HTML trend-report generator.

Reads ``user_data/test_kpis/*.jsonl`` and renders a self-contained
HTML page with one SVG line chart per KPI key plus per-run summary
tables. No JS frameworks, no external CDN — opens offline in any
browser. Stdlib only.

Usage::

    python tools/kpi_html_report.py
    python tools/kpi_html_report.py --output kpi_report.html
    python tools/kpi_html_report.py --max-runs 50

Output: ``kpi_report.html`` at the project root by default.

See ``docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`` §9.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SINK = _PROJECT_ROOT / "user_data" / "test_kpis"
_DEFAULT_OUTPUT = _PROJECT_ROOT / "kpi_report.html"


# ── data loading ────────────────────────────────────────────────────────

def load_records(sink: Path) -> list[dict]:
    if not sink.exists():
        return []
    records: list[dict] = []
    for p in sorted(sink.glob("*.jsonl")):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception:
            continue
    return records


def group_by_key(records: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        k = r.get("key")
        if k:
            out[k].append(r)
    return out


def group_by_run(records: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        out[r.get("run_id", "?")].append(r)
    return out


# ── SVG chart helper (zero deps) ────────────────────────────────────────

def render_svg_line(
    series: list[tuple[str, float]],
    *,
    width: int = 720,
    height: int = 120,
    pad: int = 28,
    hard: float | None = None,
    warn: float | None = None,
    higher_better: bool = False,
) -> str:
    """Tiny SVG line chart. Series is [(run_id, value)] in chronological order."""
    if not series:
        return ('<svg width="%d" height="%d" '
                'style="background:#fafafa;border:1px solid #ddd"/>'
                % (width, height))

    values = [v for _, v in series]
    raw_lo = min(values)
    raw_hi = max(values)
    # Include thresholds in the y range so they're visible.
    for t in (hard, warn):
        if t is not None:
            raw_lo = min(raw_lo, t)
            raw_hi = max(raw_hi, t)
    span = max(raw_hi - raw_lo, 1e-9)
    lo = raw_lo - span * 0.05
    hi = raw_hi + span * 0.05
    span = max(hi - lo, 1e-9)

    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    def x(i: int) -> float:
        if len(series) <= 1:
            return pad + inner_w / 2
        return pad + (i * inner_w / (len(series) - 1))

    def y(v: float) -> float:
        return pad + inner_h - ((v - lo) / span) * inner_h

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(series))
    last_x, last_y = x(len(series) - 1), y(values[-1])

    threshold_lines = []
    if hard is not None and lo <= hard <= hi:
        ly = y(hard)
        threshold_lines.append(
            f'<line x1="{pad}" y1="{ly:.1f}" x2="{pad+inner_w}" y2="{ly:.1f}" '
            f'stroke="#c0392b" stroke-dasharray="4 3" stroke-width="1"/>'
            f'<text x="{pad+inner_w}" y="{ly-2:.1f}" font-size="10" '
            f'fill="#c0392b" text-anchor="end">hard={hard}</text>'
        )
    if warn is not None and lo <= warn <= hi:
        ly = y(warn)
        threshold_lines.append(
            f'<line x1="{pad}" y1="{ly:.1f}" x2="{pad+inner_w}" y2="{ly:.1f}" '
            f'stroke="#d68910" stroke-dasharray="4 3" stroke-width="1"/>'
            f'<text x="{pad+inner_w}" y="{ly-2:.1f}" font-size="10" '
            f'fill="#d68910" text-anchor="end">warn={warn}</text>'
        )

    # axis ticks (lo / median / hi)
    median_v = median(values)
    ticks = ''.join(
        f'<text x="{pad-4}" y="{y(v)+3:.1f}" font-size="9" fill="#555" '
        f'text-anchor="end">{v:.1f}</text>'
        for v in (lo, median_v, hi)
    )

    return (
        f'<svg width="{width}" height="{height}" '
        f'style="background:#fafafa;border:1px solid #ddd">'
        f'<polyline points="{pts}" fill="none" stroke="#1f77b4" stroke-width="1.5"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="#1f77b4"/>'
        f'{"".join(threshold_lines)}'
        f'{ticks}'
        f'</svg>'
    )


# ── render ──────────────────────────────────────────────────────────────

_CSS = """
body { font-family: -apple-system, system-ui, sans-serif; margin: 24px; color: #222; }
h1 { font-size: 22px; margin: 0 0 4px 0; }
.sub { color: #666; font-size: 12px; margin-bottom: 16px; }
.workflow { margin: 32px 0 16px; border-top: 1px solid #ccc; padding-top: 12px; }
.workflow h2 { font-size: 16px; margin: 0 0 8px 0; color: #333; }
.kpi { display: flex; align-items: flex-start; gap: 16px; padding: 12px 0;
       border-bottom: 1px solid #eee; }
.kpi .meta { width: 320px; font-size: 13px; }
.kpi .meta .key { font-weight: 600; font-family: ui-monospace, monospace; font-size: 12px; }
.kpi .meta .verdict { display: inline-block; padding: 1px 6px; border-radius: 3px;
                      font-size: 11px; font-weight: 600; margin-left: 6px; }
.verdict.PASS { background: #d4edda; color: #155724; }
.verdict.WARN { background: #fff3cd; color: #856404; }
.verdict.FAIL { background: #f8d7da; color: #721c24; }
.kpi .meta .desc { color: #666; font-size: 11px; margin-top: 4px; }
.summary { display: flex; gap: 12px; margin: 12px 0 24px; }
.summary .box { padding: 8px 14px; border-radius: 4px; font-size: 13px; font-weight: 600; }
.summary .PASS { background: #d4edda; color: #155724; }
.summary .WARN { background: #fff3cd; color: #856404; }
.summary .FAIL { background: #f8d7da; color: #721c24; }
table.runs { width: 100%; font-size: 12px; border-collapse: collapse; margin-top: 16px; }
table.runs th, table.runs td { text-align: left; padding: 4px 8px;
                                border-bottom: 1px solid #eee; }
table.runs th { background: #f4f4f4; font-weight: 600; }
.empty { color: #888; font-style: italic; padding: 16px; }
"""


def render_html(records: list[dict], *, max_runs: int = 50) -> str:
    if not records:
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>AI-PACS KPI report</title>"
            f"<style>{_CSS}</style></head><body>"
            "<h1>AI-PACS KPI report</h1>"
            "<div class='empty'>No KPI records found yet. "
            "Run a test that uses the <code>kpi</code> fixture, then re-run "
            "this tool.</div></body></html>"
        )

    by_key = group_by_key(records)
    by_run = group_by_run(records)

    # latest run summary
    latest = sorted(by_run.keys())[-1]
    latest_recs = by_run[latest]
    summary = defaultdict(int)
    for r in latest_recs:
        summary[r.get("verdict", "?")] += 1

    # workflow grouping
    by_workflow: dict[str, list[str]] = defaultdict(list)
    for key, recs in by_key.items():
        wf = recs[0].get("workflow", "?")
        by_workflow[wf].append(key)
    for keys in by_workflow.values():
        keys.sort()

    # build per-key cards
    sections: list[str] = []
    for wf in sorted(by_workflow):
        cards: list[str] = []
        for key in by_workflow[wf]:
            recs = sorted(by_key[key], key=lambda r: r.get("ts", ""))
            recent = recs[-max_runs:]
            series = [(r.get("run_id", "?"), float(r.get("value", 0)))
                      for r in recent]
            # KPI spec from the latest record:
            last = recent[-1]
            verdict = last.get("verdict", "?")
            unit = last.get("unit", "")
            hard = last.get("threshold_hard")
            warn = last.get("threshold_warn")
            hb = bool(last.get("higher_better"))
            desc = last.get("description", "") or ""

            svg = render_svg_line(
                series, hard=hard, warn=warn, higher_better=hb,
            )
            cards.append(
                f'<div class="kpi"><div class="meta">'
                f'<span class="key">{html.escape(key)}</span>'
                f'<span class="verdict {html.escape(verdict)}">'
                f'{html.escape(verdict)}</span>'
                f'<div>last={last.get("value", 0):.2f} {html.escape(unit)} '
                f'· n={len(recent)} run(s) · '
                f'hard={hard if hard is not None else "-"} '
                f'warn={warn if warn is not None else "-"} '
                f'{"(↑ better)" if hb else ""}</div>'
                f'<div class="desc">{html.escape(desc)}</div>'
                f'</div>{svg}</div>'
            )
        sections.append(
            f'<div class="workflow"><h2>workflow: {html.escape(wf)}</h2>'
            f'{"".join(cards)}</div>'
        )

    # per-run history table
    run_table_rows: list[str] = []
    for rid in sorted(by_run.keys(), reverse=True)[:30]:
        c = defaultdict(int)
        for r in by_run[rid]:
            c[r.get("verdict", "?")] += 1
        first = by_run[rid][0]
        run_table_rows.append(
            f'<tr><td><code>{html.escape(rid)}</code></td>'
            f'<td>{html.escape(first.get("host", "?"))}</td>'
            f'<td>{html.escape(first.get("git_sha", "") or "-")}</td>'
            f'<td>{html.escape(first.get("build_kind", "?"))}</td>'
            f'<td>{c["PASS"]}</td><td>{c["WARN"]}</td><td>{c["FAIL"]}</td></tr>'
        )

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>AI-PACS KPI report</title>"
        f"<style>{_CSS}</style></head><body>"
        "<h1>AI-PACS KPI report</h1>"
        f"<div class='sub'>latest run: <code>{html.escape(latest)}</code> "
        f"· {len(records)} record(s) across {len(by_run)} run(s) "
        f"· {len(by_key)} KPI key(s)</div>"
        f"<div class='summary'>"
        f"<div class='box PASS'>PASS {summary.get('PASS', 0)}</div>"
        f"<div class='box WARN'>WARN {summary.get('WARN', 0)}</div>"
        f"<div class='box FAIL'>FAIL {summary.get('FAIL', 0)}</div>"
        f"</div>"
        f"{''.join(sections)}"
        "<h2 style='margin-top:32px'>Recent runs</h2>"
        "<table class='runs'><thead><tr>"
        "<th>run_id</th><th>host</th><th>git</th><th>build</th>"
        "<th>PASS</th><th>WARN</th><th>FAIL</th></tr></thead><tbody>"
        f"{''.join(run_table_rows)}"
        "</tbody></table>"
        "</body></html>"
    )


# ── CLI ─────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sink", type=Path, default=_DEFAULT_SINK,
                        help="JSONL sink directory")
    parser.add_argument("--output", "-o", type=Path, default=_DEFAULT_OUTPUT,
                        help="Output HTML path")
    parser.add_argument("--max-runs", type=int, default=50,
                        help="Trim each KPI series to last N runs")
    args = parser.parse_args(argv)

    records = load_records(args.sink)
    html_str = render_html(records, max_runs=args.max_runs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_str, encoding="utf-8")
    print(f"Wrote {args.output}  ({len(records)} record(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
