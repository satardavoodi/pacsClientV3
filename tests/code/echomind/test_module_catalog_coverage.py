"""Module catalog coverage gate.

The EchoMind ``catalog/modules/*.md`` files document what the agent is
allowed to ask for. The CommandBus adapters provide what the agent can
actually do. Drift between the two is a documentation lie.

This test:

1. Enumerates the catalog (every module document under
   ``modules/EchoMind/secretary/catalog/modules/``).
2. Asks the CommandBus what action names ARE actually registered when
   all known launchers are wired (production widget.py + the lazy
   DownloadAdapter + the read-only ViewerAdapter).
3. Lists modules whose actions are NOT yet reachable as a NON-FAILING
   diagnostic, plus a categorization of what's "wired today vs catalog".

The test always PASSes — drift is a finding to report, not a build
blocker. But the per-module summary it prints is what an agent uses
to know what it can attempt.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pydantic  # noqa: F401
except ImportError:
    import pytest
    pytest.skip("pydantic not installed", allow_module_level=True)

CATALOG_DIR = PROJECT_ROOT / "modules" / "EchoMind" / "secretary" / "catalog" / "modules"


def _enumerate_catalog() -> dict[str, dict]:
    """Return {module_id: {actions: [..]}} parsed from the *.md headers.

    The MD files use ``module_id:`` in the frontmatter and ``### `action_name``
    headers per action. We parse loosely — this is documentation, not a
    schema, so we tolerate variations.
    """
    out: dict[str, dict] = {}
    if not CATALOG_DIR.exists():
        return out
    for md in sorted(CATALOG_DIR.glob("*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        module_id = md.stem  # fallback: use file stem
        for line in text.splitlines():
            if "module_id:" in line:
                module_id = line.split(":", 1)[1].strip().strip("`")
                break
        actions: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("### `") and stripped.endswith("`"):
                actions.append(stripped[5:-1].strip())
            elif stripped.startswith("### "):
                # Some catalog files use plain headers without backticks
                cand = stripped[4:].strip()
                if cand and " " not in cand and "_" in cand:
                    actions.append(cand)
        out[module_id] = {"file": md.name, "actions": sorted(set(actions))}
    return out


def _bus_with_everything_wired():
    """Build a bus simulating full home-widget integration.

    Production widget.py wires home + system + viewer + (eagle_ai module);
    DM widget attaches lazily on first download click. For the catalog test
    we include all three so the comparison reflects what an agent would
    actually see at runtime once the user has interacted.
    """
    from modules.EchoMind.secretary import build_command_bus

    class _Stub:
        def is_available(self): return True
        def search(self, **_): pass
        class _Store:
            def get(self, *_): return None
            def get_all(self): return []
            def get_statistics(self): return {}
        state_store = _Store()
        def count(self): return 0
        def tabText(self, _): return ""
        def currentIndex(self): return -1
        def currentWidget(self): return None

    bus = build_command_bus(
        home_widget=_Stub(),
        dm_widget=_Stub(),
        module_launchers={
            "eagle_ai":  lambda e: object(),
            # mpr, printing, education NOT wired here — that's the gap we
            # want this test to surface.
        },
        get_active_patient_tab=lambda: None,
        get_main_tab_widget=lambda: _Stub(),
    )
    return bus


def test_catalog_drift_is_reported():
    """Always PASSes; prints a coverage diff for the human reviewer."""
    catalog = _enumerate_catalog()
    assert catalog, "expected at least one catalog file"

    bus = _bus_with_everything_wired()
    bus_actions = set(bus.actions())

    print()
    print("=== EchoMind catalog vs CommandBus coverage ===")
    print(f"  bus action count: {len(bus_actions)}")
    print()
    print(f"  {'module':<18} {'cat':>4} {'wired':>6} {'missing':<40}")
    print(f"  {'-'*18} {'-'*4:>4} {'-'*6:>6} {'-'*40:<40}")

    total_cat = 0
    total_wired = 0
    for mod_id in sorted(catalog):
        cat_actions = catalog[mod_id]["actions"]
        wired_here = [a for a in cat_actions if a in bus_actions]
        missing = [a for a in cat_actions if a not in bus_actions]
        total_cat += len(cat_actions)
        total_wired += len(wired_here)
        miss_str = ", ".join(missing[:3])
        if len(missing) > 3:
            miss_str += f" (+{len(missing)-3} more)"
        print(f"  {mod_id:<18} {len(cat_actions):>4} {len(wired_here):>6} {miss_str:<40}")

    pct = (100 * total_wired / total_cat) if total_cat else 0.0
    print()
    print(f"  Coverage: {total_wired}/{total_cat} catalog actions wired ({pct:.0f}%)")
    print()


def test_every_bus_action_is_documented_or_acknowledged():
    """Inverse drift: every action the bus exposes should either be in a
    catalog file OR in the explicit infrastructure-action allowlist.

    Infrastructure actions (e.g. ``snapshot_resources``) aren't
    user-facing module commands, so they don't need catalog entries.
    """
    # Infrastructure actions = wired through adapters but NOT user-facing
    # natural-language commands, so they don't need catalog entries.
    #
    # ``download_patient`` and ``open_patient`` are intentionally NOT in this
    # set: they're routed through HomeCommandAdapter but they ARE user-facing
    # parser actions documented in catalog/modules/homepage.md +
    # patient_viewer.md + download.md. The catalog is the canonical home —
    # listing them here too would silently mask catalog drift.
    INFRASTRUCTURE_ACTIONS = {
        # SystemAdapter
        "snapshot_resources", "count_aipacs_processes",
        "count_native_faults_since", "probe_idle_cpu",
        # DownloadAdapter (status/control only — user-facing
        # ``download_patient`` belongs to the catalog)
        "check_download_status", "list_downloads", "download_statistics",
        "cancel_download", "pause_download", "resume_download",
        # ViewerAdapter (read-only)
        "get_active_tab", "list_open_tabs", "get_thumbnails_data",
        "get_active_series", "get_multistudy_info",
        # ModuleAdapter convenience actions
        "open_module", "list_modules",
        # HomeAdapter list-only (open_patient is catalog-documented)
        "list_patients",
    }
    bus = _bus_with_everything_wired()
    catalog = _enumerate_catalog()
    catalog_actions: set[str] = set()
    for d in catalog.values():
        catalog_actions.update(d["actions"])

    undocumented = []
    for action in bus.actions():
        if action in INFRASTRUCTURE_ACTIONS:
            continue
        if action in catalog_actions:
            continue
        undocumented.append(action)

    # This is a soft warning, not a fail — emit but don't break the build.
    if undocumented:
        print(f"\n  Soft warning: {len(undocumented)} bus action(s) "
              f"missing from catalog: {sorted(undocumented)}")

    # Hard rule: zero collisions between infrastructure actions and
    # documented module actions. If a module catalog claims an
    # infrastructure action name, that's a real bug.
    collisions = sorted(INFRASTRUCTURE_ACTIONS & catalog_actions)
    assert not collisions, (
        f"Infrastructure action(s) collide with module catalog: {collisions}"
    )
