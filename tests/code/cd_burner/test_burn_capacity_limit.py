"""Burn-image capacity: the IMAPI size-limit failure (2026-07-14).

Live bug: burning a study + the ~100 MB Lite Viewer bundle died 55% in with

    Error adding files: (-1062555360, None, ("Adding '_libjpeg.cp313-win_amd64.pyd'
    would result in a result image having a size larger than the current
    configured limit.", ...))

Root cause: ``MsftFileSystemImage`` was created with NO media context, so IMAPI
applied its built-in default size limit (CD-sized, ~650 MB) even on a DVD.
``ChooseImageDefaults(recorder)`` / ``FreeMediaBlocks`` were never set.
"""

from __future__ import annotations

from pathlib import Path

from modules.cd_burner.cd_writer import (
    SECTOR_SIZE,
    check_content_fits,
    content_blocks,
)

_SRC = Path(__file__).resolve().parents[3] / "modules" / "cd_burner" / "cd_writer.py"


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


def test_small_files_each_round_up_to_a_whole_sector(tmp_path):
    for i in range(10):
        _write(tmp_path / f"IM{i:04d}.dcm", 100)  # 100 bytes -> still 1 block

    assert content_blocks(tmp_path) >= 10


def test_content_blocks_covers_raw_bytes_plus_overhead(tmp_path):
    _write(tmp_path / "big.bin", 10 * 1024 * 1024)  # 10 MB

    raw_blocks = (10 * 1024 * 1024) // SECTOR_SIZE
    blocks = content_blocks(tmp_path)

    assert blocks > raw_blocks              # overhead accounted for
    assert blocks < raw_blocks * 1.2 + 1024  # but not wildly inflated


def test_payload_that_fits_is_allowed(tmp_path):
    _write(tmp_path / "study" / "IM0001.dcm", 1 * 1024 * 1024)

    fits, message = check_content_fits(tmp_path, free_sectors=2_298_496)  # DVD
    assert fits is True
    assert message == ""


def test_payload_that_exceeds_the_media_is_rejected_with_numbers(tmp_path):
    _write(tmp_path / "viewer" / "big.bin", 20 * 1024 * 1024)

    # 5 MB of free space — nowhere near enough
    fits, message = check_content_fits(tmp_path, free_sectors=(5 * 1024 * 1024) // SECTOR_SIZE)

    assert fits is False
    assert "does not fit" in message
    assert "MB" in message
    assert "DVD" in message  # tells the user what to do about it


def test_unknown_capacity_never_blocks_a_valid_burn(tmp_path):
    _write(tmp_path / "big.bin", 900 * 1024 * 1024)

    # free_sectors unknown (0) -> we must NOT refuse; let IMAPI decide.
    fits, message = check_content_fits(tmp_path, free_sectors=0)
    assert fits is True
    assert message == ""


def test_burn_configures_the_image_from_the_loaded_media():
    """The whole point of the fix — pin the ordering that makes it work."""
    src = _SRC.read_text(encoding="utf-8")

    assert "ChooseImageDefaults" in src, "image must learn the media's capacity"
    assert "FreeMediaBlocks" in src, "explicit free-block limit from the media"
    assert "check_content_fits(source_path" in src, "pre-flight capacity check"

    # ChooseImageDefaults overwrites FileSystemsToCreate, so our ISO9660+Joliet
    # value MUST be applied AFTER it — otherwise the bundled viewer breaks on
    # 8.3-mangled names (the 2026-06-06 regression).
    assert src.index("ChooseImageDefaults") < src.index("file_system.FileSystemsToCreate")

    # And the capacity check must run BEFORE AddTree, not after it fails.
    assert src.index("check_content_fits(source_path") < src.index("root.AddTree")
