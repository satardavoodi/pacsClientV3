"""
brain/catalog_loader.py
-----------------------
Utilities for loading Document 1 (catalog.yaml) and Document 2s (per-module
markdown files) from the catalog/ directory next to the brain/ package.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Root of the secretary package (parent of brain/)
_SECRETARY_ROOT = Path(__file__).resolve().parent.parent
_CATALOG_ROOT = _SECRETARY_ROOT / "catalog"
_CATALOG_YAML = _CATALOG_ROOT / "catalog.yaml"
_MODULES_DIR = _CATALOG_ROOT / "modules"


def load_catalog_text() -> str:
    """Return the raw text of catalog.yaml (Document 1)."""
    try:
        return _CATALOG_YAML.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("catalog.yaml not found at %s", _CATALOG_YAML)
        return ""


def load_module_doc(module_id: str) -> str:
    """
    Return the raw markdown text of the per-module Document 2.
    Returns empty string if the file does not exist.
    """
    path = _MODULES_DIR / f"{module_id}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("Module doc not found for module_id=%r at %s", module_id, path)
        return ""


def load_module_docs(module_ids: list[str]) -> str:
    """
    Concatenate per-module Document 2s for the given module_id list.
    Each doc is separated by a horizontal rule so the LLM can distinguish them.
    """
    parts: list[str] = []
    for mid in module_ids:
        doc = load_module_doc(mid)
        if doc:
            parts.append(doc.strip())
        else:
            parts.append(f"# Module: {mid}\n*(No documentation file found.)*")
    return "\n\n---\n\n".join(parts)


def list_available_module_ids() -> list[str]:
    """
    Return all module_ids for which a markdown doc file exists in catalog/modules/.
    """
    if not _MODULES_DIR.exists():
        return []
    return sorted(p.stem for p in _MODULES_DIR.glob("*.md"))
