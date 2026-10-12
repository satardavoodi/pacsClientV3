from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from .operations import OperationError, OperationRegistry, load_operations


#: Annotated because the literals mix strings, lists and ints, so each row
#: infers as dict[str, object] and every keyword list reaches score_keywords as
#: an opaque object. The table has always held Any; now it says so.
ANALYTICS_ROUTES: list[dict[str, Any]] = [
    {
        "name": "daily-summary",
        "label": "خلاصه کار امروز",
        "keywords": ["گزارش", "کارکرد", "امروز", "خلاصه", "وضعیت امروز"],
        "priority": 0,
        "cli": ["crm", "daily-summary", "--date", "today"],
    },
    {
        "name": "patient-list",
        "label": "فهرست بیماران",
        "keywords": ["لیست بیمار", "فهرست بیمار", "بیماران", "mri", "ct", "سونو", "رادیولوژی"],
        "priority": 2,
        "cli": ["crm", "patient-list", "--date", "today"],
    },
    {
        "name": "financial-analysis",
        "label": "بررسی درآمدی",
        "keywords": ["درآمد", "صندوق", "کارت", "نقد", "بدهی", "تخفیف", "پولی"],
        "priority": 2,
        "cli": ["crm", "financial-analysis", "--date", "today"],
    },
    {
        "name": "cashier-reconciliation",
        "label": "بررسی صندوق",
        "keywords": ["ناهمخوانی", "کسری", "اضافه", "تطبیق", "صندوقدار"],
        "priority": 3,
        "cli": ["crm", "cashier-reconciliation", "--date", "today"],
    },
    {
        "name": "risk-analysis",
        "label": "پرونده‌های نیازمند پیگیری",
        "keywords": ["پرخطر", "پیگیری", "مشکوک", "اصلاح", "ریسک"],
        "priority": 3,
        "cli": ["crm", "risk-analysis", "--date", "today"],
    },
    {
        "name": "trend-analysis",
        "label": "روند کار",
        "keywords": ["روند", "مقایسه", "دیروز", "هفته", "ماه"],
        "priority": 2,
        "cli": ["crm", "trend-analysis", "--date", "today", "--compare", "yesterday"],
    },
]

WRITE_ROUTES: list[dict[str, Any]] = [
    {
        "operation": "reception.add",
        "label": "پذیرش بیمار",
        "keywords": ["پذیرش", "ثبت پذیرش", "بیمار پذیرش"],
    },
    {
        "operation": "appointments.schedule",
        "label": "ثبت نوبت",
        "keywords": ["نوبت", "وقت", "رزرو", "schedule"],
    },
    {
        "operation": "prescriptions.submit",
        "label": "نسخه‌نویسی",
        "keywords": ["نسخه", "دارو", "خدمت بیمه", "prescription"],
    },
    {
        "operation": "patients.add_patient",
        "label": "ساخت پرونده بیمار",
        "keywords": ["بیمار جدید", "ثبت بیمار", "پرونده بیمار"],
    },
]


@dataclass(frozen=True)
class TokenEstimate:
    input_tokens: int
    output_tokens_reserved: int
    total_estimated_tokens: int
    pricing_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens_reserved": self.output_tokens_reserved,
            "total_estimated_tokens": self.total_estimated_tokens,
            "pricing_status": self.pricing_status,
        }


def route_command(
    text: str,
    user: str | None = None,
    center: str | None = None,
    inputs: dict[str, Any] | None = None,
    registry: OperationRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or load_operations()
    normalized = normalize_text(text)
    inputs = inputs or {}
    token_estimate = estimate_tokens(text)

    analytics = best_analytics_route(normalized)
    write_route = best_write_route(normalized)

    if write_route and (not analytics or score_keywords(normalized, write_route["keywords"]) >= analytics["score"]):
        return build_write_response(text, user, center, write_route, inputs, registry, token_estimate)

    if analytics:
        return {
            "type": "analytics",
            "status": "ready",
            "received_at": datetime.now().isoformat(timespec="seconds"),
            "user": user,
            "center": center,
            "text": text,
            "skill": analytics["name"],
            "label": analytics["label"],
            "suggested_cli": ["python", "-m", "reception_crm.cli", *analytics["cli"]],
            "needs_confirmation": False,
            "token_estimate": token_estimate.as_dict(),
            "notes": [
                "برای این نوع درخواست، API خواندن منبع اصلی است.",
                "اگر گزارش مربوط به امروز باشد، داده‌ها در طول روز ممکن است تغییر کنند.",
            ],
        }

    return {
        "type": "unknown",
        "status": "needs_clarification",
        "received_at": datetime.now().isoformat(timespec="seconds"),
        "user": user,
        "center": center,
        "text": text,
        "needs_confirmation": False,
        "token_estimate": token_estimate.as_dict(),
        "notes": [
            "درخواست به هیچ مسیر آماده‌ای وصل نشد.",
            "برای اجرای واقعی باید یا skill تازه تعریف شود یا operation جدید به registry اضافه شود.",
        ],
    }


def build_write_response(
    text: str,
    user: str | None,
    center: str | None,
    write_route: dict[str, Any],
    inputs: dict[str, Any],
    registry: OperationRegistry,
    token_estimate: TokenEstimate,
) -> dict[str, Any]:
    operation_name = write_route["operation"]
    try:
        plan = registry.plan(operation_name, inputs)
        plan_dict = plan.as_dict()
        status = "dry_run_ready" if not plan.missing_required_inputs else "missing_inputs"
    except OperationError as exc:
        plan_dict = {"error": str(exc)}
        status = "operation_error"

    return {
        "type": "write_plan",
        "status": status,
        "received_at": datetime.now().isoformat(timespec="seconds"),
        "user": user,
        "center": center,
        "text": text,
        "operation": operation_name,
        "label": write_route["label"],
        "needs_confirmation": True,
        "execution_allowed": False,
        "plan": plan_dict,
        "token_estimate": token_estimate.as_dict(),
        "notes": [
            "این خروجی فقط برنامه عملیات است و چیزی در CRM نمی‌نویسد.",
            "اجرای write بعد از تکمیل ورودی‌ها، اعتبارسنجی، و تأیید صریح مجاز می‌شود.",
        ],
    }


def best_analytics_route(normalized_text: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for route in ANALYTICS_ROUTES:
        score = score_keywords(normalized_text, route["keywords"])
        if score:
            candidates.append({**route, "score": score})
    return max(candidates, key=lambda item: (item["score"], item.get("priority", 0))) if candidates else None


def best_write_route(normalized_text: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for route in WRITE_ROUTES:
        score = score_keywords(normalized_text, route["keywords"])
        if score:
            candidates.append({**route, "score": score})
    return max(candidates, key=lambda item: item["score"]) if candidates else None


def score_keywords(normalized_text: str, keywords: Iterable[str]) -> int:
    """Widened from `list[str]`: this only iterates.

    The route tables hand it whatever their literals infer to — `object` in one
    place, `Sequence[str]` in another — and every call site was reported as a
    type error for passing something this function is perfectly happy with. An
    annotation narrower than the function's real contract makes correct callers
    look wrong, which is how a checker earns being ignored.
    """
    return sum(1 for keyword in keywords if normalize_text(keyword) in normalized_text)


def normalize_text(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u200c", " ")
    )


def estimate_tokens(text: str, output_tokens_reserved: int = 700) -> TokenEstimate:
    # Persian text often tokenizes less compactly than English; this is intentionally conservative.
    input_tokens = max(1, int(len(text) / 3) + 40)
    return TokenEstimate(
        input_tokens=input_tokens,
        output_tokens_reserved=output_tokens_reserved,
        total_estimated_tokens=input_tokens + output_tokens_reserved,
        pricing_status="token estimate only; model pricing is not configured in this project",
    )
