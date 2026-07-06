# -*- coding: utf-8 -*-
r"""Live clinical workflow validation for the EchoMind Secretary agent.

This is an end-to-end runner, not a unit test. It talks to the running
AI-PACS app through the same QLocalSocket test server used by the
``aipacs-control`` MCP, wraps key commands with ``UiProbe`` screenshots, runs
OCR over the loaded viewport image, and writes a structured report.

Typical run from the repository root:

    .\.venv\Scripts\python.exe tools\testing\aipacs_control_mcp\clinical_agent_validation.py ^
      --launch-app --config tools\testing\aipacs_control_mcp\scenarios\clinical_agent_validation.default.json

Measurement is automated through the CommandBus when image-space coordinates are
supplied by the scenario or returned by the external GPT/GapGPT brain. Legacy
screen-coordinate drag is retained only as a fallback for older builds.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

from client import AipacsControlClient  # noqa: E402
from ui_probe import UiProbe  # noqa: E402


LOGDIR = REPO / "user_data" / "logs"
MEASUREMENT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:mm|cm|px|deg|degree|degrees|°)\b", re.I)


def _echomind_agent_runs_root() -> Path:
    try:
        from PacsClient.utils.data_paths import ECHOMIND_DIR
        root = Path(ECHOMIND_DIR)
    except Exception:
        root = REPO / "user_data" / "echomind"
    out = root / "agent_runs" / "clinical_validation"
    out.mkdir(parents=True, exist_ok=True)
    return out


DEFAULT_OUT_ROOT = _echomind_agent_runs_root()


@dataclass
class Stage:
    name: str
    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "pass"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Optional[Path]) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _yesterday_yyyymmdd() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") or {}
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def _series(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") or {}
    if isinstance(data, dict):
        values = data.get("series") or data.get("rows") or []
    else:
        values = []
    return [r for r in values if isinstance(r, dict)]


def _patient_key(row: dict[str, Any]) -> str:
    return str(row.get("patient_id") or row.get("id") or row.get("patient_code") or "")


def _modalities(row: dict[str, Any]) -> str:
    val = row.get("modalities", row.get("modality", ""))
    if isinstance(val, (list, tuple, set)):
        return ",".join(str(x) for x in val)
    return str(val or "")


def _query_modality(config: dict[str, Any], modality: str) -> str:
    aliases = config.get("modality_aliases") or {"MRI": "MR"}
    return str(aliases.get(str(modality).upper(), modality))


def _first_row_with_modality(rows: list[dict[str, Any]], modality: str) -> Optional[dict[str, Any]]:
    wanted = modality.upper()
    for row in rows:
        if wanted in _modalities(row).upper():
            return row
    return rows[0] if rows else None


def _rows_with_modality(rows: list[dict[str, Any]], modality: str) -> list[dict[str, Any]]:
    wanted = modality.upper()
    return [row for row in rows if wanted in _modalities(row).upper()]


def _safe_patient_entities(row: dict[str, Any]) -> dict[str, Any]:
    ent: dict[str, Any] = {"patient_id": _patient_key(row)}
    for src, dst in (
        ("patient_name", "patient_name"),
        ("name", "patient_name"),
        ("study_uid", "study_uid"),
        ("report_status", "report_status"),
    ):
        if row.get(src) and dst not in ent:
            ent[dst] = row[src]
    return ent


def _viewport0(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") or {}
    viewports = data.get("viewports") if isinstance(data, dict) else []
    if isinstance(viewports, list) and viewports:
        return viewports[0] if isinstance(viewports[0], dict) else {}
    return {}


def _extract_measurement(text: str) -> str:
    m = MEASUREMENT_RE.search(text or "")
    return m.group(0).replace(",", ".") if m else ""


def _measurement_text(row: dict[str, Any]) -> str:
    if not row:
        return ""
    if row.get("distance_mm") not in (None, ""):
        try:
            return f"{float(row['distance_mm']):.2f} mm"
        except Exception:
            return f"{row['distance_mm']} mm"
    if row.get("angle_degrees") not in (None, ""):
        try:
            return f"{float(row['angle_degrees']):.2f} deg"
        except Exception:
            return f"{row['angle_degrees']} deg"
    stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
    if stats and stats.get("mean") not in (None, ""):
        return f"ROI mean={stats.get('mean')}, area_cm2={stats.get('area_cm2')}"
    return ""


def _strip_json_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = [
            line for line in text.splitlines()
            if not line.strip().startswith("```")
        ]
        return "\n".join(lines).strip()
    return text


class ExternalGPTBrain:
    """Thin external reasoning adapter.

    The local runner only collects state, calls this adapter, validates that the
    returned decision fits the available objects, then executes it. Selection
    and interpretation decisions belong here, not in the local orchestrator.

    The call goes through ``modules.EchoMind.llm_client.chat_completion`` so it
    uses the same configured EchoMind Secretary backend. In the AI-PACS company
    deployment that means GapGPT by default; OpenAI is only used when EchoMind
    settings explicitly select the OpenAI backend.
    """

    SYSTEM_PROMPT = (
        "You are the external GPT reasoning brain for an AI-PACS workflow. "
        "The local process is only an orchestrator/executor. Return only valid "
        "JSON. Choose from the provided IDs/indexes only. Do not invent patient "
        "IDs, series numbers, slice indexes, coordinates, or actions. If there "
        "is not enough information, return a JSON object with ok=false and a "
        "short reason."
    )

    def __init__(self, config: dict[str, Any], out_dir: Path):
        cfg = config.get("external_brain") or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.required = bool(cfg.get("required", self.enabled))
        self.allow_local_fallback = bool(cfg.get("allow_local_fallback", False))
        self.model = str(cfg.get("model") or "").strip()
        self.max_rows = int(cfg.get("max_rows", 20) or 20)
        self.max_series = int(cfg.get("max_series", 20) or 20)
        self.timeout = int(cfg.get("timeout_seconds", 60) or 60)
        self.out = out_dir
        self.log_path = self.out / "external_brain_decisions.jsonl"

    def _log(self, task: str, context: dict[str, Any], result: dict[str, Any],
             raw: str = "", error: str = "") -> None:
        rec = {
            "t": _now_iso(),
            "task": task,
            "context": context,
            "result": result,
            "raw": raw[:4000],
            "error": error,
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def decide(self, task: str, context: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "external brain disabled"}
        try:
            from modules.EchoMind.llm_client import chat_completion
            from modules.EchoMind.settings_store import get_openai_model_for_feature
            model = self.model or get_openai_model_for_feature("secretary", "gpt-5-mini")
            user = {
                "task": task,
                "instruction": (
                    "Return a compact JSON decision. The local orchestrator "
                    "will execute only the returned decision after validation."
                ),
                "context": context,
            }
            result = chat_completion(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
                ],
                model=model,
                temperature=0.0,
                max_tokens=800,
                timeout=self.timeout,
            )
            raw = str(result.get("content") or "")
            parsed = json.loads(_strip_json_fences(raw))
            if not isinstance(parsed, dict):
                parsed = {"ok": False, "reason": "GPT returned non-object JSON"}
            self._log(task, context, parsed, raw=raw)
            return parsed
        except Exception as exc:  # noqa: BLE001
            out = {"ok": False, "reason": f"external brain failed: {exc}"}
            self._log(task, context, out, error=traceback.format_exc())
            return out


class ClinicalAgentValidation:
    def __init__(self, config: dict[str, Any], out_dir: Path):
        self.config = config
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.commands_path = self.out / "commands.jsonl"
        self.conversation_path = self.out / "conversation.jsonl"
        self.client: Optional[AipacsControlClient] = None
        self.probe: Optional[UiProbe] = None
        self.stages: list[Stage] = []
        self.selected_patient: dict[str, Any] = {}
        self.selected_series: dict[str, Any] = {}
        self.ocr_text = ""
        self.measurement_result = ""
        self.run_started = time.time()
        self.brain = ExternalGPTBrain(config, self.out)

    # -- reporting ---------------------------------------------------------
    def _log_conversation(self, kind: str, payload: dict[str, Any]) -> None:
        rec = {"t": _now_iso(), "kind": kind, **payload}
        with self.conversation_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def stage(self, name: str, status: str, message: str,
              data: Optional[dict[str, Any]] = None,
              artifacts: Optional[list[str]] = None,
              error: str = "") -> Stage:
        item = Stage(
            name=name,
            status=status,
            message=message,
            data=data or {},
            artifacts=artifacts or [],
            error=error,
        )
        self.stages.append(item)
        self._log_conversation("stage", item.__dict__)
        self.flush_report(partial=True)
        return item

    def _log_command(self, action: str, entities: dict[str, Any], reply: dict[str, Any],
                     label: str = "", mode: str = "") -> None:
        rec = {
            "t": _now_iso(),
            "label": label,
            "action": action,
            "entities": entities,
            "mode": mode,
            "reply": reply,
        }
        with self.commands_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self._log_conversation("command", rec)

    def report_obj(self, partial: bool = False) -> dict[str, Any]:
        required = [s for s in self.stages if s.status != "skipped"]
        overall_ok = bool(required) and all(s.status == "pass" for s in required)
        return {
            "name": "clinical_agent_validation",
            "partial": partial,
            "test_started": datetime.fromtimestamp(self.run_started).isoformat(timespec="seconds"),
            "test_finished": None if partial else _now_iso(),
            "out_dir": str(self.out),
            "selected_modality": self.config.get("target_modality", "CT"),
            "initial_modality": self.config.get("initial_modality", "MRI"),
            "selected_patient": self.selected_patient,
            "study_series_loaded": self.selected_series,
            "viewport_used": int(self.config.get("viewport", 0)),
            "ocr_text_result": self.ocr_text,
            "measurement_result": self.measurement_result,
            "external_brain": {
                "enabled": self.brain.enabled,
                "required": self.brain.required,
                "allow_local_fallback": self.brain.allow_local_fallback,
                "decisions_log": str(self.brain.log_path),
            },
            "artifact_logs": {
                "commands": str(self.commands_path),
                "conversation": str(self.conversation_path),
                "error_logs": str(self.out / "error_logs.json"),
            },
            "stages": [s.__dict__ for s in self.stages],
            "overall_status": "pass" if overall_ok else "fail",
        }

    def flush_report(self, partial: bool = False) -> None:
        _write_json(self.out / "report.json", self.report_obj(partial=partial))

    def write_markdown(self) -> None:
        obj = self.report_obj(partial=False)
        lines = [
            "# Clinical Agent Validation Report",
            "",
            f"- Started: {obj['test_started']}",
            f"- Finished: {obj['test_finished']}",
            f"- Overall: {obj['overall_status'].upper()}",
            f"- Patient: {self.selected_patient.get('patient_id', '')}",
            f"- Series: {self.selected_series.get('series_number', '')}",
            f"- Viewport: {obj['viewport_used']}",
            "",
            "## Stages",
            "",
        ]
        for s in self.stages:
            lines.append(f"- {s.status.upper()} `{s.name}`: {s.message}")
        lines += [
            "",
            "## OCR Text",
            "",
            "```text",
            self.ocr_text.strip() or "(empty)",
            "```",
            "",
            "## Measurement",
            "",
            self.measurement_result or "(not available)",
            "",
            "## Recommendations",
            "",
        ]
        if any(s.name == "measurement" and s.status != "pass" for s in self.stages):
            lines.append("- Provide external-brain image-space measurement points or add `measurement.points_image` to the scenario; keep coordinate_drag only as a legacy fallback.")
        if any(s.name == "ocr_capture" and s.status != "pass" for s in self.stages):
            lines.append("- Install `pytesseract` and a Tesseract binary, or set `AIPACS_TESSERACT` to the executable path.")
        if any(s.status == "fail" for s in self.stages):
            lines.append("- Review `commands.jsonl`, `report.json`, app logs, and `UiProbe` screenshots under this run directory.")
        if lines[-1] == "":
            lines.append("- No follow-up recommendations.")
        (self.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # -- command helpers ---------------------------------------------------
    def connect(self) -> None:
        self.client = AipacsControlClient(connect_timeout_ms=5000)

    def send(self, action: str, entities: Optional[dict[str, Any]] = None,
             timeout_ms: int = 60000, label: str = "", observe_s: float = 0.0,
             mode: str = "") -> dict[str, Any]:
        assert self.client is not None
        ent = entities or {}
        if self.probe is not None and label:
            rec = self.probe.run(label, action, ent, observe_s=observe_s or 3.0,
                                 timeout_ms=timeout_ms)
            raw_reply = rec.get("reply") if isinstance(rec.get("reply"), dict) else {}
            reply = {
                "ok": rec.get("ok"),
                "action": action,
                "error_code": rec.get("error_code"),
                "message": raw_reply.get("message") or rec.get("message", ""),
                "data": raw_reply.get("data"),
                "probe_record": rec,
            }
            self._log_command(action, ent, reply, label=label, mode=mode)
            return reply
        reply = self.client.send(action, ent, timeout_ms=timeout_ms, mode=mode)
        self._log_command(action, ent, reply, label=label, mode=mode)
        return reply

    def poll(self, name: str, fn: Callable[[], Optional[dict[str, Any]]],
             timeout_s: float, interval_s: float = 1.0) -> Optional[dict[str, Any]]:
        deadline = time.time() + timeout_s
        last_error = ""
        while time.time() < deadline:
            try:
                out = fn()
                if out:
                    return out
            except Exception as exc:  # noqa: BLE001
                last_error = repr(exc)
            time.sleep(interval_s)
        if last_error:
            self.stage(name, "fail", f"poll timed out after {timeout_s}s", error=last_error)
        return None

    # -- external brain decisions -----------------------------------------
    def _brain_or_fail(self, name: str, decision: dict[str, Any]) -> bool:
        if decision.get("ok") is not False:
            self.stage(name, "pass", "external GPT brain returned a decision", data=decision)
            return True
        status = "fail" if self.brain.required and not self.brain.allow_local_fallback else "blocked"
        self.stage(name, status, str(decision.get("reason") or "external GPT brain unavailable"), data=decision)
        return False

    def choose_patient(self, rows: list[dict[str, Any]], target_modality: str) -> Optional[dict[str, Any]]:
        candidate_rows = _rows_with_modality(rows, target_modality)
        if not candidate_rows and rows:
            self.stage("target_modality_filter", "fail",
                       f"no rows matched target modality {target_modality}",
                       data={"raw_count": len(rows)})
            return None
        if self.brain.enabled:
            slim_rows = [
                {
                    "row_index": i,
                    "patient_id": _patient_key(row),
                    "study_uid": row.get("study_uid"),
                    "modalities": row.get("modalities", row.get("modality")),
                    "series_count": row.get("series_count"),
                    "report_status": row.get("report_status"),
                }
                for i, row in enumerate(candidate_rows[: self.brain.max_rows])
            ]
            decision = self.brain.decide("choose_patient_for_open", {
                "target_modality": target_modality,
                "candidate_patients": slim_rows,
                "expected_json": {
                    "ok": True,
                    "patient_id": "<one provided patient_id>",
                    "reason": "<short reason>",
                },
            })
            if self._brain_or_fail("external_brain_choose_patient", decision):
                wanted = str(decision.get("patient_id") or "")
                selected = next((row for row in candidate_rows if _patient_key(row) == wanted), None)
                if selected:
                    return selected
                self.stage("external_brain_choose_patient_validated", "fail",
                           f"GPT selected unavailable patient_id={wanted}", data=decision)
                return None
            if self.brain.required and not self.brain.allow_local_fallback:
                return None
        self.stage("external_brain_choose_patient", "skipped",
                   "using explicit patient_id or deterministic QA fallback")
        return _first_row_with_modality(candidate_rows, target_modality)

    def choose_series(self, series: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if self.brain.enabled:
            slim_series = [
                {
                    "series_index": i,
                    "series_number": row.get("series_number"),
                    "series_uid": row.get("series_uid"),
                    "image_count": row.get("image_count"),
                    "description": row.get("description"),
                }
                for i, row in enumerate(series[: self.brain.max_series])
            ]
            decision = self.brain.decide("choose_series_for_viewport_import", {
                "selected_patient": _safe_patient_entities(self.selected_patient),
                "candidate_series": slim_series,
                "expected_json": {
                    "ok": True,
                    "series_number": "<one provided series_number>",
                    "reason": "<short reason>",
                },
            })
            if self._brain_or_fail("external_brain_choose_series", decision):
                wanted = str(decision.get("series_number") or "")
                selected = next((row for row in series if str(row.get("series_number")) == wanted), None)
                if selected:
                    return selected
                self.stage("external_brain_choose_series_validated", "fail",
                           f"GPT selected unavailable series_number={wanted}", data=decision)
                return None
            if self.brain.required and not self.brain.allow_local_fallback:
                return None
        self.stage("external_brain_choose_series", "skipped",
                   "using configured series_index deterministic QA fallback")
        index = int(self.config.get("series_index", 0))
        index = max(0, min(index, len(series) - 1))
        return dict(series[index])

    def choose_slice_index(self, viewport_state: dict[str, Any]) -> int:
        slice_count = int(viewport_state.get("slice_count") or 1)
        if self.brain.enabled:
            decision = self.brain.decide("choose_stack_slice_for_ocr_and_measurement", {
                "selected_patient": _safe_patient_entities(self.selected_patient),
                "selected_series": self.selected_series,
                "viewport_state": viewport_state,
                "valid_slice_index_range": [0, max(0, slice_count - 1)],
                "expected_json": {
                    "ok": True,
                    "slice_index": "<integer in range>",
                    "reason": "<short reason>",
                },
            })
            if self._brain_or_fail("external_brain_choose_slice", decision):
                try:
                    idx = int(decision.get("slice_index"))
                    if 0 <= idx < slice_count:
                        return idx
                except Exception:
                    pass
                self.stage("external_brain_choose_slice_validated", "fail",
                           "GPT returned an invalid slice_index", data=decision)
                return 0
            if self.brain.required and not self.brain.allow_local_fallback:
                return 0
        self.stage("external_brain_choose_slice", "skipped",
                   "using middle-slice deterministic QA fallback")
        return max(0, slice_count // 2)

    def decide_measurement_strategy(self, actions: list[Any]) -> dict[str, Any]:
        if self.brain.enabled:
            decision = self.brain.decide("decide_measurement_strategy", {
                "selected_patient": _safe_patient_entities(self.selected_patient),
                "selected_series": self.selected_series,
                "ocr_text": self.ocr_text[:2000],
                "available_actions": [str(a) for a in actions],
                "configured_measurement": self.config.get("measurement") or {},
                "expected_json": {
                    "ok": True,
                    "strategy": "commandbus | coordinate_drag | blocked",
                    "reason": "<short reason>",
                },
            })
            self._brain_or_fail("external_brain_measurement_strategy", decision)
            return decision
        self.stage("external_brain_measurement_strategy", "skipped",
                   "external brain disabled")
        return {"ok": False, "strategy": "blocked", "reason": "external brain disabled"}

    # -- capture/OCR/measurement -----------------------------------------
    def stable_png_for(self, label: str) -> Optional[Path]:
        path = self.out / label / "stable.png"
        return path if path.exists() else None

    def run_ocr(self, image_path: Path) -> tuple[str, str]:
        try:
            from modules.EchoMind.secretary.background.verification import (
                ocr_available,
                ocr_image,
            )
        except Exception as exc:  # noqa: BLE001
            return "", f"OCR_IMPORT_FAILED: {exc}"
        if not ocr_available():
            return "", "OCR_UNAVAILABLE"
        text = ocr_image(str(image_path))
        return text, "OCR_OK" if text else "OCR_EMPTY"

    def coordinate_measurement(self) -> tuple[bool, str]:
        measurement = self.config.get("measurement") or {}
        if str(measurement.get("mode") or "").lower() != "coordinate_drag":
            return False, "no coordinate measurement configured"
        tool_click = measurement.get("tool_click")
        start = measurement.get("start")
        end = measurement.get("end")
        if not (tool_click and start and end):
            return False, "measurement.tool_click/start/end are required"
        try:
            from pywinauto import mouse
            mouse.click(button="left", coords=(int(tool_click[0]), int(tool_click[1])))
            time.sleep(float(measurement.get("after_tool_s", 0.4)))
            mouse.press(button="left", coords=(int(start[0]), int(start[1])))
            time.sleep(0.1)
            mouse.release(button="left", coords=(int(end[0]), int(end[1])))
            time.sleep(float(measurement.get("after_drag_s", 1.0)))
            return True, "coordinate drag completed"
        except Exception as exc:  # noqa: BLE001
            return False, f"coordinate measurement failed: {exc}"

    def commandbus_measurement(
        self,
        viewport: int,
        target_slice: int,
        context_image: Optional[Path],
    ) -> tuple[bool, str, list[str], dict[str, Any]]:
        measurement = self.config.get("measurement") or {}
        mode = str(measurement.get("mode") or "").lower()
        if mode == "coordinate_drag":
            return False, "scenario requested legacy coordinate_drag", [], {}

        context_reply = self.send(
            "get_viewport_context",
            {"viewport": viewport, "include_slice_meta": True},
            timeout_ms=30000,
            mode="read_only",
        )
        if not context_reply.get("ok"):
            return False, "get_viewport_context failed", [], {"context_reply": context_reply}

        capture_reply = self.send(
            "capture_viewport",
            {"viewport": viewport, "scope": "viewport", "filename_prefix": "clinical_measurement_before"},
            timeout_ms=30000,
        )
        artifacts: list[str] = []
        before_path = str(((capture_reply.get("data") or {}) or {}).get("path") or "")
        if before_path:
            artifacts.append(before_path)

        points = measurement.get("points_image") or measurement.get("image_points")
        label = str(measurement.get("label") or "agent measurement")
        decision: dict[str, Any] = {}
        if not points and self.brain.enabled:
            decision = self.brain.decide("decide_measurement_points", {
                "selected_patient": _safe_patient_entities(self.selected_patient),
                "selected_series": self.selected_series,
                "viewport_context": context_reply.get("data") or {},
                "viewport_capture_path": before_path or str(context_image or ""),
                "ocr_text": self.ocr_text[:2000],
                "instruction": (
                    "Choose two image-pixel points for a safe distance measurement "
                    "only if the target anatomy is clear. Use the current displayed "
                    "slice only. Do not invent anatomy."
                ),
                "expected_json": {
                    "ok": True,
                    "action": {
                        "name": "measure_distance",
                        "entities": {
                            "viewport": viewport,
                            "slice_index": target_slice,
                            "points_image": [[0.0, 0.0], [1.0, 1.0]],
                            "label": "<short label>",
                        },
                    },
                    "requires_confirmation": False,
                    "reason": "<short reason>",
                },
            })
            self._brain_or_fail("external_brain_measurement_points", decision)
            action = decision.get("action") if isinstance(decision.get("action"), dict) else {}
            entities = action.get("entities") if isinstance(action.get("entities"), dict) else {}
            if str(action.get("name") or "") == "measure_distance":
                points = entities.get("points_image") or entities.get("image_points")
                label = str(entities.get("label") or label)
            if decision.get("requires_confirmation"):
                return False, "external brain requested confirmation before measurement", artifacts, {
                    "context_reply": context_reply,
                    "capture_reply": capture_reply,
                    "external_brain_decision": decision,
                }

        if not points:
            return False, "no image-space measurement points supplied by scenario or external brain", artifacts, {
                "context_reply": context_reply,
                "capture_reply": capture_reply,
                "external_brain_decision": decision,
            }

        measure_reply = self.send(
            "measure_distance",
            {
                "viewport": viewport,
                "slice_index": target_slice,
                "points_image": points,
                "label": label,
            },
            timeout_ms=30000,
        )
        if not measure_reply.get("ok"):
            return False, "measure_distance failed", artifacts, {
                "context_reply": context_reply,
                "capture_reply": capture_reply,
                "measure_reply": measure_reply,
                "external_brain_decision": decision,
            }

        readback = self.send(
            "get_measurements",
            {"viewport": viewport, "slice_index": target_slice},
            timeout_ms=30000,
            mode="read_only",
        )
        after = self.send(
            "capture_viewport",
            {"viewport": viewport, "scope": "viewport", "filename_prefix": "clinical_measurement_after"},
            timeout_ms=30000,
        )
        after_path = str(((after.get("data") or {}) or {}).get("path") or "")
        if after_path:
            artifacts.append(after_path)

        measurement_row = ((measure_reply.get("data") or {}) or {}).get("measurement") or {}
        value = _measurement_text(measurement_row)
        if not value:
            rows = ((readback.get("data") or {}) or {}).get("measurements") or []
            if isinstance(rows, list) and rows:
                value = _measurement_text(rows[-1] if isinstance(rows[-1], dict) else {})
        self.measurement_result = value
        ok = bool(value) and bool(readback.get("ok"))
        return ok, value or "measurement was placed but value/readback was unavailable", artifacts, {
            "context_reply": context_reply,
            "capture_reply": capture_reply,
            "measure_reply": measure_reply,
            "readback": readback,
            "after_capture": after,
            "external_brain_decision": decision,
        }

    def collect_logs(self) -> None:
        cut = datetime.fromtimestamp(self.run_started - 5)
        rows: list[dict[str, Any]] = []
        patterns = ("ERROR", "Traceback", "Exception", "native fault", "[UX_FIRST_IMAGE_VISIBLE]",
                    "change_series_on_viewer", "scroll_slices")
        for name in ("app.log", "download_diagnostics.log", "viewer_diagnostics.log", "db_diagnostics.log"):
            p = LOGDIR / name
            if not p.exists():
                continue
            try:
                data = p.read_bytes()[-5_000_000:].decode("utf-8", "replace")
            except Exception:
                continue
            for line in data.splitlines():
                if not any(x in line for x in patterns):
                    continue
                m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                if m:
                    try:
                        if datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") < cut:
                            continue
                    except ValueError:
                        pass
                rows.append({"log": name, "line": line[:500]})
        _write_json(self.out / "error_logs.json", {"rows": rows})

    # -- pipeline ----------------------------------------------------------
    def maybe_launch(self, enabled: bool) -> None:
        if not enabled:
            self.connect()
            reply = self.send("ping", {}, timeout_ms=5000)
            status = "pass" if reply.get("ok") else "fail"
            self.stage("app_open", status, "connected to running app" if reply.get("ok") else "ping failed", data=reply)
            return
        try:
            import lifecycle
            res = lifecycle.launch_app(wait_ready_s=int(self.config.get("launch_wait_s", 180)))
            self.stage("app_open", "pass" if res.get("ok") else "fail", "launch_app completed", data=res)
        except Exception as exc:  # noqa: BLE001
            self.stage("app_open", "fail", "launch_app failed", error=traceback.format_exc())
            raise exc
        self.connect()

    def maybe_probe(self, enabled: bool) -> None:
        if not enabled:
            self.stage("ui_probe", "skipped", "disabled by CLI")
            return
        assert self.client is not None
        try:
            self.probe = UiProbe(self.client, self.out, fps=float(self.config.get("probe_fps", 20.0)))
            self.stage("ui_probe", "pass", "live app window capture started")
        except Exception:
            self.probe = None
            self.stage("ui_probe", "fail", "could not start live UI capture", error=traceback.format_exc())

    def run(self, launch_app: bool, use_probe: bool) -> dict[str, Any]:
        try:
            self.maybe_launch(launch_app)
            self.maybe_probe(use_probe)
            self.run_patient_list()
            self.run_modality_switch_and_search()
            self.run_open_and_load()
            self.run_stack_ocr_measurement()
            self.collect_logs()
        finally:
            if self.probe is not None:
                self.probe.close()
            if self.client is not None:
                self.client.close()
            self.flush_report(partial=False)
            self.write_markdown()
        return self.report_obj(partial=False)

    def run_patient_list(self) -> None:
        date = str(self.config.get("date") or _yesterday_yyyymmdd())
        initial = str(self.config.get("initial_modality") or "MRI")
        query_modality = _query_modality(self.config, initial)
        ent = {
            "modality": query_modality,
            "date_from": date,
            "date_to": date,
            "source": str(self.config.get("source") or "server"),
            "limit": int(self.config.get("patient_limit", 50)),
        }
        reply = self.send("list_patients", ent, timeout_ms=90000, label="01_patient_list_mri", observe_s=4.0)
        rows = _rows(reply)
        if not rows and isinstance((reply.get("probe_record") or {}).get("reply"), dict):
            rows = _rows((reply.get("probe_record") or {}).get("reply") or {})
        status = "pass" if reply.get("ok") and rows else "fail"
        self.stage("patient_list_initial", status, f"{len(rows)} {initial} patient rows loaded", data={"criteria": ent, "count": len(rows)})

    def run_modality_switch_and_search(self) -> None:
        date = str(self.config.get("date") or _yesterday_yyyymmdd())
        target = str(self.config.get("target_modality") or "CT")
        query_modality = _query_modality(self.config, target)
        ent = {
            "modality": query_modality,
            "date_from": date,
            "date_to": date,
            "source": str(self.config.get("source") or "server"),
            "limit": int(self.config.get("patient_limit", 50)),
        }
        reply = self.send("list_patients", ent, timeout_ms=90000, label="02_patient_list_ct", observe_s=4.0)
        rows = _rows(reply)
        if not rows and isinstance((reply.get("probe_record") or {}).get("reply"), dict):
            rows = _rows((reply.get("probe_record") or {}).get("reply") or {})
        selected_id = str(self.config.get("patient_id") or "")
        selected = None
        if selected_id:
            selected = next((r for r in rows if _patient_key(r) == selected_id), None)
            if selected is None:
                search_ent = dict(ent)
                search_ent["patient_id"] = selected_id
                search_reply = self.send("list_patients", search_ent, timeout_ms=90000,
                                         label="03_search_patient", observe_s=3.0)
                search_rows = _rows(search_reply)
                if not search_rows and isinstance((search_reply.get("probe_record") or {}).get("reply"), dict):
                    search_rows = _rows((search_reply.get("probe_record") or {}).get("reply") or {})
                selected = next((r for r in search_rows if _patient_key(r) == selected_id), None)
                self.stage("patient_search", "pass" if selected else "fail",
                           f"searched patient_id={selected_id}", data={"count": len(search_rows)})
        else:
            selected = self.choose_patient(rows, target)
            if selected:
                search_ent = dict(ent)
                search_ent["patient_id"] = _patient_key(selected)
                search_reply = self.send("list_patients", search_ent, timeout_ms=90000,
                                         label="03_search_patient", observe_s=3.0)
                search_rows = _rows(search_reply)
                if not search_rows and isinstance((search_reply.get("probe_record") or {}).get("reply"), dict):
                    search_rows = _rows((search_reply.get("probe_record") or {}).get("reply") or {})
                found = any(_patient_key(r) == _patient_key(selected) for r in search_rows)
                self.stage("patient_search", "pass" if found else "fail",
                           f"searched selected patient {_patient_key(selected)}", data={"count": len(search_rows)})
        if not rows:
            self.stage("modality_switch", "fail", f"no {target} rows returned", data={"criteria": ent})
        else:
            target_rows = _rows_with_modality(rows, target)
            status = "pass" if target_rows else "fail"
            self.stage(
                "modality_switch",
                status,
                f"{len(target_rows)} {target} rows loaded",
                data={"criteria": ent, "count": len(target_rows), "raw_count": len(rows)},
            )
        if selected:
            self.selected_patient = dict(selected)
            self.stage("patient_selected", "pass", f"selected {_patient_key(selected)}", data=_safe_patient_entities(selected))
        else:
            self.stage("patient_selected", "fail", "no patient could be selected from target modality list")

    def run_open_and_load(self) -> None:
        if not self.selected_patient:
            return
        ent = _safe_patient_entities(self.selected_patient)
        self.send("select_patient", ent, timeout_ms=60000, label="04_select_patient", observe_s=4.0)
        open_reply = self.send("open_patient", ent, timeout_ms=90000, label="05_open_patient", observe_s=7.0)
        self.stage("patient_opened", "pass" if open_reply.get("ok") else "fail",
                   "open_patient dispatched", data={"entities": ent, "reply_ok": open_reply.get("ok")})

        def active_tab() -> Optional[dict[str, Any]]:
            reply = self.send("get_active_tab", {}, timeout_ms=30000)
            data = reply.get("data") or {}
            if reply.get("ok") and isinstance(data, dict) and data.get("patient_id"):
                return data
            return None

        active = self.poll("patient_open_wait", active_tab, timeout_s=float(self.config.get("open_timeout_s", 60)), interval_s=2.0)
        self.stage("patient_tab_active", "pass" if active else "fail",
                   "active patient tab available" if active else "active patient tab did not appear",
                   data=active or {})

        def loaded_series() -> Optional[dict[str, Any]]:
            reply = self.send("get_series_info", {}, timeout_ms=30000)
            series = _series(reply)
            return {"series": series, "count": len(series)} if series else None

        series_data = self.poll("series_wait", loaded_series, timeout_s=float(self.config.get("series_timeout_s", 90)), interval_s=2.0)
        if not series_data:
            self.stage("series_thumbnails_loaded", "fail", "no series metadata returned")
            return
        self.stage("series_thumbnails_loaded", "pass", f"{series_data['count']} series loaded", data=series_data)
        series = series_data["series"]
        selected_series = self.choose_series(series)
        if not selected_series:
            self.stage("series_selected", "fail", "no series selected by external brain")
            return
        self.selected_series = dict(selected_series)
        viewport = int(self.config.get("viewport", 0))
        change_ent: dict[str, Any] = {"viewport": viewport}
        if self.selected_series.get("series_number") not in (None, ""):
            change_ent["series_number"] = self.selected_series["series_number"]
        elif self.selected_series.get("series_uid"):
            change_ent["series_uid"] = self.selected_series["series_uid"]
        else:
            change_ent["series_index"] = 0
        change_reply = self.send("change_series", change_ent, timeout_ms=90000,
                                 label="06_import_series", observe_s=8.0)
        self.stage("series_imported", "pass" if change_reply.get("ok") else "fail",
                   "series imported into viewport", data={"series": self.selected_series, "entities": change_ent})

    def run_stack_ocr_measurement(self) -> None:
        viewport = int(self.config.get("viewport", 0))

        def viewport_ready() -> Optional[dict[str, Any]]:
            reply = self.send("query_viewport_state", {}, timeout_ms=30000)
            v0 = _viewport0(reply)
            if (v0.get("slice_count") or 0) > 0:
                return v0
            return None

        vstate = self.poll("viewport_wait", viewport_ready, timeout_s=float(self.config.get("viewport_timeout_s", 90)), interval_s=2.0)
        if not vstate:
            self.stage("viewport_loaded", "fail", "viewport did not report loaded slices")
            return
        self.stage("viewport_loaded", "pass", "viewport has image stack", data=vstate)
        slice_count = int(vstate.get("slice_count") or 1)
        target_slice = self.choose_slice_index(vstate)
        scroll_reply = self.send("scroll_slices", {"viewport": viewport, "index": target_slice},
                                 timeout_ms=30000, label="07_stack_middle_slice", observe_s=3.0)
        scroll_data = scroll_reply.get("data") or {}
        if not scroll_data and isinstance((scroll_reply.get("probe_record") or {}).get("reply"), dict):
            scroll_data = ((scroll_reply.get("probe_record") or {}).get("reply") or {}).get("data") or {}
        self.stage("stack_navigation", "pass" if scroll_reply.get("ok") else "fail",
                   f"moved to slice {target_slice + 1}/{slice_count}", data=scroll_data)

        text = ""
        shot = self.stable_png_for("07_stack_middle_slice")
        if not shot:
            cap = self.send(
                "capture_viewport",
                {"viewport": viewport, "scope": "viewport", "filename_prefix": "clinical_ocr_capture"},
                timeout_ms=30000,
            )
            cap_path = Path(str(((cap.get("data") or {}) or {}).get("path") or ""))
            shot = cap_path if cap_path.exists() else None
        if not shot:
            self.stage("ocr_capture", "fail", "no stable screenshot or viewport capture available for OCR")
        else:
            text, reason = self.run_ocr(shot)
            self.ocr_text = text
            self.stage("ocr_capture", "pass" if text else "fail",
                       reason, data={"ocr_chars": len(text), "image": str(shot)}, artifacts=[str(shot)])

        measured, msg = self.coordinate_measurement()
        if measured and self.probe is not None:
            self.send("query_viewport_state", {}, timeout_ms=30000,
                      label="08_after_measurement", observe_s=2.0)
            shot2 = self.stable_png_for("08_after_measurement") or shot
            m_text = ""
            if shot2 is not None:
                m_text, _ = self.run_ocr(shot2)
            self.measurement_result = _extract_measurement(m_text) or _extract_measurement(text)
            self.stage("measurement", "pass" if self.measurement_result else "fail",
                       "measurement GUI drag completed" if self.measurement_result else "measurement value not readable",
                       data={"message": msg, "text": m_text[:1000]},
                       artifacts=[str(shot2)] if shot2 is not None else [])
            return

        actions_reply = self.send("list_actions", {}, timeout_ms=30000, mode="read_only")
        actions = actions_reply.get("data") or []
        strategy = self.decide_measurement_strategy(actions)
        known_hooks = [a for a in actions if str(a) in {"activate_tool", "measure_distance", "viewer_measure_distance", "get_measurements"}]
        if known_hooks:
            ok, message, artifacts, data = self.commandbus_measurement(viewport, target_slice, shot)
            data.update({"actions": known_hooks, "external_brain_strategy": strategy})
            self.stage("measurement", "pass" if ok else "blocked",
                       message if ok else f"CommandBus measurement unavailable: {message}",
                       data=data, artifacts=artifacts)
        else:
            self.stage("measurement", "blocked",
                       "no measurement CommandBus hook and no coordinate_drag scenario configured",
                       data={"reason": msg, "external_brain_strategy": strategy})


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, help="scenario JSON")
    p.add_argument("--out-dir", type=Path, help="artifact output directory")
    p.add_argument("--date", help="study date as YYYYMMDD; default is yesterday")
    p.add_argument("--patient-id", help="target patient id; default selects the first target modality row")
    p.add_argument("--launch-app", action="store_true", help="launch/connect to the source app before running")
    p.add_argument("--no-ui-probe", action="store_true", help="disable live GUI screenshots")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    config = _read_json(args.config)
    if args.date:
        config["date"] = args.date
    if args.patient_id:
        config["patient_id"] = args.patient_id
    if "date" not in config:
        config["date"] = _yesterday_yyyymmdd()
    out_dir = args.out_dir or (DEFAULT_OUT_ROOT / time.strftime("%Y%m%d_%H%M%S"))
    runner = ClinicalAgentValidation(config, out_dir)
    try:
        report = runner.run(launch_app=args.launch_app or bool(config.get("launch_app")),
                            use_probe=not args.no_ui_probe)
    except Exception:
        runner.stage("runner_exception", "fail", "unhandled exception", error=traceback.format_exc())
        runner.collect_logs()
        runner.flush_report(partial=False)
        runner.write_markdown()
        raise
    print(json.dumps({
        "ok": report["overall_status"] == "pass",
        "status": report["overall_status"],
        "report": str(out_dir / "report.json"),
        "markdown": str(out_dir / "report.md"),
    }, indent=2))
    return 0 if report["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
