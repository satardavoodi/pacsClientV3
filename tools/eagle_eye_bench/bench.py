"""Eagle Eye lumbar bench: score existing sessions, or run one N times.

Two subcommands.

``score``  Parse and score FINAL REPORTs that already exist on disk. Costs
           nothing, touches no model, and is the fastest way to see how a
           change moved the numbers after the fact.

``run``    Copy a captured session N times and run the analysis pipeline on
           each copy, then score all N. This SPENDS MODEL BUDGET - N x 3
           requests - so it asks for confirmation unless --yes is given.

Both report per-claim hit rates over N runs rather than a single verdict.
Repeated model runs can disagree about morphology, so one run is not a
reliable comparison of two pipeline configurations.

Examples::

    python -m tools.eagle_eye_bench.bench score --case lumbar-001 \\
        --study "<study-instance-uid>"

    python -m tools.eagle_eye_bench.bench run --case lumbar-001 \\
        --session <path to a captured session> --repeats 5 \\
        --label baseline-4.6.1 --evidence-mode focused-v2
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.eagle_eye_bench import reference as reference_mod  # noqa: E402
from tools.eagle_eye_bench import scoring  # noqa: E402

COPY_ENTRIES = (
    "session.json",
    "series_sources.local.json",
    "Sagittal",
    "Axial",
)


def _eagle_eye_root() -> Path:
    try:
        from PacsClient.utils.data_paths import AI_DIR
        return Path(AI_DIR) / "eagle_eye"
    except Exception:
        return REPO_ROOT / "user_data" / "ai" / "eagle_eye"


def _bench_root() -> Path:
    return _eagle_eye_root() / "_bench"


def find_sessions(study_uid: str) -> List[Path]:
    study_dir = _eagle_eye_root() / study_uid
    if not study_dir.is_dir():
        return []
    return sorted(
        p for p in study_dir.iterdir()
        if p.is_dir() and (p / "llm_result.txt").is_file()
    )


def score_session(session_dir: Path, ref: Dict[str, Any]) -> Optional[scoring.RunScore]:
    report_path = Path(session_dir) / "llm_result.txt"
    if not report_path.is_file():
        return None
    parsed = scoring.parse_report(report_path.read_text(encoding="utf-8", errors="replace"))
    score = scoring.score_report(ref, parsed, run_id=Path(session_dir).name)
    meta = Path(session_dir) / "llm_result.json"
    if meta.is_file():
        try:
            document = json.loads(meta.read_text(encoding="utf-8"))
            score.parse_notes.append(
                "pipeline {pv} | evidence {mode} | s3 images {imgs}".format(
                    pv=document.get("pipeline_version", "?"),
                    mode=document.get("verification_evidence_mode", "-"),
                    imgs=document.get("verification_image_count", "-"),
                )
            )
        except Exception:
            pass
    return score


def clone_session(session_dir: Path, destination: Path) -> Path:
    """A fresh copy of the captures only - no previous answers come along."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in COPY_ENTRIES:
        source = Path(session_dir) / name
        if not source.exists():
            continue
        target = destination / name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return destination


def run_once(run_dir: Path) -> None:
    from modules.ai_imaging.eagle_eye_lumbar import llm_backend
    llm_backend.run_analysis(run_dir)


def cmd_score(args: argparse.Namespace) -> int:
    ref = reference_mod.load(args.case)
    if args.session:
        sessions = [Path(args.session)]
    else:
        study = args.study or ref.get("study_instance_uid", "")
        sessions = find_sessions(study)
        if args.since:
            sessions = [s for s in sessions if s.name >= args.since]
    if not sessions:
        print("No sessions with a FINAL REPORT were found.")
        return 1

    scores: List[scoring.RunScore] = []
    for session in sessions:
        score = score_session(session, ref)
        if score is None:
            continue
        scores.append(score)
        counts = score.counts()
        critical = ", ".join(c.claim_id for c in score.critical_misses) or "none"
        print(f"{session.name:<20} {counts}")
        print(f"{'':<20} critical misses: {critical}")
        for note in score.parse_notes:
            print(f"{'':<20} note: {note}")
    print()
    print(scoring.summarize(scoring.aggregate(scores)))
    if args.out:
        Path(args.out).write_text(
            json.dumps([s.as_dict() for s in scores], indent=2), encoding="utf-8"
        )
        print(f"\nwrote {args.out}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    ref = reference_mod.load(args.case)
    session = Path(args.session)
    if not (session / "session.json").is_file():
        print(f"{session} is not a captured Eagle Eye session.")
        return 1

    label = args.label or time.strftime("run-%Y%m%dT%H%M%S")
    root = _bench_root() / "runs" / label
    total = int(args.repeats)

    print(f"case      : {ref['case_id']}")
    print(f"session   : {session}")
    print(f"repeats   : {total}   ({total * 3} model requests)")
    print(f"evidence  : {args.evidence_mode or '(unchanged)'}")
    print(f"output    : {root}")
    if not args.yes:
        answer = input("This spends model budget. Continue? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("aborted")
            return 1

    if args.evidence_mode:
        os.environ["AIPACS_EAGLE_EYE_EVIDENCE_MODE"] = args.evidence_mode

    scores: List[scoring.RunScore] = []
    for index in range(1, total + 1):
        run_dir = clone_session(session, root / f"{index:02d}")
        print(f"[{index}/{total}] running {run_dir.name} ...", flush=True)
        try:
            run_once(run_dir)
        except Exception as exc:
            print(f"[{index}/{total}] FAILED: {exc}")
            continue
        score = score_session(run_dir, ref)
        if score is None:
            print(f"[{index}/{total}] no FINAL REPORT produced")
            continue
        scores.append(score)
        print(f"[{index}/{total}] {score.counts()}")

    summary = scoring.aggregate(scores)
    print()
    print(scoring.summarize(summary))
    out = root / "bench_summary.json"
    out.write_text(json.dumps({
        "label": label,
        "case_id": ref["case_id"],
        "source_session": str(session),
        "evidence_mode": args.evidence_mode or "",
        "aggregate": summary,
        "runs": [s.as_dict() for s in scores],
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eagle_eye_bench")
    sub = parser.add_subparsers(dest="command", required=True)

    score = sub.add_parser("score", help="score FINAL REPORTs already on disk")
    score.add_argument("--case", required=True, help="reference case id")
    score.add_argument("--study", default="", help="StudyInstanceUID to scan")
    score.add_argument("--session", default="", help="score one session folder")
    score.add_argument("--since", default="", help="only sessions at or after this id")
    score.add_argument("--out", default="", help="write per-run JSON here")
    score.set_defaults(func=cmd_score)

    run = sub.add_parser("run", help="re-run one captured session N times")
    run.add_argument("--case", required=True, help="reference case id")
    run.add_argument("--session", required=True, help="captured session to replicate")
    run.add_argument("--repeats", type=int, default=5)
    run.add_argument("--label", default="")
    run.add_argument("--evidence-mode", default="",
                     choices=["", "layout", "focused-v1", "focused-v2",
                              "focused-v3", "focused-v3-parasagittal"])
    run.add_argument("--yes", action="store_true", help="skip the budget confirmation")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
