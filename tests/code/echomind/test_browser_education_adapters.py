"""Guards for the Web Browser + Education CommandBus adapters (2026-06-11).

Contract pinned here:

  1. BrowserCommandAdapter: web_search uses Google through the widget's
     controller API (search_web), open_url normalizes/rejects URLs, nav
     actions call navigate_back/forward/reload_page, and an unavailable
     module yields a typed MODULE_UNAVAILABLE envelope — never silence.
  2. EducationCommandAdapter: consultation / consultant directory /
     courses / case of the day / library search drive the Education
     widget's own navigation API; a gated-off Online Consultation tab
     yields CONSULTATION_UNAVAILABLE.
  3. bus_factory registers both adapters from the ``web_browser`` /
     ``education`` module launchers.
  4. The validator accepts the new bus actions.
  5. The rule parser maps the initial voice commands — while the legacy
     "open patient 123" / "open education" / list paths are untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import pydantic  # noqa: F401
except ImportError:  # pragma: no cover
    import pytest
    pytest.skip("pydantic not installed", allow_module_level=True)

from modules.EchoMind.secretary.adapters.browser_command_adapter import (  # noqa: E402
    BROWSER_ACTIONS,
    BrowserCommandAdapter,
    normalize_url,
)
from modules.EchoMind.secretary.adapters.education_command_adapter import (  # noqa: E402
    EDUCATION_ACTIONS,
    EducationCommandAdapter,
)
from modules.EchoMind.secretary.command_envelope import CommandPlan  # noqa: E402
from modules.EchoMind.secretary.parser_rules import parse_command_rule  # noqa: E402
from modules.EchoMind.secretary.validator import (  # noqa: E402
    _BUS_ALLOWED_ACTIONS,
    validate_plan,
)


def _cp(action: str, entities: dict | None = None) -> CommandPlan:
    return CommandPlan(action=action, entities=entities or {},
                       confidence=0.9, needs_confirmation=False,
                       reason="test")


# ── fakes ───────────────────────────────────────────────────────────────────

class _FakeBrowser:
    def __init__(self):
        self.calls: list[tuple] = []

    def search_web(self, query):
        self.calls.append(("search_web", query))
        return True

    def load_url(self, url):
        self.calls.append(("load_url", url))
        return True

    def navigate_back(self):
        self.calls.append(("navigate_back",))

    def navigate_forward(self):
        self.calls.append(("navigate_forward",))

    def reload_page(self):
        self.calls.append(("reload_page",))


class _FakeTabWidget:
    def __init__(self):
        self.current = None

    def setCurrentWidget(self, w):
        self.current = w


class _FakeLibraryPage:
    def __init__(self):
        self.search_input = self
        self._text = ""

    def setText(self, t):  # acts as its own search_input
        self._text = t


class _FakeEducation:
    def __init__(self, consultation=True):
        self.tab_widget = _FakeTabWidget()
        self.library_page = _FakeLibraryPage()
        self.mycourses_page = object()
        self.case_of_day_tab = object()
        self.online_consultation_page = object() if consultation else None
        self.consult_calls: list = []

    def show_online_consultation(self, section=None):
        self.consult_calls.append(section)


# ── 1. browser adapter ──────────────────────────────────────────────────────

def test_web_search_uses_widget_google_search():
    w = _FakeBrowser()
    a = BrowserCommandAdapter(open_browser_launcher=lambda e: w)
    res = a.web_search(_cp("web_search", {"query": "rotator cuff tear"}), {})
    assert res.ok and res.data["engine"] == "google"
    assert ("search_web", "rotator cuff tear") in w.calls


def test_web_search_missing_query():
    a = BrowserCommandAdapter(open_browser_launcher=lambda e: _FakeBrowser())
    res = a.web_search(_cp("web_search", {}), {})
    assert not res.ok and res.error_code == "MISSING_QUERY"


def test_browser_unavailable_is_typed_not_silent():
    a = BrowserCommandAdapter(open_browser_launcher=lambda e: None)
    for action, method in BROWSER_ACTIONS.items():
        entities = {"query": "x"} if action == "web_search" else {"url": "example.com"}
        res = getattr(a, method)(_cp(action, entities), {})
        assert not res.ok and res.error_code == "MODULE_UNAVAILABLE", action
        assert res.message  # clear user-facing message


def test_open_url_normalizes_and_rejects():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("https://a.b/c") == "https://a.b/c"
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("file:///etc/passwd") == ""
    w = _FakeBrowser()
    a = BrowserCommandAdapter(open_browser_launcher=lambda e: w)
    ok = a.open_url(_cp("open_url", {"url": "radiopaedia.org"}), {})
    assert ok.ok and ("load_url", "https://radiopaedia.org") in w.calls
    bad = a.open_url(_cp("open_url", {"url": "javascript:alert(1)"}), {})
    assert not bad.ok and bad.error_code == "INVALID_URL"


def test_browser_navigation_actions():
    w = _FakeBrowser()
    a = BrowserCommandAdapter(open_browser_launcher=lambda e: w)
    assert a.browser_back(_cp("browser_back"), {}).ok
    assert a.browser_forward(_cp("browser_forward"), {}).ok
    assert a.refresh_page(_cp("refresh_page"), {}).ok
    names = [c[0] for c in w.calls]
    assert names == ["navigate_back", "navigate_forward", "reload_page"]


# ── 2. education adapter ────────────────────────────────────────────────────

def test_open_consultation_and_profiles():
    edu = _FakeEducation(consultation=True)
    a = EducationCommandAdapter(open_education_launcher=lambda e: edu)
    assert a.open_consultation(_cp("open_consultation"), {}).ok
    assert a.show_consultant_profiles(_cp("show_consultant_profiles"), {}).ok
    assert edu.consult_calls == [None, "directory"]


def test_consultation_gated_off_is_typed():
    edu = _FakeEducation(consultation=False)
    a = EducationCommandAdapter(open_education_launcher=lambda e: edu)
    res = a.open_consultation(_cp("open_consultation"), {})
    assert not res.ok and res.error_code == "CONSULTATION_UNAVAILABLE"


def test_open_courses_and_case_of_day_switch_tabs():
    edu = _FakeEducation()
    a = EducationCommandAdapter(open_education_launcher=lambda e: edu)
    assert a.open_courses(_cp("open_courses"), {}).ok
    assert edu.tab_widget.current is edu.mycourses_page
    assert a.open_case_of_day(_cp("open_case_of_day"), {}).ok
    assert edu.tab_widget.current is edu.case_of_day_tab


def test_search_education_sets_library_query():
    edu = _FakeEducation()
    a = EducationCommandAdapter(open_education_launcher=lambda e: edu)
    res = a.search_education(_cp("search_education", {"query": "spine"}), {})
    assert res.ok
    assert edu.tab_widget.current is edu.library_page
    assert edu.library_page._text == "spine"
    missing = a.search_education(_cp("search_education", {}), {})
    assert not missing.ok and missing.error_code == "MISSING_QUERY"


def test_education_unavailable_is_typed():
    a = EducationCommandAdapter(open_education_launcher=lambda e: None)
    res = a.open_courses(_cp("open_courses"), {})
    assert not res.ok and res.error_code == "MODULE_UNAVAILABLE"


# ── 3. bus_factory wiring ───────────────────────────────────────────────────

def test_bus_factory_registers_browser_and_education():
    from modules.EchoMind.secretary import build_command_bus
    bus = build_command_bus(module_launchers={
        "web_browser": lambda e: _FakeBrowser(),
        "education":   lambda e: _FakeEducation(),
    })
    actions = set(bus.actions())
    for a in (set(BROWSER_ACTIONS) | set(EDUCATION_ACTIONS)):
        assert a in actions, a
    # end-to-end through the bus
    res = bus.execute(_cp("web_search", {"query": "ct dose"}))
    assert res.ok


def test_bus_factory_without_launchers_has_no_browser_actions():
    from modules.EchoMind.secretary import build_command_bus
    bus = build_command_bus()
    actions = set(bus.actions())
    assert not (set(BROWSER_ACTIONS) & actions)
    assert not (set(EDUCATION_ACTIONS) & actions)


# ── 4. validator ────────────────────────────────────────────────────────────

def test_validator_accepts_new_actions():
    for action in (set(BROWSER_ACTIONS) | set(EDUCATION_ACTIONS)):
        assert action in _BUS_ALLOWED_ACTIONS, action
        plan = {"action": action, "entities": {"query": "x"},
                "confidence": 0.9, "needs_confirmation": False,
                "reason": "test"}
        normalized, errors = validate_plan(plan)
        assert not errors, (action, [e.to_dict() for e in errors])
        assert normalized is not None


# ── 5. rule parser ──────────────────────────────────────────────────────────

def _action_of(text: str) -> str | None:
    plan = parse_command_rule(text)
    return plan["action"] if plan else None


def test_parser_web_search_variants():
    for text, query in [
        ("Search rotator cuff tear on Google", "rotator cuff tear"),
        ("search for chest xray grading on the web", "chest xray grading"),
        ("Open Google and search ct dose limits", "ct dose limits"),
        ("google brain mri sequences", "brain mri sequences"),
    ]:
        plan = parse_command_rule(text)
        assert plan and plan["action"] == "web_search", text
        assert plan["entities"]["query"].lower() == query, text


def test_parser_web_search_persian():
    plan = parse_command_rule("در گوگل جستجو کن آناتومی شانه")
    assert plan and plan["action"] == "web_search"
    assert "آناتومی شانه" in plan["entities"]["query"]


def test_parser_open_url_and_browser():
    plan = parse_command_rule("Open this website: radiopaedia.org")
    assert plan and plan["action"] == "open_url"
    assert plan["entities"]["url"].startswith("radiopaedia.org")
    assert _action_of("open the browser") == "open_browser"
    assert _action_of("go back") == "browser_back"
    assert _action_of("go forward") == "browser_forward"
    assert _action_of("refresh the page") == "refresh_page"


def test_parser_education_commands():
    assert _action_of("open consultation") == "open_consultation"
    assert _action_of("show my consultations") == "open_consultation"
    assert _action_of("show consultant profiles") == "show_consultant_profiles"
    assert _action_of("open courses") == "open_courses"
    assert _action_of("open case of the day") == "open_case_of_day"
    plan = parse_command_rule("search education for spine anatomy")
    assert plan and plan["action"] == "search_education"
    assert plan["entities"]["query"] == "spine anatomy"


def test_parser_legacy_paths_untouched():
    plan = parse_command_rule("open patient code 12345")
    assert plan and plan["action"] == "open_patient"
    assert plan["entities"].get("patient_code") == "12345"
    plan = parse_command_rule("open education")
    assert plan and plan["action"] == "open_module"
    assert plan["entities"]["module"] == "education"
    plan = parse_command_rule("open mpr")
    assert plan and plan["action"] == "open_mpr" or plan["action"] == "open_module"
    plan = parse_command_rule("show today's patients")
    assert plan and plan["action"] == "list_patients"
    plan = parse_command_rule("download patient code 999")
    assert plan and plan["action"] == "download_patient"
