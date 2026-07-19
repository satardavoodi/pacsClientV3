"""Operational agent documentation exposed as MCP *resources*.

The user's requirement: the full operational documents (which functions exist,
how to call them, how the workflows operate) must stay available **to AI
agents** so they can use the workstation correctly — WITHOUT dumping those long
documents into the Settings page. MCP resources are exactly the right channel:
the Settings tab shows only the connection info + a one-line pointer, while a
connected agent client can ``resources/list`` + ``resources/read`` the docs on
demand.

Two kinds of resource are published:

* **Curated doc files** — a small allow-list of the operational guides under
  ``docs/for-future-agents/`` (NOT every internal report). Read on demand.
* **A synthesized function catalog** — ``aipacs-agent://functions`` — generated
  live from the CommandBus action list so an agent always sees the *actual*
  callable surface of THIS build, with a short how-to-call note.

Pure stdlib; the docs root and the action list are injected so this is fully
unit-testable off-screen and never depends on a running app.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

RESOURCE_SCHEME = "aipacs-agent"

# Allow-list of operational docs surfaced to agents. Kept deliberately small —
# connection/how-to material only, never clinical reports or internal history.
_CURATED_DOCS = (
    ("guide", "docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md",
     "How to control and test the AI-PACS workstation (command surface, lanes)."),
    ("readme", "docs/for-future-agents/README.md",
     "Index of the for-future-agents documentation set."),
    ("pairing", "docs/for-future-agents/AGENT_MOBILE_PAIRING_PROTOCOL.md",
     "Android pairing + MCP wire protocol for the Agent Gateway."),
    ("client", "docs/for-future-agents/AGENT_MOBILE_CLIENT_GUIDE.md",
     "Mobile client-agent guide: order catalog (actions + params) + the "
     "text-in/text-out contract for driving the workstation."),
)


def _repo_root() -> Path:
    """Best-effort repository / bundle root for locating docs."""
    try:
        from _project_root import PROJECT_ROOT

        return Path(PROJECT_ROOT)
    except Exception:
        # modules/agent_gateway/docs_resources.py -> repo root is parents[2]
        return Path(__file__).resolve().parents[2]


class DocsResourceProvider:
    """Serves the curated docs + a live function catalog as MCP resources."""

    def __init__(
        self,
        *,
        list_actions: Optional[Callable[[], List[str]]] = None,
        repo_root: Optional[Path] = None,
    ) -> None:
        self._list_actions = list_actions or (lambda: [])
        self._root = Path(repo_root) if repo_root is not None else _repo_root()

    # ── MCP: resources/list ───────────────────────────────────────────
    def list_resources(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = [
            {
                "uri": f"{RESOURCE_SCHEME}://functions",
                "name": "AI-PACS function catalog",
                "description": (
                    "Live list of every CommandBus action callable on this "
                    "workstation, with how-to-call notes."
                ),
                "mimeType": "application/json",
            }
        ]
        for key, rel, desc in _CURATED_DOCS:
            path = self._root / rel
            if path.exists():
                out.append(
                    {
                        "uri": f"{RESOURCE_SCHEME}://docs/{key}",
                        "name": Path(rel).name,
                        "description": desc,
                        "mimeType": "text/markdown",
                    }
                )
        return out

    # ── MCP: resources/read ───────────────────────────────────────────
    def read_resource(self, uri: str) -> Optional[Dict[str, Any]]:
        uri = str(uri or "")
        if uri == f"{RESOURCE_SCHEME}://functions":
            text = json.dumps(self._function_catalog(), indent=2, ensure_ascii=False)
            return {"uri": uri, "mimeType": "application/json", "text": text}

        prefix = f"{RESOURCE_SCHEME}://docs/"
        if uri.startswith(prefix):
            key = uri[len(prefix):]
            for k, rel, _desc in _CURATED_DOCS:
                if k == key:
                    path = self._root / rel
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except Exception as exc:
                        logger.debug("doc read failed for %s: %s", uri, exc)
                        return None
                    return {"uri": uri, "mimeType": "text/markdown", "text": text}
        return None

    # ── synthesized catalog ───────────────────────────────────────────
    def _function_catalog(self) -> Dict[str, Any]:
        try:
            actions = sorted(self._list_actions() or [])
        except Exception:
            actions = []
        return {
            "workstation": "AI-PACS",
            "how_to_call": (
                "Call an action as an MCP tool: tools/call with name=<action> "
                "and arguments=<entities dict>. Reads (list_patients, "
                "query_viewport_state, get_measurements, ...) are safe to call "
                "freely. Server-write/destructive actions (download_patient, "
                "send_report_to_pacs, close_patient_tab, cancel_download) may "
                "require confirmation depending on this device's mode — re-issue "
                "with arguments.confirmed=true after the user approves."
            ),
            "action_count": len(actions),
            "actions": actions,
        }


__all__ = ["DocsResourceProvider", "RESOURCE_SCHEME"]
