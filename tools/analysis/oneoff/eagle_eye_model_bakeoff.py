"""Run the SAME captured session through several SCREENING models.

Why a harness and not three clicks: a fair comparison needs one variable. The
captures, the prompts, the verification model and the pipeline version must be
identical, and only pass 1's model may move. Re-capturing between runs would
change the images; restarting the app between runs would change nothing else
but is slow and easy to get wrong.

Each model gets its OWN COPY of the session under `_bakeoff/<slug>/`, so the
real session's stored result is never touched.

    python eagle_eye_model_bakeoff.py <session_dir> <model> [<model> ...]

Verification is pinned to gpt-5.6-sol for every run: this measures the
SCREENING model, and letting pass 2 move as well would measure nothing.
"""
import json
import os
import pathlib
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from modules.ai_imaging.eagle_eye_lumbar import llm_backend  # noqa: E402

VERIFICATION_MODEL = "gpt-5.6-sol"


def slug(name):
    return "".join(c if c.isalnum() else "_" for c in name)


def run_one(source, model, out_root):
    target = out_root / slug(model)
    if target.exists():
        shutil.rmtree(target)
    # Copy the captures, NOT any previous analysis - a stale llm_result.json
    # would read as "already complete" and the run would be skipped.
    shutil.copytree(source, target,
                    ignore=shutil.ignore_patterns("llm_*", "_bakeoff"))

    os.environ["AIPACS_EAGLE_EYE_SCREENING_MODEL"] = model
    os.environ["AIPACS_EAGLE_EYE_VERIFICATION_MODEL"] = VERIFICATION_MODEL
    os.environ.pop("AIPACS_EAGLE_EYE_MODEL", None)   # never let it pin both

    started = time.time()
    record = llm_backend.run_analysis(target)
    elapsed = time.time() - started

    print("  %-24s %-9s %5.0fs" % (model, record.state, elapsed))
    if record.state != "complete":
        print("     error:", record.error)
    return {"model": model, "dir": str(target), "state": record.state,
            "error": record.error, "seconds": round(elapsed, 1)}


def main():
    source = pathlib.Path(sys.argv[1]).resolve()
    models = sys.argv[2:]
    if not models:
        raise SystemExit("give at least one screening model")

    denied = llm_backend.company_entitlement_error()
    if denied:
        raise SystemExit("not entitled: " + denied)

    out_root = source / "_bakeoff"
    out_root.mkdir(exist_ok=True)

    print("session:", source.name)
    print("verification pinned to:", VERIFICATION_MODEL)
    print()
    results = [run_one(source, model, out_root) for model in models]

    (out_root / "bakeoff.json").write_text(
        json.dumps({"session": source.name,
                    "verification_model": VERIFICATION_MODEL,
                    "runs": results}, indent=2), encoding="utf-8")
    print("\nwrote", out_root / "bakeoff.json")


if __name__ == "__main__":
    main()
