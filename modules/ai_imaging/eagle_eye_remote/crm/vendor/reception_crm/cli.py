from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from .analytics import build_daily_report
from .agent_router import route_command
from .collector import collect_day
from .config import load_config
from .core.dispatcher import dispatch
from .core.types import DispatchContext, Principal, ToolCall
from .management import (
    render_persian_report,
)
from .operations import load_operations
from .permissions import load_permissions
from .settings import load_settings, resolve_center
from .storage import Storage
from .write_executor import execute_operation


def parse_business_date(value: str) -> date:
    normalized = value.lower().strip()
    if normalized == "today":
        return date.today()
    if normalized == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(value)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="reception-crm")
    parser.add_argument("--config", help="Path to endpoint config JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check local collector configuration.")

    collect_parser = subparsers.add_parser("collect", help="Collect CRM API data for a date.")
    collect_parser.add_argument("--date", default="today", help="Business date: today, yesterday, or YYYY-MM-DD.")

    report_parser = subparsers.add_parser("report", help="Build a report from stored daily data.")
    report_parser.add_argument("--date", default="today", help="Business date: today, yesterday, or YYYY-MM-DD.")

    crm_parser = subparsers.add_parser("crm", help="Run live INO CRM analytics skills.")
    crm_parser.add_argument(
        "skill",
        choices=[
            "daily-summary",
            "patient-list",
            "financial-analysis",
            "cashier-reconciliation",
            "risk-analysis",
            "trend-analysis",
            "reporting-queue",
            "report-current",
            "report-logs",
            "report-print-preview",
            "report-template-list",
            "report-template-search",
            "report-template-get",
            "report-template-refresh",
            "report-draft-plan",
        ],
    )
    crm_parser.add_argument("--date", default="today", help="today, yesterday, YYYY-MM-DD, or Jalali YYYY/MM/DD.")
    crm_parser.add_argument("--days", type=int, default=1, help="Number of Jalali days ending at --date.")
    crm_parser.add_argument("--modality", help="Patient-list modality filter: MRI, CT, US, XR, or local code.")
    crm_parser.add_argument("--compare", default="yesterday", choices=["yesterday", "last-week", "last-month"])
    crm_parser.add_argument("--reception-id", help="Numeric ReceptionID for clinical reporting tools.")
    crm_parser.add_argument("--workflow-id", help="Workflow/reception ObjectId for imagingWorkflow report tools.")
    crm_parser.add_argument("--template-id", help="Local clinical report template id.")
    crm_parser.add_argument("--modality-id", help="CRM modality id/code for report template/glossary refresh.")
    crm_parser.add_argument("--category", help="Clinical sample-report category filter.")
    crm_parser.add_argument("--priority", help="Clinical sample-report priority filter.")
    crm_parser.add_argument("--personnel-id", help="Personnel/radiologist id filter for local report templates.")
    crm_parser.add_argument("--source", help="Local report template source filter.")
    crm_parser.add_argument("--query", help="Local report template search query.")
    crm_parser.add_argument("--include-html", action="store_true", help="Include HTML snippets in template search results.")
    crm_parser.add_argument("--max-content-chars", type=int, help="Max HTML/plain preview characters for template search.")
    crm_parser.add_argument("--page", type=int, default=1)
    crm_parser.add_argument("--limit", type=int, default=20)
    crm_parser.add_argument("--start-date", dest="startDate", help="Jalali start date for report queue filters.")
    crm_parser.add_argument("--end-date", dest="endDate", help="Jalali end date for report queue filters.")
    crm_parser.add_argument("--search", help="Patient/name/national-code search for report queue.")
    crm_parser.add_argument("--status", help="Report queue status filter.")
    crm_parser.add_argument("--radiologist", help="Radiologist id filter.")
    crm_parser.add_argument("--has-voice-attachment", dest="hasVoiceAttachment", choices=["yes", "no", ""], default="")
    crm_parser.add_argument("--report-text", help="Plain text clinical report draft. Used only for dry-run planning.")
    crm_parser.add_argument("--report-html", help="Ready HTML clinical report draft. Used only for dry-run planning.")
    crm_parser.add_argument(
        "--target-status",
        default="awaiting_physician_approval",
        choices=[
            "pending",
            "awaiting_physician_approval",
            "awaiting_approval",
            "physician_approved",
            "awaiting_secretary_approval",
            "secretary_approved",
            "completed",
            "archived",
        ],
    )
    crm_parser.add_argument("--user", default="local_cli", help="Principal user for permission checks.")
    crm_parser.add_argument("--center", default=resolve_center(), help="Center for permission checks (defaults to the configured center).")
    crm_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")

    operations_parser = subparsers.add_parser("operations", help="Inspect safe CRM operation registry.")
    operations_parser.add_argument("action", choices=["list", "show", "plan", "execute"])
    operations_parser.add_argument("name", nargs="?", help="Operation name for show/plan.")
    operations_parser.add_argument("--registry", help="Path to operations.json.")
    operations_parser.add_argument("--input-json", default="{}", help="JSON inputs for operation planning.")
    operations_parser.add_argument("--user", help="Requesting user for execution checks.")
    operations_parser.add_argument("--center", help="Center for execution checks.")
    operations_parser.add_argument("--confirm", help="Exact confirmation phrase, for example: EXECUTE reception.add")
    operations_parser.add_argument(
        "--execute",
        action="store_true",
        help="Legacy compatibility flag. This path is retired and always remains dry-run only.",
    )

    permissions_parser = subparsers.add_parser("permissions", help="Inspect role permissions.")
    permissions_parser.add_argument("action", choices=["check"])
    permissions_parser.add_argument("--user", required=True)
    permissions_parser.add_argument("--center", required=True)
    permissions_parser.add_argument("--operation", required=True)
    permissions_parser.add_argument("--permission-action", choices=["read", "plan", "execute"], default="execute")
    permissions_parser.add_argument("--safety", default="clinical_write")

    agent_parser = subparsers.add_parser("agent", help="Route transcribed voice/text commands.")
    agent_parser.add_argument("action", choices=["route"])
    agent_parser.add_argument("--text", required=True, help="Transcribed user command.")
    agent_parser.add_argument("--user", help="Requesting user.")
    agent_parser.add_argument("--center", help="Center or tenant identifier.")
    agent_parser.add_argument("--input-json", default="{}", help="Structured inputs already collected by the UI.")

    gateway_parser = subparsers.add_parser(
        "gateway",
        help="Run the retired local gateway for explicit loopback compatibility testing only.",
    )
    gateway_parser.add_argument("--host", default="127.0.0.1")
    gateway_parser.add_argument("--port", type=int, default=8765)

    http_api_parser = subparsers.add_parser("http-api", help="Run the mobile/agent HTTP API adapter.")
    http_api_parser.add_argument("--host", default="127.0.0.1")
    http_api_parser.add_argument("--port", type=int, default=8770)

    subparsers.add_parser("mcp", help="Run the lightweight stdio MCP server.")

    settings_parser = subparsers.add_parser("settings", help="Inspect active multi-center settings.")
    settings_parser.add_argument("action", choices=["show"])

    args = parser.parse_args()
    config = load_config(args.config)
    storage = Storage(config.data_root)
    storage.ensure_layout()

    if args.command == "doctor":
        output = {
            "config_path": str(config.config_path),
            "data_root": str(config.data_root),
            "endpoint_count": len(config.endpoints),
            "endpoints": [endpoint.name for endpoint in config.endpoints],
            "folders_ready": all(
                (Path(config.data_root) / child).exists()
                for child in ["config", "data", "exports", "logs", "manifests", "reports"]
            ),
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    elif args.command == "collect":
        result = collect_day(config, parse_business_date(args.date))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "report":
        path = build_daily_report(config.data_root, parse_business_date(args.date))
        print(path)
    elif args.command == "crm":
        tool_arguments = {
            "date": args.date,
            "days": args.days,
            "data_root": str(config.data_root),
            "modality": args.modality,
            "compare": args.compare,
            "reception_id": args.reception_id,
            "workflow_id": args.workflow_id,
            "template_id": args.template_id,
            "modality_id": args.modality_id,
            "category": args.category,
            "priority": args.priority,
            "personnel_id": args.personnel_id,
            "source": args.source,
            "query": args.query,
            "include_html": args.include_html,
            "max_content_chars": args.max_content_chars,
            "page": args.page,
            "limit": args.limit,
            "startDate": args.startDate,
            "endDate": args.endDate,
            "search": args.search,
            "status": args.status,
            "radiologist": args.radiologist,
            "hasVoiceAttachment": args.hasVoiceAttachment,
            "report_text": args.report_text,
            "report_html": args.report_html,
            "target_status": args.target_status,
        }
        tool_arguments = {key: value for key, value in tool_arguments.items() if value is not None}
        tool_result = dispatch(
            ToolCall(args.skill, tool_arguments),
            context=DispatchContext(
                principal=Principal(user=args.user, center=args.center, roles=[]),
                client="cli",
                data_root=config.data_root,
            ),
        )
        result = tool_result.unwrap()
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(render_persian_report(result))
    elif args.command == "operations":
        registry = load_operations(args.registry)
        if args.action == "list":
            print(json.dumps(registry.list_operations(), ensure_ascii=False, indent=2))
        elif args.action == "show":
            if not args.name:
                raise SystemExit("Operation name is required for show.")
            print(json.dumps(registry.get(args.name), ensure_ascii=False, indent=2))
        elif args.action == "plan":
            if not args.name:
                raise SystemExit("Operation name is required for plan.")
            inputs = json.loads(args.input_json)
            plan = registry.plan(args.name, inputs)
            print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
        elif args.action == "execute":
            if not args.name:
                raise SystemExit("Operation name is required for execute.")
            inputs = json.loads(args.input_json)
            result = execute_operation(
                args.name,
                inputs=inputs,
                user=args.user,
                center=args.center,
                confirmation=args.confirm,
                execute=args.execute,
                registry=registry,
                data_root=config.data_root,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "permissions":
        policy = load_permissions()
        decision = policy.check(args.user, args.center, args.operation, args.permission_action, args.safety)
        print(json.dumps(decision.as_dict(), ensure_ascii=False, indent=2))
    elif args.command == "agent":
        inputs = json.loads(args.input_json)
        result = route_command(args.text, user=args.user, center=args.center, inputs=inputs)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "gateway":
        from .voice_gateway import run_gateway

        run_gateway(host=args.host, port=args.port)
    elif args.command == "http-api":
        from .adapters.http_api import run_http_api

        run_http_api(host=args.host, port=args.port)
    elif args.command == "mcp":
        from .mcp_server import run_stdio_server

        run_stdio_server()
    elif args.command == "settings":
        settings = load_settings()
        print(json.dumps(settings.public_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
