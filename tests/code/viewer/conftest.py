"""Pytest configuration scoped to tests/viewer/.

Adds the ``--capture-golden`` CLI flag used by ``test_overlap_pixel_quality.py``
(F1.1 — pixel-hash quality gate) to (re)capture golden hashes instead of
asserting against them.
"""
from __future__ import annotations


def pytest_addoption(parser):
    parser.addoption(
        "--capture-golden",
        action="store_true",
        default=False,
        help=(
            "F1.1: capture pixel-hash golden files into tests/viewer/golden/ "
            "instead of asserting equality."
        ),
    )
