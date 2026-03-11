from __future__ import annotations

import re


def _norm(text: str) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def is_yes(text: str) -> bool:
    s = _norm(text)
    yes_words = {
        "yes",
        "y",
        "ok",
        "okay",
        "confirm",
        "go ahead",
        "بله",
        "آره",
        "اره",
        "تایید",
        "تایید کن",
        "انجام بده",
    }
    return s in yes_words or any(s.startswith(w + " ") for w in yes_words)


def is_no(text: str) -> bool:
    s = _norm(text)
    no_words = {
        "no",
        "n",
        "cancel",
        "stop",
        "nevermind",
        "خیر",
        "نه",
        "لغو",
        "بیخیال",
    }
    return s in no_words or any(s.startswith(w + " ") for w in no_words)


def parse_selection_index(text: str, max_count: int) -> int | None:
    if max_count <= 0:
        return None
    s = _norm(text)
    m = re.search(r"\b(\d{1,2})\b", s)
    if not m:
        return None
    n = int(m.group(1))
    if 1 <= n <= max_count:
        return n - 1
    return None

