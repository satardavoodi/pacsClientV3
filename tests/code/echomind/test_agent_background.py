"""Guards for the Secretary background agent layer (2026-06-11).

Contract pinned here:

  1. BackgroundTaskEngine: bounded workers, MEDIUM-before-LOW ordering,
     failure/warning/cancel states, listener events, never raises.
  2. ui_bridge inline mode (no Qt): callables run inline, exceptions
     are captured.
  3. verification term matching + OCR capability probe degrade safely.
  4. agent_tasks web-search workflow verifies page text via the widget's
     controller API and reports warning when verification fails.
  5. content_search searches DB sources + files with the optional
     extractors, reports skipped extractors, caches file text.
  6. CredentialVault stores secrets ONLY via Identity secure_store
     (no password in the JSON index), finds entries by site, migrates
     legacy base64 bookmarks.
  7. Bus wiring: engine getter routes web_search/open_url to background
     tasks; AgentCommandAdapter actions registered; validator accepts;
     parser maps the new voice commands; legacy paths untouched.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import pydantic  # noqa: F401
except ImportError:  # pragma: no cover
    import pytest
    pytest.skip("pydantic not installed", allow_module_level=True)

import pytest

from modules.EchoMind.secretary.background.task_engine import (  # noqa: E402
    BackgroundTaskEngine, PRIORITY_LOW, PRIORITY_MEDIUM, TaskResult,
    TaskState,
)
from modules.EchoMind.secretary.background import ui_bridge  # noqa: E402
from modules.EchoMind.secretary.background import verification as V  # noqa: E402
from modules.EchoMind.secretary.command_envelope import CommandPlan  # noqa: E402


def _cp(action: str, entities: dict | None = None) -> CommandPlan:
    return CommandPlan(action=action, entities=entities or {},
                       confidence=0.9, needs_confirmation=False,
                       reason="test")


# ── 1. task engine ──────────────────────────────────────────────────────────

def test_engine_runs_task_and_reports_states():
    engine = BackgroundTaskEngine(max_workers=1)
    events: list[tuple[str, str]] = []
    engine.add_listener(lambda t, s: events.append((t.task_id, s)))
    tid = engine.submit("t", "web_browser",
                        lambda task: TaskResult(ok=True, message="done"))
    task = engine.wait(tid, timeout=10)
    assert task.state == TaskState.COMPLETED
    states = [s for (i, s) in events if i == tid]
    assert states == ["queued", "working", "completed"]
    engine.shutdown()


def test_engine_failure_warning_and_crash_states():
    engine = BackgroundTaskEngine(max_workers=1)
    t_fail = engine.submit("f", "m", lambda t: TaskResult(ok=False, message="no"))
    t_warn = engine.submit("w", "m",
                           lambda t: TaskResult(ok=True, warning=True))
    def _boom(t):
        raise RuntimeError("boom")
    t_crash = engine.submit("c", "m", _boom)
    assert engine.wait(t_fail, 10).state == TaskState.FAILED
    assert engine.wait(t_warn, 10).state == TaskState.WARNING
    crashed = engine.wait(t_crash, 10)
    assert crashed.state == TaskState.FAILED
    assert "boom" in crashed.result.message
    engine.shutdown()


def test_engine_priority_medium_before_low():
    engine = BackgroundTaskEngine(max_workers=1)
    gate = threading.Event()
    order: list[str] = []
    engine.submit("blocker", "m",
                  lambda t: (gate.wait(10), TaskResult(ok=True))[-1])
    time.sleep(0.2)  # blocker is now occupying the single worker
    engine.submit("low", "m",
                  lambda t: (order.append("low"), TaskResult(ok=True))[-1],
                  priority=PRIORITY_LOW)
    t_med = engine.submit(
        "med", "m",
        lambda t: (order.append("med"), TaskResult(ok=True))[-1],
        priority=PRIORITY_MEDIUM)
    gate.set()
    engine.wait(t_med, 10)
    time.sleep(0.3)
    assert order and order[0] == "med"
    engine.shutdown()


def test_engine_cancel_queued_task():
    engine = BackgroundTaskEngine(max_workers=1)
    gate = threading.Event()
    blocker = engine.submit(
        "blocker", "m", lambda t: (gate.wait(10), TaskResult(ok=True))[-1])
    time.sleep(0.2)
    victim = engine.submit("victim", "m", lambda t: TaskResult(ok=True))
    assert engine.cancel(victim)
    gate.set()
    engine.wait(blocker, 10)
    assert engine.get(victim).state == TaskState.CANCELLED
    engine.shutdown()


# ── 2. ui_bridge inline mode ────────────────────────────────────────────────

def test_ui_bridge_inline_without_qt():
    ui_bridge._reset_for_tests()
    ok, val = ui_bridge.run_on_ui(lambda: 41 + 1)
    assert ok and val == 42
    ok, val = ui_bridge.run_on_ui(lambda: 1 / 0)
    assert not ok and isinstance(val, ZeroDivisionError)


# ── 3. verification helpers ────────────────────────────────────────────────

def test_verify_terms_in_text():
    text = "Best practices for ACL reconstruction surgery and recovery"
    ok, ratio = V.verify_terms_in_text(text, "ACL reconstruction")
    assert ok and ratio == 1.0
    ok, ratio = V.verify_terms_in_text("totally unrelated", "ACL reconstruction")
    assert not ok and ratio == 0.0


def test_ocr_probe_never_raises():
    assert V.ocr_available() in (True, False)
    assert V.ocr_image("definitely_missing.png") == ""


# ── 4. web-search workflow (fake widget, inline UI bridge) ─────────────────

class _FakePixmap:
    def isNull(self):
        return True  # → screenshot path returns ''


class _FakeWebView:
    def grab(self):
        return _FakePixmap()

    class _U:
        def toString(self):
            return "https://www.google.com/search?q=x"

    def url(self):
        return self._U()


class _FakePage:
    def __init__(self, text):
        self._text = text

    def toPlainText(self, cb):
        cb(self._text)


class _FakeBrowserWidget:
    def __init__(self, page_text):
        self._is_loading = False
        self.page = _FakePage(page_text)
        self.web_view = _FakeWebView()
        self.searched: list[str] = []
        self.loaded: list[str] = []

    def search_web(self, q):
        self.searched.append(q)
        return True

    def load_url(self, u):
        self.loaded.append(u)
        return True


def test_web_search_task_verifies_page_text():
    ui_bridge._reset_for_tests()
    from modules.EchoMind.secretary.background.agent_tasks import (
        make_web_search_task,
    )
    widget = _FakeBrowserWidget(
        "meniscus tear MRI findings — results about meniscus tears")
    engine = BackgroundTaskEngine(max_workers=1)
    tid = engine.submit(
        "s", "web_browser",
        make_web_search_task("meniscus tear MRI", lambda e: widget))
    task = engine.wait(tid, timeout=60)
    assert task.state == TaskState.COMPLETED, (task.state, task.result)
    assert widget.searched == ["meniscus tear MRI"]
    assert task.result.data["term_ratio"] >= 0.5
    engine.shutdown()


def test_web_search_task_warns_when_unverified():
    ui_bridge._reset_for_tests()
    from modules.EchoMind.secretary.background.agent_tasks import (
        make_web_search_task,
    )
    widget = _FakeBrowserWidget("blank page no relation whatsoever")
    engine = BackgroundTaskEngine(max_workers=1)
    tid = engine.submit(
        "s", "web_browser",
        make_web_search_task("zygomatic arch fracture", lambda e: widget,
                             max_attempts=1))
    task = engine.wait(tid, timeout=60)
    assert task.state == TaskState.WARNING
    engine.shutdown()


def test_web_search_task_unavailable_module_fails():
    ui_bridge._reset_for_tests()
    from modules.EchoMind.secretary.background.agent_tasks import (
        make_web_search_task,
    )
    engine = BackgroundTaskEngine(max_workers=1)
    tid = engine.submit("s", "web_browser",
                        make_web_search_task("anything", lambda e: None))
    task = engine.wait(tid, timeout=60)
    assert task.state == TaskState.FAILED
    assert "not available" in task.result.message
    engine.shutdown()


# ── 5. education content search ────────────────────────────────────────────

def test_content_search_files_and_db(tmp_path, monkeypatch):
    from modules.education import content_search as CS

    root = tmp_path / "edu"
    (root / "course_1" / "assets").mkdir(parents=True)
    (root / "course_1" / "assets" / "acl_notes.txt").write_text(
        "Detailed ACL reconstruction rehabilitation protocol", encoding="utf-8")
    monkeypatch.setattr(CS, "_education_root", lambda: root)

    import modules.education.course_database as cdb
    monkeypatch.setattr(cdb, "get_all_courses", lambda: [
        {"course_pk": 1, "course_name": "Knee MRI Course",
         "description": "Covers ACL reconstruction grading", "author": "",
         "tags": "knee"},
        {"course_pk": 2, "course_name": "Chest X-ray", "description": "",
         "author": "", "tags": ""},
    ])
    monkeypatch.setattr(cdb, "get_slides_for_course", lambda pk: [])
    import modules.education.case_of_day_database as codb
    monkeypatch.setattr(codb, "search_cases", lambda query="", **kw: [])

    report = CS.search_education_content("ACL reconstruction")
    sources = {r["source"] for r in report["results"]}
    assert "course" in sources
    assert "file:text" in sources
    titles = [r["title"] for r in report["results"]]
    assert "Knee MRI Course" in titles and "acl_notes.txt" in titles
    assert all("Chest" not in t for t in titles)
    # Cache file created
    assert (root / "content_index.json").exists()


def test_content_search_pptx_extraction(tmp_path, monkeypatch):
    pptx_mod = pytest.importorskip("pptx")
    from modules.education import content_search as CS

    root = tmp_path / "edu"
    root.mkdir()
    prs = pptx_mod.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "ACL reconstruction techniques"
    deck = root / "lecture.pptx"
    prs.save(str(deck))
    monkeypatch.setattr(CS, "_education_root", lambda: root)

    import modules.education.course_database as cdb
    monkeypatch.setattr(cdb, "get_all_courses", lambda: [])
    monkeypatch.setattr(cdb, "get_slides_for_course", lambda pk: [])
    import modules.education.case_of_day_database as codb
    monkeypatch.setattr(codb, "search_cases", lambda query="", **kw: [])

    report = CS.search_education_content("ACL reconstruction")
    assert any(r["source"] == "file:pptx" for r in report["results"])


# ── 6. credential vault ────────────────────────────────────────────────────

@pytest.fixture()
def fake_secure_store(monkeypatch):
    store: dict[str, dict] = {}
    import modules.Identity.secure_store as ss
    monkeypatch.setattr(
        ss, "save_secret",
        lambda prov, sid, payload: store.update({f"{prov}:{sid}": payload}) or True)
    monkeypatch.setattr(
        ss, "load_secret", lambda prov, sid: store.get(f"{prov}:{sid}"))
    monkeypatch.setattr(
        ss, "delete_secret",
        lambda prov, sid: store.pop(f"{prov}:{sid}", None))
    return store


def test_vault_no_plaintext_in_index(tmp_path, fake_secure_store):
    from modules.web_browser.credential_vault import CredentialVault
    vault = CredentialVault(index_path=tmp_path / "idx.json")
    entry = vault.add("https://portal.example.com/login", "vahid",
                      "S3cret!pass", label="Portal")
    assert entry and entry["id"]
    raw = (tmp_path / "idx.json").read_text(encoding="utf-8")
    assert "S3cret!pass" not in raw          # the contract
    assert vault.get_password(entry["id"]) == "S3cret!pass"
    found = vault.find_for_site("portal.example.com")
    assert found and found["id"] == entry["id"]
    assert vault.find_for_site("portal") is not None     # label/host substring
    assert vault.delete(entry["id"])
    assert vault.get_password(entry["id"]) == ""


def test_vault_migrates_legacy_base64(tmp_path, fake_secure_store):
    import base64
    from modules.web_browser.credential_vault import CredentialVault
    vault = CredentialVault(index_path=tmp_path / "idx.json")
    legacy = base64.b64encode(b"oldpass").decode()
    entry = vault.migrate_bookmark("https://x.example.com", "u", legacy, "X")
    assert entry is not None
    assert vault.get_password(entry["id"]) == "oldpass"


# ── 7. bus wiring + validator + parser ──────────────────────────────────────

def test_browser_adapter_background_route():
    ui_bridge._reset_for_tests()
    from modules.EchoMind.secretary.adapters.browser_command_adapter import (
        BrowserCommandAdapter,
    )
    widget = _FakeBrowserWidget("meniscus findings everywhere meniscus")
    engine = BackgroundTaskEngine(max_workers=1)
    adapter = BrowserCommandAdapter(
        open_browser_launcher=lambda e: widget,
        engine_getter=lambda: engine,
    )
    res = adapter.web_search(_cp("web_search", {"query": "meniscus"}), {})
    assert res.ok and res.data["background"] is True
    task = engine.wait(res.data["task_id"], timeout=60)
    assert task.state in (TaskState.COMPLETED, TaskState.WARNING)
    res2 = adapter.open_url(_cp("open_url", {"url": "example.com"}), {})
    assert res2.ok and res2.data["background"] is True
    engine.wait(res2.data["task_id"], timeout=60)
    engine.shutdown()


def test_agent_adapter_actions_and_bus_registration():
    from modules.EchoMind.secretary import build_command_bus
    from modules.EchoMind.secretary.adapters.agent_command_adapter import (
        AGENT_ACTIONS,
    )
    engine = BackgroundTaskEngine(max_workers=1)
    bus = build_command_bus(
        module_launchers={"web_browser": lambda e: None},
        task_engine_getter=lambda: engine,
    )
    actions = set(bus.actions())
    for a in AGENT_ACTIONS:
        assert a in actions, a
    # missing site → typed error
    res = bus.execute(_cp("login_website", {}))
    assert not res.ok and res.error_code == "MISSING_SITE"
    # task status works
    res = bus.execute(_cp("agent_task_status", {}))
    assert res.ok
    # no engine → adapter not registered
    bus_off = build_command_bus(module_launchers={"web_browser": lambda e: None})
    assert "login_website" not in set(bus_off.actions())
    engine.shutdown()


def test_validator_accepts_agent_actions():
    from modules.EchoMind.secretary.validator import (
        _BUS_ALLOWED_ACTIONS, validate_plan,
    )
    for action in ("login_website", "search_education_content",
                   "agent_task_status", "cancel_agent_task"):
        assert action in _BUS_ALLOWED_ACTIONS
        plan = {"action": action, "entities": {"site": "x"},
                "confidence": 0.9, "needs_confirmation": False,
                "reason": "test"}
        normalized, errors = validate_plan(plan)
        assert not errors and normalized is not None


def test_parser_agent_commands():
    from modules.EchoMind.secretary.parser_rules import parse_command_rule

    plan = parse_command_rule("Find all ACL educational materials")
    assert plan and plan["action"] == "search_education_content"
    assert plan["entities"]["query"].lower() == "acl"

    plan = parse_command_rule(
        "find all educational resources discussing ACL reconstruction")
    assert plan and plan["action"] == "search_education_content"
    assert plan["entities"]["query"].lower() == "acl reconstruction"

    plan = parse_command_rule("log into website myhospital portal")
    assert plan and plan["action"] == "login_website"
    assert "myhospital" in plan["entities"]["site"]

    assert parse_command_rule("task status")["action"] == "agent_task_status"
    assert parse_command_rule("cancel the search")["action"] == "cancel_agent_task"

    # Legacy paths untouched
    plan = parse_command_rule("search education for spine anatomy")
    assert plan and plan["action"] == "search_education"
    plan = parse_command_rule("open patient code 12345")
    assert plan and plan["action"] == "open_patient"
    plan = parse_command_rule("Search rotator cuff tear on Google")
    assert plan and plan["action"] == "web_search"


# ── notifications mapping ───────────────────────────────────────────────────

def test_notify_task_finished_mapping(monkeypatch):
    from modules.EchoMind.secretary.background import notify as N
    posted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        N, "post_notification",
        lambda title, body="", kind="": posted.append((kind, title)) or 1)

    class _T:
        state = "completed"
        name = "Google search: x"
        result = None
    class _R:
        message = "done"
        artifacts = ["a.png"]
    N.notify_task_finished(_T(), _R())
    _T.state = "failed"
    N.notify_task_finished(_T(), _R())
    kinds = [k for k, _ in posted]
    assert kinds == [N.KIND_AGENT_DONE, N.KIND_AGENT_FAIL]
