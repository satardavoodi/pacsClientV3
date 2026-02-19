from __future__ import annotations

import json
import typing as t
import time

import requests
from PySide6.QtCore import QObject, Signal, QThread

from .ai_chat_helpers import _safe_fa_connection_error
from .ai_chat_config import URL_CHAT

class Mode1Payload:
    query: str

    def to_dict(self) -> dict: return {"query": self.query}

class Mode2Payload:
    session_id: str
    user_message: str

    def to_dict(self) -> dict: return {"session_id": self.session_id, "user_message": self.user_message}

class ChatApiClient:
    def __init__(self, base_url: str = URL_CHAT, timeout: int = 60):
        self.base_url = base_url
        self.timeout = timeout

    def _mask_url(self, url: str) -> str:
        if not url:
            return "<URL>"
        try:
            from urllib.parse import urlsplit
            parts = urlsplit(url)
            path = parts.path or ""
            if parts.query:
                return f"{parts.scheme}://<host>{path}?<redacted>"
            return f"{parts.scheme}://<host>{path}"
        except Exception:
            return "<URL>"

    def _log_request(self, method: str, url: str, headers: dict | None) -> float:
        masked_url = self._mask_url(url)
        print(f"[LocalAI] -> {method} {masked_url} headers={headers or {}}")
        return time.perf_counter()

    def _log_response(self, started: float, resp: requests.Response) -> None:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        ctype = resp.headers.get("Content-Type")
        clen = resp.headers.get("Content-Length")
        print(f"[LocalAI] <- status={resp.status_code} elapsed_ms={elapsed_ms} content_type={ctype} content_length={clen}")

    def post(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        started = self._log_request("POST", self.base_url, headers)
        r = requests.post(self.base_url, data=json.dumps(payload), headers=headers, timeout=self.timeout)
        self._log_response(started, r)
        r.raise_for_status()
        return r.json()

class ApiWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: t.Callable, *args, parent=None, **kwargs):
        super().__init__(parent)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            res = self._fn(*self._args, **self._kwargs)
            self.done.emit(res)
        except Exception as e:
            # IMPORTANT: never leak endpoint/URL/host in UI errors
            try:
                self.failed.emit(_safe_fa_connection_error(str(e)))
            except Exception:
                self.failed.emit(
                    "❌ Connection error. Please check your internet connection and contact support if the problem persists."
                )

class ChatController(QObject):
    messageReady = Signal(str, str)  # who, text
    sessionChanged = Signal(str)  # session_id

    def __init__(self, api_client: ChatApiClient):
        super().__init__()
        self.api = api_client
        self._session_id: t.Optional[str] = None

    @property
    def session_id(self) -> t.Optional[str]:
        return self._session_id

    def reset_session(self):
        self._session_id = None
        self.sessionChanged.emit("")

    def switch_session(self, session_id: str):
        self._session_id = session_id
        self.sessionChanged.emit(session_id)

    def bubble(self, who: str, text: str):
        self.messageReady.emit(who, text)

    def handle_chat_response(self, resp_json: dict):
        # /chat returns {"response": "...", "session_id": "..."}
        assistant_text = t.cast(str, resp_json.get("response", ""))
        print(f'\n\nresponse text: \n{assistant_text}')
        if assistant_text:
            self.bubble("AI ChatBot", assistant_text)
        sid = resp_json.get("session_id")
        if sid and sid != self._session_id:
            self._session_id = sid
            self.sessionChanged.emit(sid)
