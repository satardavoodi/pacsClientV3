"""Turn technical failures into something a receptionist can act on.

A raw ``ConnectionError: [Errno 111] Connection refused`` tells the user
nothing they can do. ``explain()`` maps the failure to three things:

    headline   what went wrong, in plain Persian
    advice     the next thing to try
    details    the original text, kept for support and shown only on demand

The mapping is deliberately pattern-based rather than exception-class based:
the failure text reaches the UI as a string (workers marshal exceptions across
the thread boundary), and the same wording arrives from ``urllib``, ``requests``
and our own ``RuntimeError`` re-raises.

Nothing is ever swallowed. ``details`` always carries the original message, so
support keeps the exact error while the user reads the plain one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Explained:
    headline: str
    advice: str = ""
    details: str = ""
    tone: str = "bad"

    def one_line(self) -> str:
        return f"{self.headline} {self.advice}".strip()


# (regex, headline, advice) — first match wins, so order from specific to broad.
_RULES: list[tuple[str, str, str]] = [
    # -- authentication --------------------------------------------------- #
    (
        r"\b401\b|unauthor|invalid[_\s-]?credential|نام کاربری یا رمز|bad credentials",
        "نام کاربری یا رمز عبور پذیرفته نشد.",
        "همان نام کاربری و رمزی را وارد کنید که با آن وارد نرم‌افزار پذیرش می‌شوید. "
        "اگر اخیراً رمز خود را عوض کرده‌اید، اینجا هم باید به‌روز شود.",
    ),
    (
        r"\b403\b|forbidden|permission denied|دسترسی",
        "این حساب کاربری اجازهٔ انجام این کار را ندارد.",
        "با مسئول نرم‌افزار پذیرش تماس بگیرید تا سطح دسترسی این نام کاربری بررسی شود.",
    ),
    # -- reachability ----------------------------------------------------- #
    (
        r"connection refused|errno 111|10061|actively refused",
        "سرور در دسترس است اما روی این پورت چیزی پاسخ نمی‌دهد.",
        "معمولاً یعنی شمارهٔ پورت اشتباه است یا سرویس روی سرور اجرا نیست. "
        "پورت را با عددی که در مرورگر بعد از دو‌نقطه می‌بینید مقایسه کنید.",
    ),
    (
        r"timed? ?out|timeout|etimedout|10060",
        "سرور در مهلت تعیین‌شده پاسخ نداد.",
        "بررسی کنید رایانهٔ سرور روشن و به شبکه متصل باشد. "
        "اگر شبکهٔ مرکز کند است، «مهلت پاسخ سرور» را در تنظیمات پیشرفته افزایش دهید.",
    ),
    (
        r"name or service not known|nodename nor servname|getaddrinfo|11001|dns",
        "آدرس سرور شناخته نشد.",
        "آدرس را دوباره بررسی کنید؛ باید فقط آدرس یا نام سرور باشد، بدون http:// و بدون پورت.",
    ),
    (
        r"no route to host|network is unreachable|errno 101|errno 113",
        "شبکه به این سرور راه ندارد.",
        "بررسی کنید این رایانه به شبکهٔ مرکز متصل باشد و سرور در همان شبکه باشد.",
    ),
    (
        r"unreachable|urlopen error|connectionerror|failed to establish",
        "ارتباط با سرور برقرار نشد.",
        "آدرس سرور و پورت را بررسی کنید و مطمئن شوید سرویس روی سرور در حال اجراست.",
    ),
    # -- ports ------------------------------------------------------------- #
    (
        r"address already in use|errno 98|errno 48|10048",
        "این پورت را برنامهٔ دیگری اشغال کرده است.",
        "شمارهٔ پورت را یک واحد افزایش دهید و دوباره ذخیره کنید.",
    ),
    (
        r"permission denied.*bind|errno 13.*bind|access.*permitted.*socket",
        "ویندوز اجازهٔ باز کردن این پورت را نداد.",
        "پورت‌های کمتر از ۱۰۲۴ نیاز به دسترسی مدیر دارند. عددی بزرگ‌تر از ۱۰۲۴ انتخاب کنید.",
    ),
    # -- TLS ---------------------------------------------------------------- #
    (
        r"certificate|ssl|tlsv1|hostname mismatch",
        "ارتباط امن با سرور برقرار نشد.",
        "اگر سرور پذیرش گواهی امنیتی ندارد، «نوع ارتباط» را روی http بگذارید.",
    ),
    # -- AI service --------------------------------------------------------- #
    (
        r"api[_\s-]?key|invalid[_\s-]?api|incorrect api key|authentication_error",
        "کلید API هوش مصنوعی پذیرفته نشد.",
        "کلید را دوباره از پنل سرویس‌دهنده کپی کنید. دقت کنید فاصله یا کاراکتر اضافه کپی نشود.",
    ),
    (
        r"rate.?limit|\b429\b|quota|insufficient_quota",
        "سرویس هوش مصنوعی فعلاً درخواست بیشتری نمی‌پذیرد.",
        "چند دقیقه صبر کنید و دوباره تلاش کنید. اگر تکرار شد، اعتبار حساب هوش مصنوعی را بررسی کنید.",
    ),
    (
        r"model.*not.*found|unknown model|model_not_found",
        "نام مدل هوش مصنوعی شناخته نشد.",
        "نام مدل را با آنچه سرویس‌دهنده اعلام کرده مقایسه کنید.",
    ),
    (
        r"proxy",
        "ارتباط از طریق پروکسی برقرار نشد.",
        "اگر پروکسی ندارید، کادر پروکسی را خالی بگذارید. در غیر این صورت آدرس پروکسی را بررسی کنید.",
    ),
    # -- server-side -------------------------------------------------------- #
    (
        r"\b5\d\d\b|internal server error|bad gateway|service unavailable",
        "سرور پذیرش با خطای داخلی پاسخ داد.",
        "مشکل از سمت سرور است، نه از تنظیمات شما. چند دقیقه بعد دوباره تلاش کنید "
        "و اگر ادامه داشت با پشتیبانی نرم‌افزار پذیرش تماس بگیرید.",
    ),
    (
        r"\b404\b|not found",
        "آدرس درخواستی روی سرور پیدا نشد.",
        "«مسیر پایهٔ سرویس» در تنظیمات پیشرفته را بررسی کنید؛ مقدار درست معمولاً /api است.",
    ),
    # -- data ---------------------------------------------------------------- #
    (
        r"json|expecting value|decode",
        "پاسخ سرور قابل خواندن نبود.",
        "معمولاً یعنی آدرس یا پورت به سرویس دیگری اشاره می‌کند. آن‌ها را بررسی کنید.",
    ),
    (
        r"dpapi|secret|رمزنگاری",
        "ذخیرهٔ امن رمز روی این رایانه ممکن نشد.",
        "برنامه را با همان حساب کاربری ویندوزی اجرا کنید که تنظیمات را ذخیره کرده است.",
    ),
    (
        r"no such file|filenotfound|errno 2",
        "پرونده یا پوشهٔ موردنیاز پیدا نشد.",
        "مسیر پوشهٔ داده را در تنظیمات پیشرفته بررسی کنید.",
    ),
]

_COMPILED = [(re.compile(pattern, re.IGNORECASE), headline, advice) for pattern, headline, advice in _RULES]


def explain(error: BaseException | str, context: str = "") -> Explained:
    """Translate a failure into plain Persian.

    ``context`` is a short phrase naming what was being attempted, e.g.
    "هنگام اتصال به نرم‌افزار پذیرش" — it is prefixed to the headline so the
    same network error reads differently in the reception tab and the AI tab.
    """
    raw = str(error).strip()
    if not raw:
        raw = error.__class__.__name__ if isinstance(error, BaseException) else "خطای ناشناخته"

    for pattern, headline, advice in _COMPILED:
        if pattern.search(raw):
            return Explained(
                headline=f"{context} {headline}".strip() if context else headline,
                advice=advice,
                details=raw,
            )

    # Unknown failure: never show the raw text as the headline — it is almost
    # always English and often a stack fragment.
    return Explained(
        headline=f"{context} کار انجام نشد.".strip() if context else "کار انجام نشد.",
        advice="جزئیات فنی را باز کنید و در صورت نیاز همان متن را برای پشتیبانی بفرستید.",
        details=raw,
    )
