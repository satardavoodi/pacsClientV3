"""The bundled Persian typeface.

The failure mode this file exists for is **silence**. A Qt stylesheet that names
a font family which is not registered does not raise, does not warn and does not
look broken — it falls through to the next family in the stack. Segoe UI shapes
Persian correctly, so the app opens, reads fine, and is simply not wearing the
typeface somebody chose. Nobody notices until they compare two screenshots.

So the things asserted here are the ones that break quietly: that the files are
where the loader looks, that the family name in the stylesheet is the family
name Qt will actually have, and that a build missing the files degrades instead
of crashing.
"""

from __future__ import annotations

import struct
from pathlib import Path

from reception_crm.desktop import theme

FONT_DIR = Path(theme.__file__).resolve().parent / "fonts"


def test_the_font_files_are_where_the_loader_looks():
    """`load_fonts()` resolves `fonts/` beside the module. If the directory is
    renamed or the files are dropped from the package, this is the only place
    that says so before a clinician sees the wrong typeface."""
    for name in theme._FONT_FILES:
        assert (FONT_DIR / name).is_file(), f"missing bundled font: {name}"


def test_the_stack_leads_with_the_bundled_family_and_keeps_a_fallback():
    """Order is the whole design: IRANYekan first, then two faces that ship with
    Windows. Dropping the fallbacks would turn a missing font file into boxes."""
    assert theme.FONT_STACK.startswith(f'"{theme.FONT_FAMILY}"')
    assert "Segoe UI" in theme.FONT_STACK
    assert "Tahoma" in theme.FONT_STACK


def test_the_stylesheet_asks_for_the_font_it_registers():
    """The two halves are written in different places — a constant and an
    f-string of CSS — and nothing but this connects them."""
    css = theme.stylesheet(theme.LIGHT)
    assert theme.FONT_FAMILY in css


def _family_names(path: Path) -> set[str]:
    """Family names out of a TrueType `name` table, with the standard library.

    Parsed here rather than with fontTools so the check always RUNS. It was
    written with `importorskip` first, and skipped on this machine — a test that
    is the only guard against a silent failure, and that silently does not run,
    is the same defect one level up.

    Reads nameID 1 (family) and 16 (typographic family) from every platform
    record; Windows records are UTF-16BE, Macintosh ones are single-byte.
    """
    data = path.read_bytes()
    (table_count,) = struct.unpack(">H", data[4:6])
    table = next(
        (
            struct.unpack(">I", data[12 + 16 * i + 8: 12 + 16 * i + 12])[0]
            for i in range(table_count)
            if data[12 + 16 * i: 12 + 16 * i + 4] == b"name"
        ),
        None,
    )
    assert table is not None, f"{path.name} has no name table — is it really a font?"

    count, string_offset = struct.unpack(">HH", data[table + 2: table + 6])
    names: set[str] = set()
    for i in range(count):
        record = table + 6 + 12 * i
        platform, _encoding, _language, name_id, length, offset = struct.unpack(
            ">HHHHHH", data[record: record + 12]
        )
        if name_id not in (1, 16):
            continue
        start = table + string_offset + offset
        raw = data[start: start + length]
        names.add(raw.decode("utf-16-be" if platform == 3 else "latin-1", "replace").strip())
    return names


def test_the_family_name_is_the_one_inside_the_files():
    """Read from the TTF's own name table rather than trusted.

    `FONT_FAMILY` is a string a human typed. The vendor calls this font
    "IRANYekan", the files are named `IRANYekanWeb*`, and Qt reports a third
    thing — the family recorded in the font. Getting it wrong costs nothing at
    run time and everything on screen: the stylesheet quietly falls through to
    Segoe UI and the app looks like it always did.
    """
    families = _family_names(FONT_DIR / "IRANYekanWebRegular.ttf")
    assert theme.FONT_FAMILY in families, f"the font reports {sorted(families)}"


def test_every_cut_belongs_to_the_same_family():
    """Three files, one family — that is what lets Qt pick a weight. A cut whose
    family differs is a font that never gets used for bold."""
    for name in theme._FONT_FILES:
        families = _family_names(FONT_DIR / name)
        assert theme.FONT_FAMILY in families, f"{name} reports {sorted(families)}"


def test_a_build_without_the_fonts_still_themes(monkeypatch, tmp_path, caplog):
    """Typography must never be a reason the app will not open."""
    monkeypatch.setattr(theme, "_fonts_loaded", None)
    monkeypatch.setattr(theme, "__file__", str(tmp_path / "theme.py"))

    with caplog.at_level("WARNING"):
        assert theme.load_fonts() is False
    assert any("falling back" in message for message in caplog.messages)


def test_loading_twice_does_not_register_twice(monkeypatch):
    """Qt keeps its own registry, and `apply()` runs on every theme switch. A
    second registration of the same family is a duplicate entry, not a no-op."""
    calls: list[str] = []

    monkeypatch.setattr(theme, "_fonts_loaded", None)

    class FakeDatabase:
        @staticmethod
        def addApplicationFont(path: str) -> int:  # noqa: N802 - Qt's name
            calls.append(path)
            return 0

    import sys
    import types

    module = types.ModuleType("PySide6.QtGui")
    module.QFontDatabase = FakeDatabase
    monkeypatch.setitem(sys.modules, "PySide6.QtGui", module)

    assert theme.load_fonts() is True
    first = len(calls)
    assert first == len(theme._FONT_FILES)

    assert theme.load_fonts() is True
    assert len(calls) == first, "the second call re-registered the fonts"
