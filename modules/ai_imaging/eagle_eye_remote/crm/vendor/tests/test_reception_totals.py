"""A truncated row list must never limit what can be counted.

The failure these guard: `reception.search` returned a full `count` and 25 rows,
and the agent — having no patient evidence in the payload beyond those rows —
answered «تعداد بیماران یکتا از این نتیجه مشخص نیست» and «فهرست به ۲۵ ردیف محدود
شده است». The count was right and the information was simply absent. Absent
information reads to a user as a limit.
"""

from __future__ import annotations

from typing import Any

import pytest

from reception_crm.local import receptions as R


class FakeCollection:
    """Enough of a Mongo collection to exercise the aggregation shapes.

    Deliberately not a mock that returns a canned answer: it interprets the
    pipeline, so a test failure means the PIPELINE is wrong, not that a stub
    drifted from it.
    """

    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs
        self.pipelines: list[list[dict]] = []
        self.find_limit: int | None = None

    # -- find -----------------------------------------------------------
    def find(self, query, fields=None):
        self._rows = [dict(d) for d in self.docs]
        return self

    def sort(self, _spec):
        return self

    def limit(self, n):
        self.find_limit = n
        return self._rows[:n]

    def count_documents(self, query, **kw):
        return len(self.docs)

    # -- aggregate ------------------------------------------------------
    def aggregate(self, pipeline, **kw):
        self.pipelines.append(pipeline)
        stages = [s for s in pipeline]
        rows = [dict(d) for d in self.docs]

        # $unwind services
        if any("$unwind" in s for s in stages):
            out = []
            for r in rows:
                for svc in r.get("services") or []:
                    copy = dict(r)
                    copy["services"] = svc
                    out.append(copy)
            rows = out

        groups = [s["$group"] for s in stages if "$group" in s]
        if not groups:
            return []

        # first $group
        first = groups[0]
        buckets: dict[Any, dict[str, Any]] = {}
        for r in rows:
            gid = first["_id"]
            if isinstance(gid, dict) and set(gid) == {"k", "p"}:
                key = (self._resolve(gid["k"], r), r.get("patient"))
            else:
                key = self._resolve(gid, r)
            b = buckets.setdefault(key, {"_id": key, "n": 0, "receptions": 0,
                                         "serviceLines": 0, "lines": 0,
                                         "discountAmount": 0})
            b["n"] += 1
            b["receptions"] += 1
            # Evaluated from the pipeline's own $add/$ifNull expression rather
            # than hardcoded, so this stays a test of the pipeline: if the
            # expression stops naming the right fields, the number moves.
            b["discountAmount"] += self._sum_expr(first.get("discountAmount"), r)
            svc = r.get("services")
            n_lines = 1 if isinstance(svc, dict) else len(svc or [])
            b["serviceLines"] += n_lines
            b["lines"] += n_lines

        first_rows = list(buckets.values())
        if len(groups) == 1:
            return first_rows

        second = groups[1]
        if second["_id"] is None:
            return [{
                "patients": len(first_rows),
                "receptions": sum(b["receptions"] for b in first_rows),
                "serviceLines": sum(b["serviceLines"] for b in first_rows),
                "discountAmount": sum(b["discountAmount"] for b in first_rows),
            }]

        # regroup by the dimension half of the composite key
        out: dict[Any, dict[str, Any]] = {}
        for b in first_rows:
            k = b["_id"][0] if isinstance(b["_id"], tuple) else b["_id"]
            o = out.setdefault(k, {"_id": k, "patients": 0, "n": 0, "serviceLines": 0})
            o["patients"] += 1
            o["n"] += b["n"]
            o["serviceLines"] += b["lines"]
        return sorted(out.values(), key=lambda x: -x["n"])

    @classmethod
    def _sum_expr(cls, expr, row) -> int:
        """Evaluate `{"$sum": {"$add": [{"$ifNull": ["$f", 0]}, …]}}`."""
        if expr is None:
            return 0
        inner = expr.get("$sum") if isinstance(expr, dict) else expr
        terms = inner.get("$add", []) if isinstance(inner, dict) else []
        total = 0
        for term in terms:
            field, default = term["$ifNull"]
            total += row.get(field[1:]) or default
        return total

    @staticmethod
    def _resolve(expr, row):
        if isinstance(expr, str) and expr.startswith("$"):
            node: Any = row
            for part in expr[1:].split("."):
                node = node.get(part) if isinstance(node, dict) else None
            return node
        if isinstance(expr, dict) and "$cond" in expr:
            return row.get("modality")
        return expr


#: Three people, four visits, six procedures. Every grain has a different
#: number, which is the entire point.
DOCS = [
    {"ReceptionID": 1, "patient": "p1", "Date": "1405/06/01", "modality": "2",
     "services": [{"Service": "MRI Brain"}, {"Service": "MRI Spine"}]},
    {"ReceptionID": 2, "patient": "p1", "Date": "1405/06/01", "modality": "2",
     "services": [{"Service": "MRI Knee"}]},
    # Two receptions carry a discount, in DIFFERENT fields, and one of them also
    # has `discountTotal: 0` sitting beside the field that holds the money —
    # which is the real shape in this database and the reason the sum is over
    # all four fields rather than over the one with the obvious name.
    {"ReceptionID": 3, "patient": "p2", "Date": "1405/06/01", "modality": "2",
     "cashDeskDiscount": 2_050_000, "discountTotal": 0,
     "services": [{"Service": "MRI Brain"}]},
    {"ReceptionID": 4, "patient": "p3", "Date": "1405/06/01", "modality": "3",
     "customerClubDiscount": 1_610_000,
     "services": [{"Service": "US Abdomen"}, {"Service": "US Pelvis"}]},
]


@pytest.fixture
def col():
    return FakeCollection(DOCS)


def test_totals_report_three_different_grains(col):
    t = R._totals(col, {})
    assert t == {"patients": 3, "receptions": 4, "serviceLines": 6,
                 "discountAmount": 3_660_000}


def test_totals_are_independent_of_the_row_limit(col):
    """The number of rows rendered must not touch any count."""
    a = R._totals(col, {})
    col.find_limit = 1
    b = R._totals(col, {})
    assert a == b


def test_empty_match_returns_zeros_not_none(col):
    empty = FakeCollection([])
    assert R._totals(empty, {}) == {"patients": 0, "receptions": 0,
                                    "serviceLines": 0, "discountAmount": 0}


def test_discount_money_is_a_total_not_a_row_sum():
    """«چند تخفیف» and «چه مبلغی تخفیف» are two questions; both get answered.

    The regression this guards: `discountedOnly` shipped able to find exactly
    the right receptions and unable to say how much money they carried, so the
    answer went from «۳ مورد به مبلغ ۱۳٬۵۸۰٬۰۰۰» to «۳ پذیرش دارای تخفیف بودند».
    The amount must live in `totals`, where it is computed over the whole match
    — not on `rows`, which are a display sample and may be truncated.
    """
    col = FakeCollection(DOCS)
    totals = R._totals(col, {})
    assert totals["discountAmount"] == 2_050_000 + 1_610_000

    # Summed across all four fields, not just the obviously-named one. In this
    # database `discountTotal` is 0 on every reception and `cashDeskDiscount`
    # is where the money actually is.
    assert "cashDeskDiscount" in R.ROW_FIELDS
    assert "customerClubDiscount" in R.ROW_FIELDS
    fields = {t["$ifNull"][0][1:] for t in R._DISCOUNT_SUM["$add"]}
    assert fields == set(R.dm.DISCOUNT_FIELDS)


def test_breakdown_carries_patients_per_bucket(col):
    out = R._breakdown(col, {}, "modality", None)
    by_value = {i["value"]: i for i in out["items"]}
    assert by_value["2"]["patients"] == 2      # p1 and p2
    assert by_value["2"]["n"] == 3            # three visits
    assert by_value["2"]["serviceLines"] == 4
    assert by_value["3"]["patients"] == 1


def test_breakdown_declares_what_n_means(col):
    assert R._breakdown(col, {}, "modality", None)["nMeans"] == "receptions"
    assert R._breakdown(col, {}, "service", None)["nMeans"] == "service lines"


def test_cashier_breakdown_resolves_user_ids_before_the_model_sees_them(monkeypatch):
    from reception_crm.local import people

    docs = [
        {"patient": "p1", "registeredBy": "u1", "services": []},
        {"patient": "p2", "registeredBy": "u1", "services": []},
        {"patient": "p3", "registeredBy": "u2", "services": []},
    ]
    monkeypatch.setattr(
        people,
        "_staff_names",
        lambda ids: {"u1": "کاربر اول", "u2": "کاربر دوم"},
    )
    out = R._breakdown(FakeCollection(docs), {}, "cashier", None)

    assert out["items"][0]["value"] == "u1"
    assert out["items"][0]["label"] == "کاربر اول"
    assert out["items"][0]["n"] == 2


def test_display_budget_is_generous_and_not_25():
    """25 was small enough that the model reported it as a limitation."""
    assert R.DEFAULT_LIMIT >= 100
    assert R.MAX_LIMIT >= 1000


def test_row_fields_carry_a_patient_reference():
    """Without it the model cannot tell two rows apart, or dedup them."""
    assert R.ROW_FIELDS.get("patient") == 1
    assert "patientNameSnapshot" not in R.ROW_FIELDS
    assert "nationalCode" not in R.ROW_FIELDS
