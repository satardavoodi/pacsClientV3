"""The Iran Nobat AI backend — the default, and the one a clinic never configures.

Everything about this backend is fixed at build time: endpoint, model, and the
generation parameters. A receptionist picking «هوش مصنوعی ایران نوبت» in the
settings gets a working assistant with nothing else to fill in, which is the
whole point of this module.

The key
-------
The key ships inside the build, so the customer has nothing to enter. It does
NOT live in this file, and it must never be committed:

    reception_crm/llm/company_key.txt      <- one line, the key, gitignored
    reception_crm/llm/company_key.example.txt  <- committed, a placeholder

That split matters more than it looks. This repository is on GitHub, and a key
committed once stays in the history forever — rotating it later does not remove
it from the old commits. Keeping the value in an untracked file means the build
carries the secret while the repository never has.

Resolution order, first hit wins:

1. ``RECEPTION_LLM_API_KEY`` in the environment — for development and for
   overriding a build without rebuilding it.
2. ``company_key.txt`` beside this module (or beside the frozen executable,
   which is where PyInstaller puts it — see the ``datas`` entry in the .spec).
3. A key a technician saved in the settings file, if one was ever entered.

Anyone holding an installer can extract the bundled key. That is a property of
the "zero configuration for the customer" decision, not a bug — treat the key as
rotatable, watch the usage on it, and re-issue by shipping a new build.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Shown wherever the backend is named. One label, everywhere.
DISPLAY_NAME_FA = "هوش مصنوعی ایران نوبت"
DISPLAY_NAME = "Iran Nobat AI"

#: Transport. Same values the AI-PACS workstation uses.
API_URL = "https://api.gapgpt.app/v1/chat/completions"

#: The default model. Measured against this agent's two jobs on 2026-08-23,
#: through the live GapGPT endpoint, before being changed:
#:
#:                        answer-writing        tool selection
#:   gpt-5.2              8.7 s, 571 tokens     4.9 s, 279 tokens
#:   gpt-5.6-terra        3.7 s, 240 tokens     4.5 s, 192 tokens
#:
#: Both produce well-formed `agent-md/1` and neither invented a figure that was
#: not in the data. terra is ~2.4x faster at writing the answer, which is the
#: call a clinician waits on.
#:
#: There is a second reason. `gpt-5.2` is a REASONING model and its reasoning
#: tokens come out of the same `max_tokens` budget as the answer: asked a
#: trivial question with a 20-token budget it spent all 20 thinking and returned
#: **empty content** with `finish_reason=length`. At the production budget of
#: 1200 that is comfortable, but the failure mode is real and silent -- an empty
#: answer, no error. terra used 0 reasoning tokens on the same trivial call.
MODEL = "gpt-5.6-terra"

#: Generation parameters. The interpreter is a classifier choosing a tool, not a
#: writer, so temperature is 0 — a clinic must not get a different answer to the
#: same question on a Tuesday.
TIMEOUT = 60
TEMPERATURE = 0.0
MAX_TOKENS = 1200

KEY_FILE_NAME = "company_key.txt"


def _candidate_key_files() -> tuple[Path, ...]:
    """Where the bundled key can be, most specific first.

    Resolved per call rather than at import: a Windows service starts in
    ``C:\\Windows\\System32``, so a relative path never matches, and the frozen
    layout differs from the source layout.
    """
    here = Path(__file__).resolve().parent
    paths = [here / KEY_FILE_NAME]

    # PyInstaller onefile unpacks datas into _MEIPASS; onedir puts them beside
    # the executable. Cover both, plus the executable's own directory.
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        paths.append(Path(bundle) / "reception_crm" / "llm" / KEY_FILE_NAME)
        paths.append(Path(bundle) / KEY_FILE_NAME)
    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / KEY_FILE_NAME)
    return tuple(paths)


def bundled_key() -> str:
    """The key shipped with this build, or an empty string."""
    for path in _candidate_key_files():
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        # The example file is committed with a placeholder; treat it as absent
        # so a developer checkout does not look configured when it is not.
        if value and not value.startswith("<") and not value.upper().startswith("REPLACE"):
            return value
    return ""


def api_key(stored: str = "") -> str:
    """Resolve the key. ``stored`` is a technician-entered fallback."""
    return os.environ.get("RECEPTION_LLM_API_KEY", "").strip() or bundled_key() or (stored or "").strip()


def is_available(stored: str = "") -> bool:
    """Can this build actually reach the company backend?"""
    return bool(api_key(stored))


def status(stored: str = "") -> dict[str, str]:
    """Where the active key came from — for the settings screen and support.

    Never returns the key itself, only its origin and length, so this can be
    shown on screen and pasted into a support message safely.
    """
    if os.environ.get("RECEPTION_LLM_API_KEY", "").strip():
        source = "environment"
    elif bundled_key():
        source = "bundled"
    elif (stored or "").strip():
        source = "stored"
    else:
        source = "missing"
    return {
        "source": source,
        "display_name": DISPLAY_NAME,
        "display_name_fa": DISPLAY_NAME_FA,
        "model": MODEL,
        "length": str(len(api_key(stored))),
    }
