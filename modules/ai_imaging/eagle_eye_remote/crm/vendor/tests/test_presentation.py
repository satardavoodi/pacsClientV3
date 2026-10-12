"""What the clinician reads, and what they must never be handed.

The load-bearing claim of this module is that structure is a GUARANTEE, not a
request to a language model. So most of these tests feed it the things a model
actually does on a bad day — pastes its payload back, wraps the answer in a
code fence, invents a fourth heading level, mixes four bullet glyphs — and
check that a person can still read the result.
"""

from __future__ import annotations

from reception_crm.core import presentation as pres


# --------------------------------------------------------------------------- #
# never hand the user JSON
# --------------------------------------------------------------------------- #
def test_a_pasted_json_payload_is_removed_from_the_answer():
    """Models paste the data back "for reference". It is already in `result`."""
    answer = pres.normalise(
        '## گزارش امروز\n'
        '\n'
        '- **مجموع:** ۱۲۸\n'
        '\n'
        '{\n'
        '  "admissions": 128,\n'
        '  "modalities": {"MRI": 42}\n'
        '}\n'
    )
    assert "admissions" not in answer
    assert "۱۲۸" in answer
    assert answer.startswith("## گزارش امروز")


def test_a_one_line_json_object_is_removed_too():
    answer = pres.normalise('یافت شد.\n{"count": 3, "rows": []}\nپایان.')
    assert "count" not in answer
    assert "یافت شد." in answer and "پایان." in answer


def test_a_sentence_that_merely_mentions_a_brace_survives():
    """The detector is structural. Over-eager deletion would silently drop a
    real sentence, which is worse than the JSON it was hunting."""
    answer = pres.normalise("مقدار { در متن گزارش دیده شد و مهم است.")
    assert "مهم است" in answer


def test_an_answer_that_is_ONLY_json_is_replaced_by_a_rendering():
    """The worst case: the model returned its payload and nothing else. The
    user must not receive it, and must not receive nothing either."""
    display, fallback = pres.build_display(
        '{"admissions": 128}', {"admissions": 128}, fallback_heading="خلاصهٔ روز"
    )
    assert fallback is True
    assert display.startswith("## خلاصهٔ روز")
    assert "128" in display or "۱۲۸" in display


def test_looks_like_json_recognises_both_shapes():
    assert pres.looks_like_json('{"a": 1}')
    assert pres.looks_like_json('  "patient": "x"  ')
    assert not pres.looks_like_json("## عنوان\n- مورد")


# --------------------------------------------------------------------------- #
# normalising what the model wrote
# --------------------------------------------------------------------------- #
def test_every_bullet_glyph_becomes_one_glyph():
    """A model mixes •, *, – and + inside a single answer. The phone's parser
    should have exactly one thing to match."""
    answer = pres.normalise("• یک\n* دو\n– سه\n+ چهار")
    assert answer.split("\n") == ["- یک", "- دو", "- سه", "- چهار"]


def test_deep_headings_collapse_to_a_level_the_phone_renders():
    """`####` arriving as literal hashes looks like a broken app."""
    answer = pres.normalise("#### خیلی عمیق\n# خیلی بزرگ")
    assert answer.split("\n") == ["### خیلی عمیق", "## خیلی بزرگ"]


def test_a_code_fence_is_removed_but_its_contents_are_kept():
    """Deleting the block would turn a formatting slip into a missing answer."""
    answer = pres.normalise("```\n- مجموع: ۱۲۸\n```")
    assert answer == "- مجموع: ۱۲۸"


def test_runs_of_blank_lines_collapse():
    assert pres.normalise("یک\n\n\n\n\nدو") == "یک\n\nدو"


def test_a_rule_of_any_glyph_becomes_the_one_separator():
    assert pres.normalise("یک\n=====\nدو") == "یک\n---\nدو"


def test_an_overlong_answer_is_cut_and_says_so():
    answer = pres.normalise("الف " * 5000)
    assert len(answer) <= pres.MAX_DISPLAY_CHARS + 8
    assert answer.rstrip().endswith("…")


# --------------------------------------------------------------------------- #
# rendering data when there is no prose at all
# --------------------------------------------------------------------------- #
def test_a_flat_result_becomes_labelled_bullets():
    out = pres.render_result({"count": 12, "date": "1405/06/01"}, heading="خلاصهٔ روز")
    assert "## خلاصهٔ روز" in out
    assert "- **تعداد:** 12" in out
    assert "- **تاریخ:** 1405/06/01" in out


def test_a_nested_object_becomes_a_subsection_not_an_indented_blob():
    """Indentation past one level is unreadable in a chat bubble, and in RTL it
    is worse than unreadable — it is misleading about what belongs to what."""
    out = pres.render_result({"modalities": {"MRI": 42, "CT": 31}})
    assert "### " in out
    assert "**MRI:** 42" in out


def test_a_row_list_becomes_a_numbered_list_one_row_per_line():
    rows = [{"name": "الف", "modality": "CT"}, {"name": "ب", "modality": "MRI"}]
    out = pres.render_result({"rows": rows})
    assert "1. " in out and "2. " in out
    assert " · " in out, "fields on one line, not a bullet each"


def test_a_long_list_says_what_it_left_out():
    """A list silently cut at 25 reads as a complete list of 25 — the exact
    failure this module exists to prevent."""
    rows = [{"n": i} for i in range(60)]
    out = pres.render_result({"rows": rows})
    assert "۳۵" in out or "35" in out
    assert "نمایش داده نشد" in out


def test_an_acronym_key_is_not_split_into_letters():
    """`MRI` came out as "M R I" in the middle of a clinical answer, because
    the splitter broke before every capital. Modality codes are exactly the
    keys this data is full of."""
    assert pres._label("MRI") == "MRI"
    assert pres._label("CT") == "CT"
    assert pres._label("dateFrom") == "از تاریخ"       # mapped wins
    assert pres._label("patientAge") == "patient Age"  # unmapped still splits
    assert pres._label("HTTPServer") == "HTTP Server"


def test_booleans_and_nulls_are_written_for_a_person():
    out = pres.render_result({"truncated": False, "note": None})
    assert "خیر" in out
    assert "—" in out


def test_rendering_never_raises_on_junk():
    class Awkward:
        def __repr__(self):  # noqa: D105
            raise RuntimeError("no")

    # Must not raise: this runs on a path that already has one failure on it.
    assert pres.render_result({"x": Awkward()}, heading="ن") is not None


def test_an_empty_result_says_so_rather_than_rendering_nothing():
    out = pres.render_result({}, heading="نتیجه")
    assert "نتیجه‌ای برای نمایش وجود ندارد" in out


# --------------------------------------------------------------------------- #
# the old client must not start seeing markup
# --------------------------------------------------------------------------- #
def test_plain_text_strips_the_markers_a_pre_renderer_build_cannot_show():
    """`message` is what a phone built before the renderer displays verbatim.
    That build must not suddenly start showing ## and ** at clinicians."""
    plain = pres.as_plain_text("## عنوان\n\n- **مجموع:** ۱۲۸\n---\n*نکته*")
    assert "#" not in plain
    assert "*" not in plain
    assert "عنوان" in plain and "مجموع" in plain and "نکته" in plain


def test_good_prose_is_preferred_over_a_rendering():
    """The rendered data is a floor, not a preference: it answers "what is in
    the payload", never "what did you ask"."""
    display, fallback = pres.build_display(
        "## پاسخ\n\n- **مجموع:** ۱۲۸", {"admissions": 128}
    )
    assert fallback is False
    assert display.startswith("## پاسخ")
