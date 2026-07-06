"""Guard test for OPT-01 — TTL cache + cheaper check for `_is_study_downloaded`.

`_is_study_downloaded` runs per-row on EVERY DM-progress-driven status refresh, so a
download storm re-walks every study's folder many times/second on the GUI thread — the
measured main-thread-stall amplifier (up to 48 s on the reporting PC). The fix:
  * a short-TTL cache (`AIPACS_STUDY_DL_CHECK_CACHE`, TTL `AIPACS_STUDY_DL_CHECK_TTL_MS`)
    collapses the repeated walks;
  * the entry is invalidated the instant a study's download status changes
    (`update_study_download_status` -> `_invalidate_study_downloaded_cache`), so a
    completed study still flips to downloaded promptly;
  * the disk check itself is a single `os.scandir` pass with early exit (was 1 + N
    `iterdir()` calls), behavior preserved: downloaded == a series subfolder has ≥1 entry.

House style: source-pins guard the real edit (no QApplication) + behavioral mirrors
reproduce the cache algorithm and the scandir check against a real temp tree.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PTW = REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "patient_table_widget.py"


def _src() -> str:
    best = ""
    for _ in range(8):
        b = PTW.read_bytes()
        if len(b) > len(best.encode("utf-8", "ignore")):
            best = b.decode("utf-8-sig", errors="ignore")
    return best


# --- source-pins ---------------------------------------------------------------------

def test_flag_retired_cache_unconditional():
    # promoted to default 2026-07-05: the on/off flag is gone; caching is always on
    # (the TTL tunable AIPACS_STUDY_DL_CHECK_TTL_MS remains, so check the on/off read only)
    assert 'os.getenv("AIPACS_STUDY_DL_CHECK_CACHE"' not in _src()


def test_helpers_defined():
    s = _src()
    assert "def _compute_study_downloaded(self, study_uid: str) -> bool:" in s
    assert "def _invalidate_study_downloaded_cache(self, study_uid: str = None) -> None:" in s
    assert "self._study_downloaded_cache = {}" in s


def test_cheaper_check_uses_scandir_not_iterdir():
    s = _src()
    start = s.index("def _compute_study_downloaded")
    body = s[start:start + 1400]
    assert "os.scandir(" in body
    assert ".iterdir()" not in body      # the expensive per-call list walk is gone here


def test_invalidation_wired_into_status_update():
    s = _src()
    start = s.index("def update_study_download_status")
    body = s[start:start + 1600]
    assert "self._invalidate_study_downloaded_cache(study_uid)" in body


# --- behavioral mirror: TTL cache + invalidation -------------------------------------

class _Mirror:
    """Reproduces the _is_study_downloaded cache decision; counts real disk walks."""

    def __init__(self, enabled=True, ttl_s=1.5):
        self._study_downloaded_cache = {}
        self._enabled = enabled
        self._ttl = ttl_s
        self.walks = 0
        self._now = 1000.0
        self._disk_state = {}   # study_uid -> bool

    def _mono(self):
        return self._now

    def _compute(self, study_uid):
        self.walks += 1
        return self._disk_state.get(study_uid, False)

    def is_downloaded(self, study_uid):
        if not study_uid:
            return False
        if self._enabled:
            ent = self._study_downloaded_cache.get(study_uid)
            if ent is not None:
                val, ts = ent
                if (self._mono() - ts) < self._ttl:
                    return val
        result = self._compute(study_uid)
        if self._enabled:
            self._study_downloaded_cache[study_uid] = (result, self._mono())
        return result

    def invalidate(self, study_uid=None):
        if study_uid is None:
            self._study_downloaded_cache.clear()
        else:
            self._study_downloaded_cache.pop(study_uid, None)


def test_repeated_calls_collapse_to_one_walk_within_ttl():
    m = _Mirror(enabled=True)
    m._disk_state["S1"] = True
    for _ in range(50):
        assert m.is_downloaded("S1") is True
    assert m.walks == 1        # 50 refreshes -> a single disk walk


def test_ttl_expiry_rewalks():
    m = _Mirror(enabled=True, ttl_s=1.5)
    m.is_downloaded("S1")
    m._now += 2.0              # past the TTL
    m.is_downloaded("S1")
    assert m.walks == 2


def test_invalidation_forces_rewalk_and_flips_state():
    m = _Mirror(enabled=True)
    assert m.is_downloaded("S1") is False   # not on disk yet (walk 1)
    m.is_downloaded("S1")                    # cached False (no walk)
    assert m.walks == 1
    # download completes -> status update invalidates the entry
    m._disk_state["S1"] = True
    m.invalidate("S1")
    assert m.is_downloaded("S1") is True     # re-walks, flips to True (walk 2)
    assert m.walks == 2




# --- behavioral: the scandir check semantics (real temp tree) ------------------------

def _compute_downloaded(study_path: Path) -> bool:
    """Mirror of _compute_study_downloaded's scandir logic."""
    try:
        with os.scandir(study_path) as entries:
            for entry in entries:
                try:
                    if not entry.is_dir():
                        continue
                    with os.scandir(entry.path) as sub:
                        for _child in sub:
                            return True
                except OSError:
                    continue
    except (FileNotFoundError, NotADirectoryError):
        return False
    return False


def test_downloaded_true_when_series_folder_has_a_file(tmp_path):
    study = tmp_path / "study1"
    series = study / "1"
    series.mkdir(parents=True)
    (series / "img.dcm").write_bytes(b"x")
    assert _compute_downloaded(study) is True


def test_downloaded_false_for_missing_study(tmp_path):
    assert _compute_downloaded(tmp_path / "nope") is False


def test_downloaded_false_when_only_loose_files_no_series_dir(tmp_path):
    study = tmp_path / "study2"
    study.mkdir()
    (study / "loose.txt").write_bytes(b"x")   # a file, not a series subdir
    assert _compute_downloaded(study) is False


def test_downloaded_false_when_series_dir_empty(tmp_path):
    study = tmp_path / "study3"
    (study / "1").mkdir(parents=True)          # empty series folder
    assert _compute_downloaded(study) is False


# --- OPT-01: expensive-flag TTL reuse in _compute_local_status_flags -----------------

def test_expensive_ttl_flag_present_default_off_pending_validation():
    # opt-in until the freshness change is validated live (default "0" = legacy)
    assert 'os.getenv("AIPACS_STATUS_EXPENSIVE_TTL", "0")' in _src()


def test_expensive_ttl_reuses_expensive_flags_and_refreshes_dicom():
    s = _src()
    start = s.index("def _compute_local_status_flags")
    body = s[start:start + 3000]
    # within the window it refreshes ONLY dicom and reuses the cached expensive flags
    assert "_data['dicom'] = bool(self._is_study_downloaded(study_uid))" in body
    assert "_prev = cached.get('data')" in body
    assert "if _age < _exp_ttl and isinstance(_prev, dict):" in body


class _StatusMirror:
    """Mirror of the two-tier TTL in _compute_local_status_flags.

    counts full_recompute (os.walk + DB queries) vs cheap dicom refresh."""

    def __init__(self, short=5.0, exp=30.0, enabled=True):
        self.cache = {}
        self.short = short
        self.exp = exp
        self.enabled = enabled
        self.now = 1000.0
        self.full_recompute = 0
        self.dicom_refresh = 0
        self._downloaded = True

    def compute(self, key):
        ent = self.cache.get(key)
        if ent is not None:
            age = self.now - ent["timestamp"]
            if age < self.short:
                return dict(ent["data"])
            if self.enabled and age < self.exp and isinstance(ent.get("data"), dict):
                data = dict(ent["data"])
                data["dicom"] = self._downloaded          # cheap cached check
                self.dicom_refresh += 1
                self.cache[key] = {"data": data, "timestamp": self.now}
                return dict(data)
        # full recompute: os.walk(attachments) + case-of-day + printed DB queries
        self.full_recompute += 1
        data = {"dicom": self._downloaded, "documents": True, "voice": True}
        self.cache[key] = {"data": data, "timestamp": self.now}
        return dict(data)


def test_expensive_flags_reused_between_short_and_expensive_ttl():
    m = _StatusMirror(short=5.0, exp=30.0, enabled=True)
    m.compute("k")                 # full recompute #1
    m.now += 10.0                  # past short TTL, within expensive TTL
    m.compute("k")
    m.compute("k") if False else None
    assert m.full_recompute == 1   # NOT re-walked
    assert m.dicom_refresh == 1    # only the cheap dicom flag refreshed


def test_expensive_ttl_expiry_forces_full_recompute():
    m = _StatusMirror(short=5.0, exp=30.0, enabled=True)
    m.compute("k")
    m.now += 40.0                  # past the expensive TTL
    m.compute("k")
    assert m.full_recompute == 2


def test_expensive_ttl_kill_switch_full_recompute_after_short():
    m = _StatusMirror(short=5.0, exp=30.0, enabled=False)
    m.compute("k")
    m.now += 10.0                  # past short TTL; legacy -> full recompute
    m.compute("k")
    assert m.full_recompute == 2
    assert m.dicom_refresh == 0
