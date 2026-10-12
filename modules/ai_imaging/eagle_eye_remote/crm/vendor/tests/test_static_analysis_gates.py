"""The linter and the type checker are configured, and the config is a ratchet.

Neither tool runs here — that would make the suite slow and would fail on a
machine where they are not installed. What this pins is that the configuration
still exists and still says what it was set up to say, because the failure mode
for a ratchet is not "it goes red", it is "someone widens the exclusion until it
cannot go red".

Both gates earned their place by finding real things:

  * ruff's `F821` found a `NameError` that had been shipping in
    `voice_gateway.py`, hidden by a broad `except` that made a missing import
    and a wrong password look identical;
  * ruff's `PLE2515` found five literal invisible codepoints inside a regex
    character class in the Persian text stripper;
  * mypy found that `ToolRegistry.list` and `ConversationStore.list` shadow the
    builtin inside their own class bodies, so `-> list[...]` written there
    resolved to the method. Those annotations were nonsense and no reader had
    noticed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def config() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_the_linter_is_configured_with_the_rules_that_found_defects():
    rules = set(config()["tool"]["ruff"]["lint"]["select"])

    # F caught the shipped NameError; PLE caught the invisible Unicode.
    assert {"F", "PLE"} <= rules, rules
    assert "E9" in rules, "syntax errors must always be caught"


def test_the_type_checker_is_configured_over_the_data_path():
    mypy = config()["tool"]["mypy"]

    assert mypy["files"] == ["reception_crm"]
    # Only the Qt layer is excused. If this ever grows to cover `core`, `llm`,
    # `local` or `adapters`, the gate has stopped guarding the code that
    # produces clinical answers.
    assert mypy["exclude"] == "reception_crm/desktop/"


def test_both_gates_are_installable():
    """A gate nobody can run is a gate nobody runs."""
    dev = config()["project"]["optional-dependencies"]["dev"]
    joined = " ".join(dev)

    assert "ruff" in joined
    assert "mypy" in joined
    assert "pytest" in joined


def test_the_lint_exclusions_stay_narrow():
    """Excluding source would make a green run meaningless."""
    excluded = config()["tool"]["ruff"]["extend-exclude"]

    for entry in excluded:
        assert entry in {".venv", "dist", "build", "scripts/_*.py"}, entry
    assert not any(entry.startswith("reception_crm") for entry in excluded)
