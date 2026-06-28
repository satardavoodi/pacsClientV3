from __future__ import annotations

from pathlib import Path

from .config import routing_v2_enabled


def _load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


# Routing-v2 (2026-06-28): the single-shot fallback parser historically advertised
# ONLY the 3 patient actions, so the LLM could never propose a web/browser/viewer
# action on the fallback path (it did not know they existed). When the flag is on,
# advertise the full executable capability set. Validator allowlists already accept
# these (validator._BUS_ALLOWED_ACTIONS); this only tells the LLM they exist.
_V2_CAPABILITY_REGISTRY = """
Additional capabilities (choose the one matching the user's intent — do NOT default
to a patient action when the user wants something else):
- web_search {query}: search the internet/Google for information or a medical topic.
- open_url {url}: open a specific website/URL.
- open_browser: open/activate the in-app web browser.
- browser_back | browser_forward | refresh_page: browser navigation.
- browser_get_text | browser_get_links | browser_dom_summary: read the current page.
- browser_find_element {selector} | browser_fill_field {selector,value}
  | browser_click {selector} | browser_submit_form: interact with page fields/buttons.
- open_module {module}: open a module (mpr, eagle, printing, education, web_browser).
- change_series {series_index|series_number, viewport} | scroll_slices {direction}
  | switch_tab | change_layout: viewer commands on an open study.
- start_report | transcribe_voice | generate_report | send_report_to_pacs: reporting.
- search_education {query} | open_courses | open_consultation | open_case_of_day: education.
ROUTING RULE: "search/look up/google X on the internet/online" or a medical-topic
lookup → web_search (NOT a patient action). A patient action is only for a specific
patient (name/code) or a patient-list filter (date/modality). If you cannot tell which
domain the user means, return action "unknown" with a one-sentence reason so the app
can ask — never guess a patient search.
""".strip()


def build_prompt_context(language: str = "auto") -> str:
    """Build a dynamic preface/context package for Secretary action parsing."""
    base = Path(__file__).resolve().parent
    module_map = _load_text(base / "module_map.yaml")

    action_registry = """
Allowed actions:
- list_patients: Search/list rows with optional source/date/modality filtering.
- open_patient: Resolve a patient and open it (side effect, confirmation required).
- download_patient: Resolve a patient and queue download (side effect, confirmation required).
""".strip()

    entity_schema = """
Entity schema by action:
- list_patients: source, date, modality
- open_patient: source, patient_code, resolved_patient
- download_patient: source, patient_code, use_context_patient, resolved_patient

Entity notes:
- source in {active_tab, local, server}
- date in {'today', 'yyyy-mm-dd', 'yyyymmdd', 'start..end'}
- MRI synonyms must normalize to modality='MR'
""".strip()

    confirmation_policy = """
Confirmation policy:
- open_patient => needs_confirmation=true
- download_patient => needs_confirmation=true
- list_patients => needs_confirmation=false
""".strip()

    output_contract = """
Output contract:
- Return JSON only (no markdown, no prose).
- Required top-level fields:
  action, entities, confidence, needs_confirmation, reason
""".strip()

    # Flag-gated: advertise the full capability set on the fallback path (off →
    # byte-identical legacy: only the 3 patient actions are described).
    caps = f"{_V2_CAPABILITY_REGISTRY}\n\n" if routing_v2_enabled() else ""

    return (
        f"Language hint: {language or 'auto'}\n\n"
        f"{action_registry}\n\n"
        f"{caps}"
        f"{entity_schema}\n\n"
        f"{confirmation_policy}\n\n"
        f"{output_contract}\n\n"
        f"Module map:\n{module_map or 'module_map unavailable'}"
    )
