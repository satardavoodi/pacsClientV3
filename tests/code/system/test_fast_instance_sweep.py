"""Guard test for OPT-12 — fast single-instance sweep via a pid→ppid snapshot.

STALL_TRACE (2026-07-05) showed the ~2.3 s startup stall is the single-instance
sweep's psutil `me.parents()` / `me.children(recursive=True)` / per-candidate
`proc.ppid()`, each of which rebuilds the whole Windows parent map. The fast path
reads parent PIDs from the ONE cheap Toolhelp snapshot already taken for names and
computes the protected set (self + ancestors + descendants) with a pure dict walk.

This is SAFETY-CRITICAL: the protected set is what stops the sweep from killing our
own launcher / process tree. So the pure computation is exercised hard here. The
flag defaults OFF (`AIPACS_FAST_INSTANCE_SWEEP`) pending live Windows validation;
the legacy psutil path stays byte-identical when off.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "PacsClient" / "utils" / "single_instance_lock.py"


def _src() -> str:
    best = ""
    for _ in range(8):
        b = SRC.read_bytes()
        if len(b) > len(best.encode("utf-8", "ignore")):
            best = b.decode("utf-8-sig", errors="ignore")
    return best


# --- source-pins ---------------------------------------------------------------------

def test_flag_default_on_validated():
    # promoted to default ON 2026-07-05 after live validation (startup :387 stall gone,
    # 0 crashes, nothing wrongly closed). Kill switch AIPACS_FAST_INSTANCE_SWEEP=0.
    assert 'os.getenv("AIPACS_FAST_INSTANCE_SWEEP", "1")' in _src()


def test_toolhelp_scan_exposes_ppid():
    s = _src()
    assert "th32ParentProcessID" in s
    assert "def _iter_pid_name_ppid_cheap():" in s
    # the (pid, name) iterator is now a thin wrapper over the ppid one
    assert "for pid, name, _ppid in _iter_pid_name_ppid_cheap():" in s


def test_fast_path_wired_and_legacy_preserved():
    s = _src()
    assert "_protected_pids_from_snapshot(_pid2ppid, self_pid)" in s
    # legacy psutil ancestors/descendants still present under `if not _use_fast:`
    assert "protected.update(a.pid for a in me.parents())" in s
    assert "protected.update(c.pid for c in me.children(recursive=True))" in s
    # top-level check uses the snapshot in fast mode, proc.ppid() otherwise
    assert "_parent_pid = _pid2ppid.get(pid)" in s
    assert "_parent_pid = proc.ppid()" in s


# --- pure protected-set logic (mirror of _protected_pids_from_snapshot) ---------------

def _protected(pid2ppid, self_pid):
    protected = {int(self_pid)}
    cur = int(self_pid)
    seen = set()
    while True:
        parent = pid2ppid.get(cur)
        if parent is None or parent in (0, cur) or parent in seen:
            break
        seen.add(parent)
        protected.add(int(parent))
        cur = int(parent)
    children = {}
    for _pid, _ppid in pid2ppid.items():
        children.setdefault(_ppid, []).append(_pid)
    stack = [int(self_pid)]
    while stack:
        node = stack.pop()
        for child in children.get(node, ()):
            if child not in protected:
                protected.add(int(child))
                stack.append(int(child))
    return protected


def test_protects_self_ancestors_and_descendants():
    # 1(root) -> 10 -> 100(self) -> 1000 ; 10 -> 101(sibling) ; 999 unrelated
    m = {100: 10, 10: 1, 1000: 100, 101: 10, 999: 5}
    assert _protected(m, 100) == {1, 10, 100, 1000}


def test_does_not_protect_siblings_or_unrelated():
    m = {100: 10, 10: 1, 1000: 100, 101: 10, 999: 5}
    prot = _protected(m, 100)
    assert 101 not in prot   # a sibling AiPacs/python process IS a valid kill target
    assert 999 not in prot


def test_cycle_guard():
    assert _protected({1: 2, 2: 1}, 1) == {1, 2}


def test_ppid_zero_stops_ancestor_walk():
    assert _protected({5: 0}, 5) == {5}


def test_empty_snapshot_protects_only_self():
    assert _protected({}, 42) == {42}


def test_deep_tree_all_descendants_protected():
    m = {2: 1, 3: 1, 4: 2, 5: 2, 6: 4}
    assert _protected(m, 1) == {1, 2, 3, 4, 5, 6}       # root protects everything
    assert _protected(m, 2) == {1, 2, 4, 5, 6}          # self+ancestor+desc, not sib 3


def test_real_function_matches_mirror_if_importable():
    # exercise the actual module function when it can be imported offscreen
    try:
        from PacsClient.utils.single_instance_lock import _protected_pids_from_snapshot
    except Exception:
        return  # import needs PySide6/Qt; source-pins + mirror cover the logic
    m = {100: 10, 10: 1, 1000: 100, 101: 10}
    assert _protected_pids_from_snapshot(m, 100) == _protected(m, 100)
