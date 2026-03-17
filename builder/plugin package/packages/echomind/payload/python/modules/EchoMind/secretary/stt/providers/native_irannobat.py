from __future__ import annotations

import os
from typing import Any

import requests

from modules.EchoMind.ai_chat_config import URL_GEN_TRANSCRIPT


class NativeIrannobatProvider:
    name = "native"

    def transcribe_files(self, paths: list[str], quality_mode: str = "clear", timeout: int = 360) -> dict[str, Any]:
        if not paths:
            return {"ok": False, "provider": self.name, "error": "No files provided.", "transcript": ""}

        files = []
        statuses: list[dict[str, Any]] = []
        try:
            for path in paths:
                if not path or not os.path.exists(path):
                    statuses.append({"path": path, "ok": False, "error": "missing_file"})
                    continue
                handle = open(path, "rb")
                files.append(("audio_files", handle))
                statuses.append({"path": path, "ok": True})

            if not files:
                return {
                    "ok": False,
                    "provider": self.name,
                    "error": "No valid files were found.",
                    "transcript": "",
                    "files": statuses,
                }

            resp = requests.post(
                URL_GEN_TRANSCRIPT,
                files=files,
                data={"quality_mode": quality_mode},
                timeout=timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            return {
                "ok": True,
                "provider": self.name,
                "transcript": (body.get("transcript") or "").strip(),
                "session_id": body.get("session_id"),
                "raw": body,
                "files": statuses,
            }
        finally:
            for _, fh in files:
                try:
                    fh.close()
                except Exception:
                    pass

