"""The help copy and the error translator are data, so they can be tested.

Neither module imports Qt, which is what makes this suite runnable in CI on a
machine with no display. What it guards is the promise the UI makes to the
user: every configurable field has an explanation, and no raw English error
text ever becomes a headline.
"""

from __future__ import annotations

import dataclasses

import pytest

from reception_crm.connections import (
    EXTERNAL_MCP,
    MOBILE_LLM,
    RECEPTION,
    ExternalMcpConnection,
    MobileInternalLlmConnection,
    ReceptionApiConnection,
)
from reception_crm.desktop import help as help_content
from reception_crm.desktop.friendly_errors import explain

# Fields the user never sets from the settings screen: derived, fixed by the
# installer, or covered by another control.
NOT_USER_FACING = {
    RECEPTION: {"enabled", "dashboard_port", "socket_port"},
    EXTERNAL_MCP: {"enabled"},
    MOBILE_LLM: {"session_secret"},
}

SECTIONS = [
    (RECEPTION, ReceptionApiConnection),
    (EXTERNAL_MCP, ExternalMcpConnection),
    (MOBILE_LLM, MobileInternalLlmConnection),
]


# --------------------------------------------------------------------------- #
# coverage
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("namespace,model", SECTIONS)
def test_every_settable_field_has_help(namespace, model):
    """A field with no explanation is a field the user has to guess at."""
    documented = set(help_content.FIELD_HELP[namespace])
    settable = {f.name for f in dataclasses.fields(model)} - NOT_USER_FACING[namespace]
    missing = settable - documented
    assert not missing, f"{namespace}: fields without help: {sorted(missing)}"


@pytest.mark.parametrize("namespace,model", SECTIONS)
def test_help_does_not_describe_fields_that_no_longer_exist(namespace, model):
    """Catches help left behind when a field is renamed or removed."""
    real = {f.name for f in dataclasses.fields(model)}
    stale = set(help_content.FIELD_HELP[namespace]) - real
    assert not stale, f"{namespace}: help for unknown fields: {sorted(stale)}"


def test_every_field_answers_what_and_what_to_enter():
    for namespace, fields in help_content.FIELD_HELP.items():
        for key, topic in fields.items():
            assert topic.title, f"{namespace}.{key} has no title"
            assert topic.what, f"{namespace}.{key} does not say what it is"
            assert topic.value, f"{namespace}.{key} does not say what to enter"
            assert topic.required is not None, f"{namespace}.{key} is neither required nor optional"


def test_sections_and_pages_are_described():
    for namespace, _model in SECTIONS:
        topic = help_content.SECTION_HELP[namespace]
        assert topic.what and topic.why
    for key, topic in help_content.PAGE_HELP.items():
        assert topic.title and topic.what, f"page {key} is not described"


def test_help_is_persian_not_leftover_english():
    """A stray English sentence is the sign of an unfinished translation."""
    persian = set("ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")
    for namespace, fields in help_content.FIELD_HELP.items():
        for key, topic in fields.items():
            for text in (topic.title, topic.what, topic.value):
                assert persian & set(text), f"{namespace}.{key}: not Persian -> {text!r}"


# --------------------------------------------------------------------------- #
# error translation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected_fragment",
    [
        ("ConnectionError: [Errno 111] Connection refused", "پورت"),
        ("HTTPError: 401 Unauthorized", "رمز عبور"),
        ("socket.timeout: timed out", "مهلت"),
        ("OSError: [Errno 98] Address already in use", "اشغال"),
        ("gaierror: [Errno -2] Name or service not known", "آدرس"),
        ("openai.AuthenticationError: incorrect api key provided", "کلید"),
        ("HTTP 500 Internal Server Error", "سرور"),
    ],
)
def test_known_failures_get_a_specific_explanation(raw, expected_fragment):
    result = explain(raw)
    assert expected_fragment in result.headline + result.advice
    assert result.details == raw, "the original text must survive for support"


def test_unknown_failure_never_becomes_the_headline():
    """The whole point: an English stack fragment must not reach the user."""
    raw = "SomeInternalThing<0x7f> exploded unexpectedly"
    result = explain(raw)
    assert raw not in result.headline
    assert result.advice
    assert result.details == raw


def test_context_is_prefixed_to_the_headline():
    result = explain("Connection refused", "هنگام اتصال به نرم‌افزار پذیرش،")
    assert result.headline.startswith("هنگام اتصال به نرم‌افزار پذیرش،")


def test_empty_error_still_produces_something_readable():
    result = explain("")
    assert result.headline
    assert result.details


def test_exception_objects_are_accepted():
    result = explain(ConnectionRefusedError("Connection refused"))
    assert "پورت" in result.advice


# --------------------------------------------------------------------------- #
# consistency
# --------------------------------------------------------------------------- #
def test_one_concept_one_label():
    """The same idea must not be called two different things.

    A user who learns «آدرس سرور» on one screen should not meet «هاست» on
    another. These are the words that used to drift.
    """
    banned = ["هاست", "Endpoint", "اندپوینت", "پسورد", "یوزرنیم"]
    for namespace, fields in help_content.FIELD_HELP.items():
        for key, topic in fields.items():
            haystack = " ".join([topic.title, topic.what, topic.why, topic.value, topic.where])
            for word in banned:
                assert word not in haystack, f"{namespace}.{key} uses «{word}»"


def test_architecture_and_troubleshooting_are_populated():
    assert len(help_content.ARCHITECTURE_STEPS) >= 3
    assert len(help_content.TROUBLESHOOTING) >= 5
    for question, answer in help_content.TROUBLESHOOTING:
        assert question and answer
