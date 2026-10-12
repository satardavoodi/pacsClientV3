"""Agent modes: what the assistant is *for* during this conversation.

A mode is three things, and it is worth being precise about which:

1. **A prompt.** Each mode composes an extra section onto the base interpretation
   prompt, so "خلاصهٔ گزارش این بیمار" in Reporting mode and the same words in
   Analysis mode do not produce the same tool call.
2. **A tool policy.** Reporting mode does not need the money tools and Analysis
   mode does not need to open one patient's report text. Narrowing the list the
   model sees is not decoration -- a smaller, relevant menu is chosen from more
   accurately, and a tool that is not offered cannot be picked by mistake.
3. **A capability ceiling.** `read_only` says whether a mode may touch anything
   that changes state, and `can_act` whether it may carry a write through. Both
   are enforced in the orchestrator on top of -- never instead of -- the
   permission model and the human confirmation gate.

The product ships exactly three modes, and the difference between them is what
they are allowed to DO, not merely what they are asked to do:

| mode | reads | reasons over what it read | changes anything |
|---|---|---|---|
| `report` | yes | no — retrieve, organise, present | **never** |
| `analysis` | yes | yes — compare, correlate, explain | **never** |
| `executive` | yes | yes | yes, once every other gate agrees |

Report and Analysis are read-only **by enforcement**, not by instruction. A
prompt that says "never modify data" is a request to a language model; a
`read_only` mode that refuses any non-read tool is a property of the system. The
prompts say it too, because a model that never sees a write tool also should not
spend its answer apologising for not having one -- but the prompt is the manner,
never the mechanism.

**Adding a mode is adding an entry here plus a prompt file.** Nothing else: not
the phone, not the wire format, not the chat store. The mobile app asks
`GET /api/modes` and renders whatever comes back, so a clinic that upgrades its
server gets the new mode without a new APK. That constraint is the reason this
registry is data rather than `if mode == "report"` scattered around.

The tool lists below name real registered tools. They are checked against the
registry by a test, because a mode that quietly narrows to nothing -- after a
tool is renamed, say -- would look like a working assistant that has simply
stopped being able to do anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODE = "report"

# Useful in any conversation, whatever the mode is about.
#
# `reception.vocabulary` is here rather than in one mode because it is the
# answer to "0 results" in every mode: a filtered count of zero beside a
# non-zero unfiltered one usually means the filter VALUE does not exist, not
# that the patients do not. Whichever mode is running needs to be able to check
# that before writing a sentence a clinician will act on.
_COMMON = ("patients.search", "patient-list", "appointments.list", "reception.vocabulary")


@dataclass(frozen=True)
class AgentMode:
    id: str
    label_fa: str
    description_fa: str
    prompt_file: str
    #: How this mode WRITES ITS ANSWER, appended to the analysis prompt on the
    #: summarising call. Separate from `prompt_file` because the two calls are
    #: separate and want different things: `prompt_file` shapes tool CHOICE and
    #: is full of guidance the answer-writer does not need, while this shapes
    #: the finished text the clinician reads.
    #:
    #: Until this existed the mode reached only the first call, so every mode's
    #: answer was written by one mode-blind prompt asking for "1-3 short
    #: sentences" -- which is right for Report and wrong for Analysis.
    answer_file: str = ""
    #: Exact tool names this mode offers. Empty = every tool the principal may
    #: use, which is the honest setting for a mode that must read widely.
    tools: tuple[str, ...] = ()
    #: Name prefixes offered in addition to `tools` -- so a new `report.*` tool
    #: joins Reporting mode automatically.
    prefixes: tuple[str, ...] = ()
    #: Hard ceiling: this mode may touch NOTHING that changes state. Enforced in
    #: two places on purpose -- `tools_for` never shows such a tool, and the
    #: orchestrator refuses one even if the model names it anyway.
    #:
    #: The tool menu alone used to be the whole mechanism, on the argument that
    #: an absent tool is more visible than a flag. That is true and it is still
    #: how the menus are written -- but it is not sufficient, because
    #: `tools_for` returns the FULL list when narrowing would leave nothing. At
    #: a site whose report tools are missing, Reporting mode degraded to "every
    #: tool the principal may call", writes included. The menu is the manner;
    #: this flag is the guarantee.
    read_only: bool = False
    #: May this mode carry a write through to the CRM, for permissions and the
    #: human confirmation gate to then rule on? Distinct from `read_only`: a
    #: mode can be permitted to handle write tools yet held at propose-only.
    can_act: bool = True
    #: Shown in the phone's mode sheet under the label.
    examples_fa: tuple[str, ...] = ()
    #: Free-form hints for clients; unknown keys are ignored by design, so a
    #: newer server can suggest an icon an older phone will simply not use.
    ui: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "labelFa": self.label_fa,
            "descriptionFa": self.description_fa,
            "readOnly": self.read_only,
            "canAct": self.can_act,
            "examplesFa": list(self.examples_fa),
            "ui": dict(self.ui),
        }


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
REPORT = AgentMode(
    id="report",
    label_fa="گزارش",
    description_fa="بازیابی و نمایش اطلاعات ثبت‌شده — بدون تحلیل یا قضاوت",
    prompt_file="mode_report.md",
    answer_file="answer_report.md",
    prefixes=("report.", "report-"),
    # "Report" is NOT only a radiology report. It is retrieval of anything the
    # reception system already holds -- today's admissions, the cashier's day, a
    # patient's registered studies -- so the menu spans the reading tools of the
    # whole system, not just the report archive.
    #
    # `cashier-reconciliation` used to be here, justified by being "the only
    # tool that reads the cashier's day". That justification has expired:
    # `cashier-report` now reads the cashier's day directly, from the reception
    # software's own report. Reconciliation computes variances and possible
    # CAUSES -- it is an interpretation, and leaving it on this menu meant
    # Report mode emitted judgement by construction, whatever the prompt said.
    # It lives in Analysis now, where that work belongs.
    #
    # `physician-performance` is here because the endpoint returns each
    # physician's totals ready-made and the ranking is done in Python. Asking
    # who was busiest is then retrieval and a sort, not a judgement. Analysis
    # gets it too, to compare and explain.
    #
    # The `integrity.*` checks are deliberately NOT here. They look for missing
    # records and post-approval edits, which is consistency checking: Analysis
    # work by the definition this mode now holds to. Report retrieves what
    # exists; it does not go looking for what is wrong.
    tools=_COMMON + (
        "reporting-queue",
        "daily-summary",
        "cashier-report",
        # Money by MEANING. On both money-answering menus, because choosing a
        # FIELD is where every financial error in this system has happened and
        # choosing a METRIC is checkable. `finance.vocabulary` is what lets the
        # model look a concept up instead of guessing at one.
        "finance.metric",
        "finance.vocabulary",
        "physician-performance",
        # "How many X did we do" is retrieval, and this is the only tool that
        # can filter by what was PERFORMED rather than by which machine ran it.
        # Report mode is where those questions land.
        "reception.search",
        # The patient chat. On BOTH menus on purpose: «گزارش گفتگوهای امروز» is
        # retrieval and «سامانه گفتگو را بررسی کن» is analysis, and when this
        # tool existed on neither, the model answered a conversation question
        # with the reception day summary rather than saying it could not see it.
        "conversation.summary",
        # The booking diary. «چه نوبت‌هایی برای فردا ثبت شده؟» and «اولین ساعت
        # خالی کی است؟» are retrieval: one reads the day's booked slots, the
        # other reads the room's declared windows and subtracts what is taken.
        # Neither judges anything, so both belong here as well as in Analysis.
        #
        # `appointments.list` (already in `_COMMON`) is the waiting QUEUE --
        # who is in the building now. These two are the CALENDAR. A tool menu
        # that offered only the queue is why appointment questions were being
        # answered from the reception day summary.
        "appointments.day",
        "appointments.availability",
        # Who referred the patients, and what each staff account did. Both
        # return counted facts straight out of the records: the referring
        # physician on each reception, and the three kinds of logged activity
        # per account. Ranking them is a sort, as with `physician-performance`.
        #
        # `staff.activity` counts ACTIONS, not attendance, and says so in its
        # own payload -- which is the reason it can sit on a retrieval menu at
        # all: it reports what was logged and leaves the inference alone.
        "marketing.referrers",
        "staff.activity",
    ),
    read_only=True,
    can_act=False,
    examples_fa=(
        "گزارش صندوق امروز را بده",
        "پذیرش‌های امروز را نشان بده",
        "گزارش گفتگوهای امروز را بده",
        "برای این بیمار چه گزارش‌هایی ثبت شده است؟",
        "گزارش سی‌تی این بیمار را نشان بده",
    ),
    ui={"icon": "description", "badgeFa": "فقط خواندن"},
)

ANALYSIS = AgentMode(
    id="analysis",
    label_fa="تحلیل",
    description_fa="استدلال روی داده‌ها — مقایسه، الگو، ناسازگاری و ناهنجاری",
    prompt_file="mode_analysis.md",
    answer_file="answer_analysis.md",
    prefixes=("integrity.",),
    # Analysis reasons ACROSS records, so it needs both the aggregate tools and
    # -- unlike before -- the ability to open the individual reports it is being
    # asked to compare. "این بیمار را با سی‌تی و ام‌آرآی مقایسه کن" is an
    # Analysis question that cannot be answered from counts.
    tools=_COMMON + (
        "daily-summary",
        "financial-analysis",
        "cashier-report",
        # The aggregate cashier report can say how many transactions were
        # deleted, but not who originally registered them or who deleted them.
        # Questions about those actors need the detail audit source below.
        "cashier-deleted-transactions",
        "cashier-reconciliation",
        "finance.metric",
        "finance.vocabulary",
        "physician-performance",
        "trend-analysis",
        "risk-analysis",
        "reporting-queue",
        "report.archive-stats",
        "report.get",
        "report.history",
        "report.search",
        # Analysis needs it too, and for the harder reason: cross-checking a
        # count against the record it came from. "0 mammography BI-RADS 3"
        # should have been checked against "how many mammography receptions
        # were there at all" — one call, and the answer would have been right.
        "reception.search",
        # «سامانه گفتگو امروز مرکز را بررسی کن» is an Analysis question and it
        # was answered from `daily-summary`, because this did not exist.
        "conversation.summary",
        # The calendar, the referral source and the staff activity log -- the
        # same four Report gets, because Analysis is asked the harder version
        # of each: not "what is booked" but "are we filling the slots we
        # declare", not "who referred" but "which referrer is growing".
        "appointments.day",
        "appointments.availability",
        "marketing.referrers",
        "staff.activity",
        # These two are Analysis-ONLY, on the rule this file already holds to
        # for `integrity.*`: Report retrieves what exists, it does not go
        # looking for what is wrong.
        #
        # `appointments.vs-receptions` compares the booking diary against who
        # actually arrived -- a reconciliation, and the no-show rate it implies
        # is a finding, not a record.
        #
        # `audit.name-changes` reads the edit log: who changed a patient's name
        # after the fact, and whether the change was blocked or overridden.
        # That is consistency checking over past edits, which is exactly why
        # `cashier-reconciliation` was moved off the Report menu.
        "appointments.vs-receptions",
        "audit.name-changes",
    ),
    read_only=True,
    can_act=False,
    examples_fa=(
        "فعالیت صندوق امروز را تحلیل کن",
        "سامانه گفتگو امروز مرکز را بررسی کن",
        "آیا امروز ناسازگاری مالی وجود دارد؟",
        "گزارش‌های قبلی این بیمار را تحلیل کن",
        "سی‌تی و ام‌آرآی این بیمار را با هم مقایسه کن",
        "پذیرش‌های امروز را بررسی و الگوهای غیرعادی را پیدا کن",
    ),
    ui={"icon": "insights", "badgeFa": "فقط خواندن"},
)

EXECUTIVE = AgentMode(
    id="executive",
    label_fa="دستور اجرایی",
    description_fa="اجرای عملیات پشتیبانی‌شده در سامانهٔ پذیرش — تنها حالتی که می‌تواند چیزی را تغییر دهد",
    prompt_file="mode_executive.md",
    answer_file="answer_executive.md",
    # No narrowing: to carry out an operation sensibly it must first be able to
    # read widely -- find the set, check the state, then act on it. Which is
    # exactly why this is the mode that is NOT read_only: its menu includes
    # everything the principal may call, writes included.
    read_only=False,
    # The mode is permitted to act. That is not the same as anything being able
    # to happen: every write still passes the role policy, the per-operation
    # switch in operations.json (where `appointments.schedule` ships disabled),
    # RECEPTION_ENABLE_WRITES, and the human confirmation gate. This flag opens
    # the mode; those four decide the operation.
    can_act=True,
    examples_fa=(
        "این فهرست بیماران را ذخیره کن",
        "برای بیماران این گروه پیامک یادآوری بفرست",
        "وضعیت این پذیرش را به‌روزرسانی کن",
        "برای این بیمار یک نوبت پیگیری ثبت کن",
    ),
    ui={"icon": "task_alt", "badgeFa": "تغییر‌دهنده"},
)

_MODES: dict[str, AgentMode] = {m.id: m for m in (REPORT, ANALYSIS, EXECUTIVE)}

#: Ids that used to name a mode, mapped to the mode that replaced them.
#:
#: "order"/"اقدام" was renamed to "executive" for the three-mode separation.
#: Without this table the rename would be silently destructive: `get()` falls
#: back to the DEFAULT mode for anything unknown, so every conversation already
#: stored as `order` -- on the server AND in each phone's local mirror -- would
#: have quietly reopened in Reporting mode. The user would see their action
#: chat still there, still answering, and simply not doing what it used to.
#:
#: Aliases resolve; they are not offered. `all_modes()` and `/api/modes` list
#: three, so no client learns a name that is on its way out.
_ALIASES: dict[str, str] = {
    "order": "executive",
    "action": "executive",  # the English word this mode was called in the spec
}


def all_modes() -> list[AgentMode]:
    return list(_MODES.values())


def canonical(mode_id: Any) -> str:
    """The current id for a possibly-retired one. Unknown ids pass through.

    Returned rather than raising so callers can canonicalise on the way past
    without deciding whether the value is valid -- `get()` and `_mode()` still
    do that, each in the direction that suits them.
    """
    raw = str(mode_id or "").strip().lower()
    return _ALIASES.get(raw, raw)


def get(mode_id: Any) -> AgentMode:
    """Resolve a mode id, falling back to the default.

    Deliberately forgiving: an unknown mode from an older or newer client is a
    reason to answer in the default mode, not to refuse the clinician's question.
    The default is read-only, so falling back can never grant anything.
    """
    return _MODES.get(canonical(mode_id), _MODES[DEFAULT_MODE])


def is_known(mode_id: Any) -> bool:
    """True for a current id or a retired one that still resolves."""
    return canonical(mode_id) in _MODES


def tools_for(mode: AgentMode, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Narrow an already permission-filtered tool list to this mode.

    Order matters and is not negotiable: the principal's permissions are applied
    first, by the registry, and this only ever removes more. A mode can never
    show a tool the user may not call.

    If narrowing would leave nothing, the full list is returned. A mode whose
    tools are all absent -- a deployment without the local database, say --
    should degrade to a general assistant rather than to a useless one.

    A read-only mode degrades to a read-only assistant, never to a general one.
    That distinction is the whole reason `read_only` exists as a field: this
    function used to hand back the FULL list on the empty-narrowing path, so at
    a site whose `report.*` tools were missing, Reporting mode was offered every
    write the principal could call. Nothing in the menus said so, and the test
    that checked for leaks passed, because on a complete registry that path is
    never taken. The filter below runs LAST, after the fallback, for exactly
    that reason.
    """
    if mode.tools or mode.prefixes:

        def admitted(tool: dict[str, Any]) -> bool:
            name = str(tool.get("name", ""))
            if name in mode.tools:
                return True  # named deliberately, whatever it does
            if not mode.prefixes or not name.startswith(mode.prefixes):
                return False
            # A prefix is a convenience, and a convenience must not quietly hand
            # a mode the power to change things: `report-` was meant to pick up
            # new report READERS, and it would just as happily pick up a future
            # `report-delete`. A tool that needs a human tap has to be named.
            return not tool.get("requires_confirmation")

        narrowed = [t for t in tools if admitted(t)]
        tools = narrowed or tools

    if mode.read_only:
        tools = [t for t in tools if is_read_only_tool(t)]

    return tools


def is_read_only_tool(tool: dict[str, Any]) -> bool:
    """Does this tool leave the reception system exactly as it found it?

    Read from the DESCRIBED tool, which is what both the model and this filter
    see. Two fields, because either alone lets something through:

    * `safety` is the tool's own claim about what it does. Anything other than
      ``read`` changes something or is a step towards changing it.
    * `requires_confirmation` is the registry's verdict, which also covers a
      tool that opted in explicitly.

    A tool that names neither is treated as read-only, because every read tool
    in the registry omits both -- but a tool that is missing its `safety` label
    AND changes state is a registry bug this cannot see. `test_modes.py` checks
    the registry against this function so such a tool fails the build rather
    than the clinic.
    """
    if tool.get("requires_confirmation"):
        return False
    return str(tool.get("safety", "read")) == "read"
