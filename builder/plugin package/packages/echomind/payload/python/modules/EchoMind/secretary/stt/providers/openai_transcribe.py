from __future__ import annotations

import os
from typing import Any

import requests

from modules.EchoMind.llm_client import chat_completion
from modules.EchoMind.settings_store import get_openai_model_for_feature, get_openai_settings, get_prompt_settings


class OpenAITranscribeProvider:
    name = "openai"

    def transcribe_files(self, paths: list[str], quality_mode: str = "clear", timeout: int = 360) -> dict[str, Any]:
        del quality_mode
        cfg = get_openai_settings()
        api_key = str(cfg.get("api_key") or "").strip()
        model = get_openai_model_for_feature("transcription", "gpt-4o-transcribe")
        base_url = str(cfg.get("base_url") or "https://api.openai.com/v1").strip().rstrip("/")
        organization = str(cfg.get("organization") or "").strip()
        project = str(cfg.get("project") or "").strip()

        if not api_key:
            return {
                "ok": False,
                "provider": self.name,
                "error": "No OpenAI API key configured.",
                "transcript": "",
                "files": [],
            }

        headers = {"Authorization": f"Bearer {api_key}"}
        if organization:
            headers["OpenAI-Organization"] = organization
        if project:
            headers["OpenAI-Project"] = project

        endpoint = f"{base_url}/audio/transcriptions"
        file_results: list[dict[str, Any]] = []
        chunks: list[str] = []
        transcript_prompt = str(get_prompt_settings().get("transcript_cleanup") or "").strip()

        for path in paths:
            if not path or not os.path.exists(path):
                file_results.append({"path": path, "ok": False, "error": "missing_file"})
                continue

            try:
                with open(path, "rb") as fh:
                    files = {"file": (os.path.basename(path), fh, "audio/wav")}
                    data = {"model": model}
                    if transcript_prompt and "diarize" not in model.lower():
                        data["prompt"] = transcript_prompt[:1000]
                    resp = requests.post(endpoint, headers=headers, files=files, data=data, timeout=timeout)
                resp.raise_for_status()
                body = resp.json()
                text = str(body.get("text") or "").strip()
                file_results.append({"path": path, "ok": True, "text": text})
                if text:
                    chunks.append(text)
            except Exception as exc:
                file_results.append({"path": path, "ok": False, "error": str(exc)})

        transcript = "\n".join(x for x in chunks if x).strip()
        if not transcript:
            return {
                "ok": False,
                "provider": self.name,
                "error": "No speech recognized.",
                "transcript": "",
                "files": file_results,
            }

        cleanup_prompt = transcript_prompt
        if cleanup_prompt:
            try:
                cleaned = chat_completion(
                    messages=[
                        {"role": "system", "content": cleanup_prompt},
                        {"role": "user", "content": transcript},
                    ],
                    model=get_openai_model_for_feature("secretary", "gpt-5-mini"),
                    temperature=0.0,
                    timeout=min(int(cfg.get("timeout_seconds") or 60), int(timeout)),
                    api_key_override=api_key,
                    reasoning_effort=str(cfg.get("reasoning_effort") or "").strip() or None,
                )
                transcript = str(cleaned.get("content") or transcript).strip() or transcript
            except Exception:
                pass

        return {
            "ok": True,
            "provider": self.name,
            "transcript": transcript,
            "files": file_results,
        }
