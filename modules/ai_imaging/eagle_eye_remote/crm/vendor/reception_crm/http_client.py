from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .config import ApiConfig, EndpointConfig


class CrmApiError(RuntimeError):
    """Raised when the CRM API cannot be reached or returns an error."""


@dataclass(frozen=True)
class ApiResponse:
    endpoint: str
    url: str
    status_code: int
    body: Any


class CrmHttpClient:
    def __init__(self, config: ApiConfig):
        self.config = config
        self._bearer_token: str | None = None

    def fetch(self, endpoint: EndpointConfig, params: dict[str, Any]) -> ApiResponse:
        if endpoint.method != "GET":
            raise NotImplementedError(f"Only GET endpoints are supported initially: {endpoint.name}")

        merged_params = {**endpoint.params, **params}
        query = urlencode({key: value for key, value in merged_params.items() if value is not None})
        url = urljoin(f"{self.config.base_url}/", endpoint.path.lstrip("/"))
        if query:
            url = f"{url}?{query}"

        request = Request(url, headers=self._headers(), method=endpoint.method)
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                body = json.loads(payload) if payload else None
                return ApiResponse(endpoint=endpoint.name, url=url, status_code=response.status, body=body)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise CrmApiError(f"{endpoint.name} returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise CrmApiError(f"{endpoint.name} request failed: {exc.reason}") from exc

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", **self.config.default_headers}
        auth = self.config.auth

        if auth.mode == "bearer":
            token = os.getenv(auth.token_env)
            if not token:
                raise CrmApiError(f"Missing bearer token environment variable: {auth.token_env}")
            headers["Authorization"] = f"Bearer {token}"
        elif auth.mode == "api_key":
            api_key = os.getenv(auth.api_key_env)
            if not api_key:
                raise CrmApiError(f"Missing API key environment variable: {auth.api_key_env}")
            headers[auth.api_key_header] = api_key
        elif auth.mode == "ino_login":
            if not self._bearer_token:
                from .ino_api import InoClient

                self._bearer_token = InoClient.from_env().login()
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        elif auth.mode in {"none", ""}:
            pass
        else:
            raise CrmApiError(f"Unsupported auth mode: {auth.mode}")

        return headers
