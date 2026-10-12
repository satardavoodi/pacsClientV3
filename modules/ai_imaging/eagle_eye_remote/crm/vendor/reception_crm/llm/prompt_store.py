"""Editable agent prompts — packaged defaults, with per-machine overrides.

Each agent mode composes its own section onto the base interpretation prompt:

    mode prompt  +  user request  +  reception data  ->  LLM

The defaults ship inside the package (``llm/prompts/*.md``) and are read-only in
a frozen build — PyInstaller unpacks them to a temporary directory that is wiped
on exit, so a prompt edited in place would silently vanish. Overrides therefore
go to the app's own config directory, and every read resolves:

    %APPDATA%\\Reception CRM Agent\\prompts\\<file>   (the override, if any)
    reception_crm/llm/prompts/<file>                  (the packaged default)

That layering is what makes "restore default" possible at all: deleting the
override is the restore, and the shipped text is never modified.

The list of editable prompts is derived from the mode registry in
``core/modes.py``, not hardcoded here. Adding a mode there — the project's stated
way to add one — makes its prompt appear in the management screen with nothing
else to change.
"""

from __future__ import annotations

import json
import shutil
from typing import Any
from dataclasses import dataclass
from pathlib import Path

from ..settings import app_config_dir

PACKAGED_DIR = Path(__file__).resolve().parent / "prompts"
OVERRIDE_DIR_NAME = "prompts"

#: Bumped if the export format ever changes shape.
EXPORT_VERSION = 1


class PromptError(Exception):
    """A prompt could not be read or written."""


@dataclass(frozen=True)
class PromptInfo:
    """One editable prompt, described for the UI."""

    key: str            # stable id, e.g. "mode_report"
    filename: str       # file inside the prompts directory
    title_fa: str
    description_fa: str
    #: Order in the management screen. Base prompt first, then modes.
    order: int = 50

    @property
    def packaged_path(self) -> Path:
        return PACKAGED_DIR / self.filename

    @property
    def override_path(self) -> Path:
        return override_dir() / self.filename


def override_dir() -> Path:
    return app_config_dir() / OVERRIDE_DIR_NAME


# --------------------------------------------------------------------------- #
# what is editable
# --------------------------------------------------------------------------- #
#: Prompts that are not tied to a mode. The base prompt governs every request,
#: which is why it is first and why the UI warns before letting it be edited.
_STATIC: tuple[PromptInfo, ...] = (
    PromptInfo(
        key="base",
        filename="crm_command_interpretation.md",
        title_fa="دستور پایه (همهٔ حالت‌ها)",
        description_fa=(
            "قواعد اصلی که در همهٔ حالت‌ها اعمال می‌شود: چطور فرمان فارسی خوانده شود، "
            "کدام ابزار انتخاب شود، و چه چیزی نیاز به تأیید دارد."
        ),
        order=0,
    ),
    PromptInfo(
        key="data_analysis",
        filename="crm_data_analysis.md",
        title_fa="پاسخ‌نویسی از روی داده",
        description_fa=(
            "پس از آنکه داده‌های پذیرش خوانده شد، این دستور تعیین می‌کند پاسخ نهایی "
            "چطور برای کاربر نوشته شود."
        ),
        order=90,
    ),
)

#: Human wording for the mode prompts. A mode without an entry still appears,
#: using its own Persian label from the registry.
_MODE_DESCRIPTIONS: dict[str, str] = {
    "report": "دستور حالت «گزارش» — بازیابی و نمایش اطلاعات ثبت‌شده، بدون تحلیل. فقط خواندن.",
    "analysis": "دستور حالت «تحلیل» — مقایسه و استدلال روی داده‌ها: الگو، ناسازگاری و ناهنجاری. فقط خواندن.",
    "executive": "دستور حالت «دستور اجرایی» — اجرای عملیات پشتیبانی‌شده. تنها حالتی که می‌تواند داده را تغییر دهد.",
}


def catalog() -> list[PromptInfo]:
    """Every editable prompt, ordered for display.

    Mode prompts are read from the registry so a future mode needs no change
    here — which is the same promise ``core/modes.py`` already makes to the
    mobile client.
    """
    items = list(_STATIC)
    try:
        from ..core import modes as mode_registry

        for index, mode in enumerate(mode_registry.all_modes()):
            filename = getattr(mode, "prompt_file", "")
            if not filename:
                continue
            items.append(
                PromptInfo(
                    key=f"mode_{mode.id}",
                    filename=filename,
                    title_fa=f"حالت {mode.label_fa}",
                    description_fa=_MODE_DESCRIPTIONS.get(mode.id) or mode.description_fa,
                    order=10 + index,
                )
            )
    except Exception:  # noqa: BLE001 - a broken registry must not empty this screen
        pass
    return sorted(items, key=lambda item: (item.order, item.key))


def by_key(key: str) -> PromptInfo | None:
    return next((item for item in catalog() if item.key == key), None)


def by_filename(filename: str) -> PromptInfo | None:
    return next((item for item in catalog() if item.filename == filename), None)


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
def resolve_path(filename: str) -> Path:
    """The file that will actually be read for this prompt."""
    override = override_dir() / filename
    try:
        if override.is_file():
            return override
    except OSError:
        pass
    return PACKAGED_DIR / filename


def read(filename: str) -> str:
    """The active text: the override if one exists, otherwise the default.

    Raises ``OSError`` when neither exists — the callers in ``interpreter.py``
    already distinguish a missing base prompt (fatal, a packaging fault) from a
    missing mode prompt (logged, not fatal).
    """
    return resolve_path(filename).read_text(encoding="utf-8")


def read_default(filename: str) -> str:
    """The shipped text, ignoring any override. Used by "restore" and diffing."""
    return (PACKAGED_DIR / filename).read_text(encoding="utf-8")


def is_overridden(filename: str) -> bool:
    try:
        return (override_dir() / filename).is_file()
    except OSError:
        return False


def differs_from_default(filename: str) -> bool:
    """True only when an override exists AND its text actually differs."""
    if not is_overridden(filename):
        return False
    try:
        return read(filename).strip() != read_default(filename).strip()
    except OSError:
        return True


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #
def write(filename: str, text: str) -> Path:
    """Save an override. Writing text identical to the default clears it instead.

    Collapsing a no-op edit back to "default" keeps the management screen
    honest: a prompt should not be badged as customised because someone opened
    it and pressed save.
    """
    if by_filename(filename) is None:
        raise PromptError(f"Unknown prompt: {filename}")

    try:
        if text.strip() == read_default(filename).strip():
            restore(filename)
            return PACKAGED_DIR / filename
    except OSError:
        pass  # no packaged default to compare against; save the override

    target = override_dir() / filename
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a sibling then replace, so an interrupted save cannot leave
        # the agent reading half a prompt.
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(target)
    except OSError as exc:
        raise PromptError(f"ذخیرهٔ دستور ممکن نشد: {exc}") from exc
    return target


def restore(filename: str) -> None:
    """Delete the override so the packaged default takes over again."""
    try:
        (override_dir() / filename).unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise PromptError(f"بازگرداندن دستور پیش‌فرض ممکن نشد: {exc}") from exc


def restore_all() -> int:
    """Restore every prompt. Returns how many overrides were removed."""
    removed = 0
    for item in catalog():
        if is_overridden(item.filename):
            restore(item.filename)
            removed += 1
    return removed


# --------------------------------------------------------------------------- #
# export / import
# --------------------------------------------------------------------------- #
def export_all(path: str | Path) -> Path:
    """Write every active prompt to one JSON file.

    Exports the ACTIVE text, not just the overrides, so the file is a complete
    picture of how this machine's agent behaves — that is what makes it useful
    to hand to another centre.
    """
    payload: dict[str, Any] = {
        "version": EXPORT_VERSION,
        "kind": "reception-crm-prompts",
        "prompts": [],
    }
    for item in catalog():
        try:
            text = read(item.filename)
        except OSError:
            continue
        payload["prompts"].append(
            {
                "key": item.key,
                "filename": item.filename,
                "title_fa": item.title_fa,
                "customised": differs_from_default(item.filename),
                "text": text,
            }
        )

    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"خروجی گرفتن ممکن نشد: {exc}") from exc
    return target


def import_all(path: str | Path) -> list[str]:
    """Load prompts from an export file. Returns the titles that changed.

    Unknown prompt names are skipped rather than rejected: a file from a newer
    build may describe a mode this one does not have, and the prompts it does
    recognise are still worth applying.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromptError(f"خواندن پروندهٔ دستورها ممکن نشد: {exc}") from exc

    if not isinstance(raw, dict) or raw.get("kind") != "reception-crm-prompts":
        raise PromptError("این پرونده حاوی دستورهای این برنامه نیست.")

    entries = raw.get("prompts")
    if not isinstance(entries, list):
        raise PromptError("پروندهٔ دستورها ساختار درستی ندارد.")

    applied: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item = by_key(str(entry.get("key") or "")) or by_filename(str(entry.get("filename") or ""))
        text = entry.get("text")
        if item is None or not isinstance(text, str) or not text.strip():
            continue
        try:
            if text.strip() == read(item.filename).strip():
                continue  # already identical — not a change worth reporting
        except OSError:
            pass
        write(item.filename, text)
        applied.append(item.title_fa)
    return applied


def backup_overrides(destination: str | Path) -> Path:
    """Copy the override directory somewhere safe. Used before a bulk import."""
    target = Path(destination)
    source = override_dir()
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        target.mkdir(parents=True, exist_ok=True)
    return target
