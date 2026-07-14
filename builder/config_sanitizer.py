"""Build-time sanitization of center-specific configuration.

PROBLEM
-------
``AIPacs.spec`` bundles the repository's ``config/`` directory verbatim
(``('config', 'config')``), and at first run on a client machine
``aipacs_runtime.seed_user_config_defaults()`` copies those bundled templates
into the user's roaming config. So every value the DEVELOPER had saved — real
server IPs, AE titles, the reception API URL, the EchoMind API key, the Google
OAuth client secret — was shipped to, and seeded into, every client centre.

FIX
---
The build no longer packages ``config/`` directly. It packages a SANITIZED copy
produced by this module: application defaults are kept, every center-specific
value is emptied. The developer's own ``config/`` on disk is **never modified** —
source runs still read it (seeding early-returns when not frozen), so local
development is completely unaffected.

Layering
--------
- **Build defaults** (what ships)  : this sanitized tree — safe, non-sensitive.
- **Development config**           : the repo ``config/`` — used only by source
                                     runs, never packaged.
- **Installed centre config**      : the user's roaming config dir, written when
                                     staff enter the centre's values. Seeding is
                                     create-if-missing and migration is key-level
                                     merge-only, so UPDATES PRESERVE these values.

Pure stdlib so the PyInstaller spec, the Nuitka build and the release gate can
all import it without extra dependencies.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ── Sanitization manifest ────────────────────────────────────────────────────
# Keyed by path RELATIVE to config/ (posix). Only files listed here are altered;
# every other config file is copied through untouched.
#
#   blank      : dotted paths whose value becomes ""
#   empty_list : dotted paths whose value becomes []
#   root_list  : the file's ROOT is a JSON array -> becomes []
#   blank_children : every child value under this dotted path becomes ""
SANITIZE: Dict[str, Dict[str, Any]] = {
    # EchoMind — real API key today. Model names / timeouts are product defaults.
    # stt_custom_base_url / stt_auth_token belong to the Voice-to-Text section: a
    # centre's own transcription server + its token must never ship. The PROVIDER
    # choice (stt_provider) is a product default and is kept.
    "echomind_settings.json": {
        "blank": [
            "api_key",
            "openai_api_key",
            "openai_org_id",
            "openai_project_id",
            "stt_custom_base_url",
            "stt_auth_token",
        ],
    },
    # DICOM servers: root is a LIST of the dev centre's servers (host/AE title).
    "servers.json": {"root_list": True},
    # Socket transport: host is the centre's PACS. Ports/tuning are defaults.
    "socket_config.json": {"blank": ["socket_host"]},
    # Multi-server profiles: real hosts + per-module AI service URLs.
    "server_profiles.json": {
        "empty_list": ["profiles"],
        "blank": ["primary_profile_id", "active_profile_id"],
    },
    # Reception / portal API.
    "reception_api_config.json": {
        "blank": ["reception_api_base_url", "reception_api_host"],
    },
    # AI service endpoints (real IPs).
    "servers_address.json": {"blank_children": ["services"]},
    # Online consultation hub address (a real mailbox).
    "cloud_consultation/cloud_consultation.json": {"blank": ["consultation_address"]},
    # Identity / OAuth — REAL client secret today. Must never ship.
    "identity/google_oauth.json": {
        "blank": [
            "installed.client_id",
            "installed.client_secret",
            "installed.project_id",
        ],
    },
    "identity/aipacs_web.json": {"blank": ["base_url"]},
    # Centre identity stamped onto patient media.
    "lightviewer_settings.json": {
        "blank": ["center_name", "center_address", "center_phone"],
    },
    # Already empty today — enforced so they can never regress.
    "external_pacs_servers.json": {"empty_list": ["servers"]},
    "offline_cloud_servers.json": {"empty_list": ["servers"]},
    "ino_assignment_config.json": {"blank": ["assignment_api_base_url"]},
    "update_sources.json": {"blank": ["sources[].location"]},
}

# Files that must NEVER be packaged at all (dev leftovers / secret material /
# machine-generated state).
EXCLUDE_NAMES = {
    ".gitignore",
    # OPT-21: the persisted per-INSTALL hardware probe (OpenGL/GPU, CPU, RAM,
    # disk). Shipping it would seed the DEVELOPER machine's results into every
    # client — and because a persisted PASS is trusted with ZERO probing, a
    # client whose driver cannot do OpenGL 3.2 would SKIP its own probe and walk
    # straight into the native MPR crash the pre-flight exists to prevent.
    # It is machine-generated state, never a config template.
    "hardware_check.json",
}
EXCLUDE_DIRS = {"secrets", "__pycache__"}
EXCLUDE_SUFFIX_PATTERNS = (
    re.compile(r"\.bak(-\d+)?$", re.I),   # aipacs_web.json.bak-20260613
    re.compile(r"\.part$", re.I),
    re.compile(r"\.orig$", re.I),
    re.compile(r"\.local\.json$", re.I),  # developer override files
)

# Files deliberately LEFT ALONE (needed for correct install behaviour).
KEEP_AS_IS = {
    "installation_profile.json",
    "viewer_backend_settings.json",
    "modality_grid.json",
}


def _is_excluded(rel: Path) -> bool:
    if rel.name in EXCLUDE_NAMES:
        return True
    if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]):
        return True
    return any(p.search(rel.name) for p in EXCLUDE_SUFFIX_PATTERNS)


def _set_by_path(obj: Any, dotted: str, value: Any) -> bool:
    """Set a dotted path (supports one ``[]`` list-wildcard segment). Returns True
    if anything was changed. Missing paths are silently ignored."""
    if "[]" in dotted:
        head, _, tail = dotted.partition("[].")
        node = _get_by_path(obj, head)
        if not isinstance(node, list):
            return False
        changed = False
        for item in node:
            if isinstance(item, dict) and tail in item:
                item[tail] = value
                changed = True
        return changed
    parts = dotted.split(".")
    node = obj
    for p in parts[:-1]:
        if not isinstance(node, dict) or p not in node:
            return False
        node = node[p]
    if isinstance(node, dict) and parts[-1] in node:
        node[parts[-1]] = value
        return True
    return False


def _get_by_path(obj: Any, dotted: str) -> Any:
    node = obj
    for p in dotted.split("."):
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def sanitize_obj(rel_posix: str, data: Any) -> Any:
    """Return a sanitized copy of one config document (never mutates the input)."""
    rule = SANITIZE.get(rel_posix)
    if not rule:
        return data
    out = copy.deepcopy(data)
    if rule.get("root_list"):
        return []
    for dotted in rule.get("blank", []):
        _set_by_path(out, dotted, "")
    for dotted in rule.get("empty_list", []):
        _set_by_path(out, dotted, [])
    for dotted in rule.get("blank_children", []):
        node = _get_by_path(out, dotted)
        if isinstance(node, dict):
            for k in list(node.keys()):
                node[k] = ""
    return out


def sanitize_bytes(rel_posix: str, raw: bytes) -> bytes:
    """Sanitized on-disk bytes for one template (used by the build AND the gate,
    so they can never disagree). Non-JSON / unparseable files pass through."""
    if rel_posix not in SANITIZE:
        return raw
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return raw
    clean = sanitize_obj(rel_posix, data)
    return (json.dumps(clean, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build_clean_config_tree(src_root: Path, dst_root: Path) -> Dict[str, List[str]]:
    """Write a sanitized copy of ``src_root`` into ``dst_root``.

    ``src_root`` (the developer's config/) is only READ. Returns a report.
    """
    src_root = Path(src_root)
    dst_root = Path(dst_root)
    if dst_root.exists():
        shutil.rmtree(dst_root, ignore_errors=True)
    dst_root.mkdir(parents=True, exist_ok=True)

    report: Dict[str, List[str]] = {"sanitized": [], "copied": [], "excluded": []}
    for src in sorted(src_root.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(src_root)
        rel_posix = rel.as_posix()
        if _is_excluded(rel):
            report["excluded"].append(rel_posix)
            continue
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        raw = src.read_bytes()
        out = sanitize_bytes(rel_posix, raw)
        dst.write_bytes(out)
        (report["sanitized"] if out != raw else report["copied"]).append(rel_posix)
    return report


# ── Leak scanner (release gate) ──────────────────────────────────────────────
_IPV4 = re.compile(r"\b(?!0\.0\.0\.0)(?!127\.0\.0\.1)\d{1,3}(?:\.\d{1,3}){3}\b")
_SECRET_KEYS = re.compile(
    r"(api_key|client_secret|password|passwd|token|secret)$", re.I
)
# Keys whose value legitimately looks like an IP but is not one (e.g. a
# four-part library version "4.5.1.48").
_IGNORE_IP_KEYS = re.compile(r"(^|_)(version|schema_version)$", re.I)


def scan_for_center_values(root: Path) -> List[Tuple[str, str, str]]:
    """Find center-specific values that must NEVER ship. Returns
    ``[(relpath, dotted_key, reason), ...]`` — empty means clean."""
    findings: List[Tuple[str, str, str]] = []
    root = Path(root)

    def walk(rel: str, node: Any, path: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(rel, v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(rel, v, f"{path}[{i}]")
        else:
            s = str(node or "").strip()
            if not s:
                return
            leaf = path.split(".")[-1].split("[")[0]
            if _SECRET_KEYS.search(leaf):
                findings.append((rel, path, "non-empty secret field"))
            elif _IPV4.search(s) and not _IGNORE_IP_KEYS.search(leaf):
                findings.append((rel, path, "embedded IP address"))

    for p in sorted(root.rglob("*.json")):
        rel = p.relative_to(root).as_posix()
        if rel in KEEP_AS_IS:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        walk(rel, data)
    return findings


if __name__ == "__main__":  # manual: python builder/config_sanitizer.py
    here = Path(__file__).resolve().parents[1]
    out = here / "generated-files" / "build" / "config_clean"
    rep = build_clean_config_tree(here / "config", out)
    print(json.dumps(rep, indent=2))
    leaks = scan_for_center_values(out)
    print("LEAKS:", leaks or "none")
    raise SystemExit(1 if leaks else 0)
