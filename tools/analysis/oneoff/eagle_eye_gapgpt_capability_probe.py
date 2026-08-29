"""Run patient-free Eagle Eye capability probes through the GapGPT bridge.

This diagnostic uses the same GapGPT endpoint, HTTP authority and center key
resolver as EchoMind.  It never reads a capture session or DICOM object.  The
only images are deterministic PNG tiles generated in memory by the pure probe
contract.

Examples:
    python tools/analysis/oneoff/eagle_eye_gapgpt_capability_probe.py --dry-run
    python tools/analysis/oneoff/eagle_eye_gapgpt_capability_probe.py
    python tools/analysis/oneoff/eagle_eye_gapgpt_capability_probe.py --model gpt-5.6-sol
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Tuple


ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from modules.ai_imaging.eagle_eye_lumbar import gapgpt_capability  # noqa: E402


OUTPUT_FILE = ROOT / "generated-files" / "gapgpt" / "eagle_eye_capability.json"


def _targets(requested: Iterable[str]) -> Tuple[Tuple[str, float], ...]:
    defaults = dict(gapgpt_capability.DEFAULT_MODEL_TEMPERATURES)
    names = tuple(str(name).strip() for name in requested if str(name).strip())
    if not names:
        return gapgpt_capability.DEFAULT_MODEL_TEMPERATURES
    return tuple((name, defaults.get(name, 0.2)) for name in names)


def _endpoint_url(chat_url: str, endpoint: str) -> str:
    if endpoint == "chat_completions":
        return chat_url
    if endpoint == "responses" and chat_url.endswith("/chat/completions"):
        return chat_url[:-len("/chat/completions")] + "/responses"
    raise ValueError(f"cannot derive GapGPT endpoint {endpoint!r}")


def _response_body(response, api_key: str) -> Dict[str, Any]:
    try:
        body = response.json()
    except Exception:
        return {"raw": gapgpt_capability.redact_sensitive(
            getattr(response, "text", ""), (api_key,))}
    return body if isinstance(body, dict) else {"raw": "non-object JSON response"}


def _send(scenario, api_key: str, chat_url: str, echomind_http) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    started = time.perf_counter()
    try:
        response = echomind_http.post(
            _endpoint_url(chat_url, scenario.endpoint),
            headers=headers,
            json=scenario.payload,
        )
        status_code = int(response.status_code)
        body = _response_body(response, api_key)
        if status_code != 200:
            unsafe_error = body.get("error") or body.get("raw") or body
            body = {"error": gapgpt_capability.redact_sensitive(
                unsafe_error, (api_key,))}
    except Exception as exc:
        status_code = 0
        body = {"error": gapgpt_capability.redact_sensitive(exc, (api_key,))}
    elapsed = time.perf_counter() - started
    return gapgpt_capability.evaluate_response(
        scenario,
        status_code=status_code,
        body=body,
        elapsed_seconds=elapsed,
    )


def _runtime_authorities():
    from modules.ai_imaging.eagle_eye_lumbar import llm_backend

    denied = llm_backend.company_entitlement_error()
    if denied:
        raise RuntimeError(denied)

    from modules.EchoMind import echomind_http
    from modules.EchoMind.ai_chat_config import GAPGPT_API_URL
    from modules.EchoMind.viewer_chat.api_manager import Manage

    _center, api_key = Manage.instance().get_center_and_gapgpt_key()
    if not str(api_key or "").strip():
        raise RuntimeError("No GapGPT credential is available from the EchoMind authority")
    return str(api_key), GAPGPT_API_URL, echomind_http


def _dry_run(targets: Tuple[Tuple[str, float], ...]) -> int:
    rows = []
    for model, temperature in targets:
        for scenario in gapgpt_capability.build_scenarios(model, temperature):
            rows.append({
                "model": model,
                "temperature": temperature,
                "scenario": scenario.name,
                "endpoint": scenario.endpoint,
            })
    print(json.dumps(rows, indent=2))
    return 0


def run(targets: Tuple[Tuple[str, float], ...]) -> Dict[str, Any]:
    api_key, chat_url, echomind_http = _runtime_authorities()
    results = []
    for model, temperature in targets:
        for scenario in gapgpt_capability.build_scenarios(model, temperature):
            result = _send(scenario, api_key, chat_url, echomind_http)
            results.append(result)
            note = result.get("note") or result.get("evidence") or ""
            print(
                f"{model:28} {scenario.name:24} "
                f"{result['status']:11} {result['elapsed_seconds']:7.2f}s {note}"
            )

    document = {
        "probe_version": gapgpt_capability.GAPGPT_CAPABILITY_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "GapGPT",
        "data_class": "synthetic_non_patient",
        "results": results,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(document, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_FILE}")
    return document


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe Eagle Eye model capabilities through GapGPT only."
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Model id to probe. Repeat for multiple models.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the synthetic requests without resolving credentials or sending them.",
    )
    args = parser.parse_args(argv)
    targets = _targets(args.model)
    if args.dry_run:
        return _dry_run(targets)
    try:
        run(targets)
    except Exception as exc:
        print(
            "Capability probe could not start: "
            + gapgpt_capability.redact_sensitive(exc),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
