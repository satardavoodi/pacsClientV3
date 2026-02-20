from __future__ import annotations

from pathlib import Path


def _load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


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

    return (
        f"Language hint: {language or 'auto'}\n\n"
        f"{action_registry}\n\n"
        f"{entity_schema}\n\n"
        f"{confirmation_policy}\n\n"
        f"{output_contract}\n\n"
        f"Module map:\n{module_map or 'module_map unavailable'}"
    )
