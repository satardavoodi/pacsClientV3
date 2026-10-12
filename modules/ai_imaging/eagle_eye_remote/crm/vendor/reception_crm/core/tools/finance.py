"""`finance.metric` — ask for a financial figure BY MEANING, not by field.

The contract this implements: the model sends what it wants in business terms —

    {"metric": "net_cashier_amount", "dateBasis": "transaction_date", "date": "yesterday"}

— and gets back the number together with its definition, its formula, its source
path, the identities it participates in, and the metrics it is most often
confused with. An ambiguous request like `{"amount": "today"}` cannot be
expressed.

Why a whole tool for this: every financial mistake in this project has been a
naming mistake, not an arithmetic one. «بیمارها چقدر بدهکار موندن؟» was answered
with the day's entire reception value because the model picked a plausible field
from a report it had already fetched. Choosing a FIELD is where the error
happens; choosing a METRIC is checkable.

`finance.vocabulary` is the companion: it lists what exists, so a metric is
looked up rather than guessed.
"""

from __future__ import annotations

from typing import Any

from ... import finance
from ..registry import ToolRegistry
from ..types import ToolDefinition


def _default_data_root() -> str:
    """The same snapshot root the HTTP adapter injects, resolved the same way."""
    from ...adapters.http_api import data_root

    return str(data_root())


def _dig(payload: Any, path: str) -> Any:
    node = payload
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def _vocabulary(args: dict[str, Any]) -> dict[str, Any]:
    wanted = args.get("metric")
    if wanted:
        try:
            return {"skill": "finance.vocabulary", "metric": finance.get(wanted).as_dict()}
        except finance.UnknownMetric as exc:
            return {"skill": "finance.vocabulary", "error": exc.as_dict()}
    return {
        "skill": "finance.vocabulary",
        "metrics": [m.as_dict() for m in finance.METRICS],
        "identities": finance.identities(),
        "date_bases": {
            finance.RECEPTION_DATE: "money that is OWED — receptions created in the period",
            finance.TRANSACTION_DATE: "money that MOVED — payments recorded in the period",
        },
        "rule_fa": (
            "پولی که جابه‌جا شده بر مبنای تاریخ تراکنش است و پولی که بدهکار است بر مبنای "
            "تاریخ پذیرش. اختلاف این دو «مغایرت» نیست."
        ),
    }


#: How deep a derivation may nest. `patient_balance_total` reaches
#: `consumables_value`, which reaches two sourced metrics — two levels. The cap
#: is a backstop against a future component cycle, not a design limit; a cycle
#: would otherwise recurse until the stack ended, and a financial tool that
#: crashes is indistinguishable to the caller from one that refuses.
_MAX_DERIVATION_DEPTH = 4


def _derive(spec: Any, args: dict[str, Any], depth: int) -> dict[str, Any]:
    """Compute a metric no tool exposes, from metrics that are exposed.

    Every component is fetched through `_metric` itself, over the SAME period
    arguments, so a derived figure can never silently mix two date windows and
    can never reach a tool the direct path would have refused.

    It fails LOUDLY and returns no number if any component is missing. A partial
    sum here would be a figure that looks complete and is short by whatever
    could not be read — which is precisely the failure this metric was added to
    correct, reproduced one level up.
    """
    if depth >= _MAX_DERIVATION_DEPTH:
        return {
            "skill": "finance.metric",
            "value": None,
            "metric": spec.as_dict(),
            "error": {
                "code": "DERIVATION_TOO_DEEP",
                "message": f"{spec.name} nests components more than "
                           f"{_MAX_DERIVATION_DEPTH} deep",
                "message_fa": "زنجیرهٔ محاسبهٔ این شاخص بیش از حد عمیق است.",
            },
        }

    period = {k: v for k, v in args.items() if k != "metric" and k != "dateBasis"}
    parts: list[dict[str, Any]] = []
    total = 0
    for name, sign in spec.components:
        inner = _metric({**period, "metric": name}, depth + 1)
        value = inner.get("value")
        parts.append({
            "metric": name,
            "sign": sign,
            "value": value,
            "source": (inner.get("traceable_to") or {}).get("tool")
                      or (inner.get("derived_from") and "derived"),
            "error": inner.get("error"),
        })
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return {
                "skill": "finance.metric",
                "value": None,
                "metric": spec.as_dict(),
                "derived_from": parts,
                "error": {
                    "code": "COMPONENT_UNAVAILABLE",
                    "message": f"{spec.name} needs {name}, which returned no number",
                    "message_fa": (
                        "برای محاسبهٔ این شاخص یکی از اجزای آن در دسترس نبود؛ "
                        "عدد ناقص ارائه نمی‌شود."
                    ),
                },
            }
        total += sign * int(value)

    return {
        "skill": "finance.metric",
        "metric": spec.as_dict(),
        "value": total,
        "derived_from": parts,
        "traceable_to": {
            "tool": "derived",
            "path": spec.formula,
            "date_basis": spec.date_basis,
        },
        "identities": [i for i in finance.identities() if spec.name in i["identity"]],
    }


def _metric(args: dict[str, Any], _depth: int = 0) -> dict[str, Any]:
    asked = str(args.get("metric") or "")
    basis = args.get("dateBasis") or args.get("date_basis")
    try:
        spec = finance.check_basis(asked, basis)
    except finance.UnknownMetric as exc:
        # Never resolve a financial metric by similarity. A plausible wrong
        # number is worse than no number, because someone acts on it.
        return {"skill": "finance.metric", "value": None, "error": exc.as_dict()}
    except finance.WrongDateBasis as exc:
        return {"skill": "finance.metric", "value": None, "error": exc.as_dict()}

    if not spec.source_tool and spec.components:
        return _derive(spec, args, _depth)

    if not spec.source_tool:
        return {
            "skill": "finance.metric",
            "value": None,
            "metric": spec.as_dict(),
            "error": {
                "code": "NO_SOURCE_TOOL",
                "message": f"{spec.name} is defined but no tool exposes it directly",
                "message_fa": (
                    "این شاخص تعریف شده اما هیچ ابزاری آن را مستقیم ارائه نمی‌کند؛ "
                    "برای همین عدد آن اینجا محاسبه نمی‌شود."
                ),
            },
        }

    # Calls the SAME handler function the source tool registers — one
    # implementation, so a metric can never drift from the tool everything else
    # reads.
    #
    # It does NOT re-enter `dispatch`. Dispatching from inside a tool opens a
    # second authorization boundary with no principal behind it, and the guards
    # correctly refused every metric with PERMISSION_DENIED. Manufacturing a
    # principal to get past our own permission check would be the wrong fix:
    # the check was right. The outer `finance.metric` call is the one that was
    # authorised, and it is the one that governs.
    #
    # What that trades away is the inner permission check, so the escalation is
    # closed explicitly below: this facade may only ever reach READ tools. If a
    # source tool were ever changed to a write, this refuses instead of becoming
    # a way around the confirmation gate.
    from ..registry import default_registry

    source = default_registry().get(spec.source_tool)
    if source.safety != "read" or source.permission_action != "read":
        return {
            "skill": "finance.metric",
            "value": None,
            "metric": spec.as_dict(),
            "error": {
                "code": "NOT_A_READ_SOURCE",
                "message": (
                    f"{spec.source_tool} is not read-only; finance.metric will not "
                    "call it"
                ),
            },
        }

    # ⚠️ NORMALISE THE RANGE NAMES BEFORE HANDING THEM ON. This tool's schema
    # says `startDate`/`endDate`; the report tools underneath say
    # `dateFrom`/`dateTo`. Passing the caller's spelling straight through meant
    # a range reached a report that did not recognise it, was dropped, and the
    # metric came back for TODAY under the caller's date — the same silent
    # substitution the benchmark caught one level up, and harder to see here
    # because the reply still carries the metric's definition and source path.
    period: dict[str, Any] = {}
    if args.get("date"):
        period["date"] = args["date"]
    start = args.get("dateFrom") or args.get("startDate")
    end = args.get("dateTo") or args.get("endDate")
    if start:
        period["dateFrom"] = start
    if end:
        period["dateTo"] = end
    if not period:
        period["date"] = "today"

    # The report tools require `data_root`, which the HTTP adapter injects on the
    # way in. Dispatching from inside a tool skips that, and every metric came
    # back `VALIDATION: Missing required input(s): data_root` — a refusal that
    # looked exactly like the deliberate ones beside it. Carry the caller's root
    # through, or fall back to the same default the adapter uses.
    period["data_root"] = args.get("data_root") or _default_data_root()

    try:
        payload = source.handler(period) or {}
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        return {
            "skill": "finance.metric",
            "value": None,
            "metric": spec.as_dict(),
            "error": {"code": "SOURCE_FAILED", "message": f"{type(exc).__name__}: {exc}",
                      "message_fa": "منبع این شاخص پاسخ نداد؛ عدد قابل ارائه نیست."},
        }
    value = _dig(payload, spec.source_path)

    return {
        "skill": "finance.metric",
        "metric": spec.as_dict(),
        "value": value,
        "period": payload.get("period"),
        "traceable_to": {
            "tool": spec.source_tool,
            "path": spec.source_path,
            "date_basis": spec.date_basis,
        },
        "identities": [i for i in finance.identities() if spec.name in i["identity"]],
        "value_is_null_means": (
            None if value is not None else
            "the source answered but that field was absent — this is 'not reported', "
            "not 'zero'"
        ),
    }


def register_finance_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="finance.metric",
            kind="skill",
            handler=_metric,
            description=(
                "Ask for a financial figure BY MEANING. Give `metric` (a normalized name "
                "such as `net_cashier_amount`, `patient_balance_total`, `service_value`), "
                "optionally `dateBasis`, and a date. Returns the number WITH its "
                "definition, formula, source field, date basis and the metrics it is "
                "commonly confused with.\n"
                "PREFER THIS over picking a field out of a report yourself whenever the "
                "question is about money. Every financial error in this system has been a "
                "naming error, not an arithmetic one — «بیمارها چقدر بدهکارند» was once "
                "answered with the day's whole reception value because a plausible-looking "
                "field was chosen from a report already in hand.\n"
                "It REFUSES rather than guesses: an unknown metric name returns the list "
                "of real ones, and asking for a transaction-dated metric on a reception "
                "basis (or the reverse) returns an error naming both. A financial answer "
                "that cannot be traced to a defined metric should not be given.\n"
                "TWO REVENUE BASES, and every patient figure has one of each. The "
                "reception software's own summary is on the SERVICE basis and leaves "
                "consumables out of it; the reception header includes them. For «چقدر "
                "بدهکار موندن» use `patient_balance_total` — `patient_balance` is the "
                "service-basis figure and was short by nearly 40% on the day it was "
                "measured. Some metrics are DERIVED from others; the reply then carries "
                "`derived_from` listing each component, its sign and its own source, so "
                "the arithmetic stays checkable.\n"
                "Call `finance.vocabulary` first if unsure what exists."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": ["metric"],
                "properties": {
                    "metric": {"type": "string",
                               "description": "Normalized metric name or a Persian alias."},
                    "dateBasis": {"type": "string",
                                  "enum": [finance.RECEPTION_DATE, finance.TRANSACTION_DATE],
                                  "description": "Optional; validated against the metric."},
                    "date": {"type": "string", "description": "Jalali date, today or yesterday."},
                    "dateFrom": {"type": "string", "description": "Start of a Jalali range."},
                    "dateTo": {"type": "string", "description": "End of a Jalali range."},
                    # Kept because the schema published them for several
                    # versions and a caller may still send them; normalised onto
                    # dateFrom/dateTo before the source tool ever sees them.
                    "startDate": {"type": "string", "description": "Alias of dateFrom."},
                    "endDate": {"type": "string", "description": "Alias of dateTo."},
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="finance.vocabulary",
            kind="skill",
            handler=_vocabulary,
            description=(
                "What financial metrics exist and what each one MEANS: definition in "
                "English and Persian, level, date basis, source field, formula, the "
                "identities it participates in, and what it must not be confused with. "
                "Pass `metric` for one, or nothing for the whole catalogue plus the "
                "reconciliation identities.\n"
                "Use it before answering any money question you are not certain of, and "
                "whenever the user's words could mean two different figures — «درآمد», "
                "«دریافتی», «بدهی» and «صندوق» each map to more than one metric."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "properties": {"metric": {"type": "string"}},
            },
        )
    )
