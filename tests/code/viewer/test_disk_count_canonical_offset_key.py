"""Guard: `_count_series_files_on_disk` resolves the CANONICAL folder for offset keys.

Root cause behind the recurring "secondary (previous-exam) series won't grow" class
(48273/48476/48567): `_count_series_files_on_disk(series_number)` joined the tab's PRIMARY
study path with the bare number. A SECONDARY series is keyed by an offset DISPLAY key
(study_slot*1_000_000 + orig), which does NOT exist under the primary study path, so the
call returned a WRONG 0 on-disk — and EVERY caller (the same-series no-op grow check,
progressive grow, load-completion, the backend candidate probe) then believed the series
had nothing on disk and never grew it.

The source-level fix: when the bare join misses AND the key is an offset key
(>= 1_000_000), resolve the canonical (study_uid, orig_series) and count that per-study
folder instead. STRICTLY additive — ordinary/primary/single-study numbers (< 1_000_000)
never reach the fallback and stay byte-identical. Kill switch AIPACS_DISK_COUNT_CANONICAL=0.

Source-pins (the module imports PySide6, so it can't be imported headless in the sandbox).
"""
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_cache.py"
    ).read_text(encoding="utf-8")


def test_offset_key_falls_back_to_canonical_identity():
    src = _src()
    fn = src.find("def _count_series_files_on_disk")
    assert fn != -1
    body = src[fn:fn + 3800]
    # the bare primary-study join is still tried FIRST (single-study unchanged)
    assert "_cand = os.path.join(study_path, str(series_number))" in body
    assert "if os.path.isdir(_cand):" in body
    # offset-key gate: only secondary DISPLAY keys reach the canonical fallback
    assert "int(str(series_number)) >= 1_000_000" in body
    # canonical resolution + the series' OWN per-study folder under SOURCE_PATH
    assert "self._resolve_canonical_series_identity(series_number)" in body
    assert "from PacsClient.utils.config import SOURCE_PATH as _SRC" in body
    assert "os.path.join(str(_SRC), str(_cu_study), str(_cu_orig))" in body
    # flag COLLAPSED after 48695 live-verify: canonical resolution is unconditional,
    # no kill switch (the legacy "return wrong 0 for an offset key" has no valid use).
    assert 'AIPACS_DISK_COUNT_CANONICAL' not in body
    assert "_canon_ok" not in body


def test_missing_series_still_returns_zero_and_caches():
    src = _src()
    fn = src.find("def _count_series_files_on_disk")
    body = src[fn:fn + 3800]
    # a genuinely-absent series still yields 0 — and the 0 is cached (no repeated I/O)
    assert "if series_dir is None:" in body
    assert "cache[key] = (0, _now)" in body
    assert "return 0" in body
