"""How this build was made, readable at run time.

`build_info.json` is written by `scripts/write_build_info.py` just before
PyInstaller runs and bundled by the spec. This reads it back so `/api/health`
can answer, on a machine nobody is sitting at, which interpreter produced the
process that is running and what it had available.

The question is not academic. A release once changed size by 5.8 MB with no
code change, because the build was handed a virtualenv without `cryptography`.
Nothing recorded the interpreter, so the difference was invisible except as a
number on a file listing.

Absent by design in a source checkout: the file is a build artefact, so running
from source reports `available: false` rather than inventing values. "Not built"
and "built by something unknown" are different facts and must not share a shape.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

BUILD_INFO_PATH = Path(__file__).with_name("build_info.json")


@lru_cache(maxsize=1)
def build_info() -> dict[str, Any]:
    """Provenance for this build, or a truthful statement that there is none."""
    try:
        raw = json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "available": False,
            "reason": "no build_info.json — running from source, not from a build",
        }
    except (OSError, json.JSONDecodeError) as exc:
        # Distinguished from the above on purpose. A missing file is the normal
        # state of a source checkout; an unreadable one is a broken artefact,
        # and reporting the second as the first would hide it.
        return {
            "available": False,
            "reason": f"build_info.json present but unreadable: {type(exc).__name__}",
        }

    python = raw.get("python") or {}
    optional = raw.get("optional_packages") or {}
    return {
        "available": True,
        "version": raw.get("version"),
        "python": python.get("version"),
        "interpreter": python.get("executable"),
        # Reported as a sorted list rather than a map so a change is visible at
        # a glance in a health payload someone is skimming.
        "bundled_optional": sorted(name for name, present in optional.items() if present),
        "absent_optional": sorted(name for name, present in optional.items() if not present),
    }
