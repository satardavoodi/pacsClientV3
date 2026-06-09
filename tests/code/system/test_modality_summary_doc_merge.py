"""Guard for the Main-Page search modality summary DOC merge (2026-06-09).

DOC (scanned/dicomized clinical-history documents) is an auxiliary series, not
a real imaging modality. The results summary must count a 'MR, DOC' study as
MRI — i.e. '27 MR' + '24 MR, DOC' collapses to '51 MRI', with no separate DOC
category. Only the summary counting changes; DOC series in studies are
untouched.

The real logic lives in PatientTableWidget._modality_summary_label (a
self-contained staticmethod). To avoid importing the heavy Qt widget (and its
qtawesome icon calls that crash offscreen), we exec just that function's source
against a clean namespace and exercise it directly.
"""
import textwrap
from collections import Counter
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_TABLE = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
          / "patient_table_widget.py")


def _load_label_fn():
    src = _TABLE.read_text(encoding="utf-8", errors="ignore")
    start = src.index("def _modality_summary_label(raw):")
    end = src.index("def _build_modality_count_summary", start)
    fn_src = textwrap.dedent(src[start:end]).rstrip() + "\n"
    ns = {}
    exec(fn_src, ns)  # noqa: S102 — test-local exec of repo source
    return ns["_modality_summary_label"]


@pytest.fixture(scope="module")
def label():
    return _load_label_fn()


def test_mri_with_doc_counts_as_mri(label):
    assert label("MR") == "MRI"
    assert label("MR, DOC") == "MRI"
    assert label("MR with Document") == "MRI"
    # critically, all three normalize to the SAME key so they merge
    assert label("MR") == label("MR, DOC") == "MRI"


def test_other_parent_modalities_keep_their_modality(label):
    assert label("CT, DOC") == "CT"
    assert label("DX, DOC") == "DX"      # radiography
    assert label("CR, DOC") == "CR"
    assert label("US") == "US"


def test_document_only_study_is_not_a_doc_category(label):
    # Pure-document study → OTHER, never a literal 'DOC' modality category.
    assert label("DOC") == "OTHER"
    assert label("DOCUMENT") == "OTHER"
    assert label("") == "OTHER"
    assert "DOC" != label("DOC")


def test_multi_real_modality_preserved_and_mapped(label):
    # A genuine multi-modality study keeps both, DOC still stripped, MR→MRI.
    assert label("MR, CT") == "MRI, CT"
    assert label("MR, CT, DOC") == "MRI, CT"


def test_doc_order_and_duplicates_handled(label):
    assert label("DOC, MR") == "MRI"          # DOC first
    assert label("MR, MR, DOC") == "MRI"      # dedupe


def test_aggregation_merges_doc_into_parent(label):
    # Mirror the summary's per-row tally: 27 pure MR + 24 MR+DOC → 51 MRI.
    rows = ["MR"] * 27 + ["MR, DOC"] * 24 + ["CT"] * 5
    tally = Counter(label(r) for r in rows)
    assert tally["MRI"] == 51
    assert tally["CT"] == 5
    # No DOC-derived category leaked into the summary.
    assert all("DOC" not in k for k in tally)


def test_user_exact_combos_friendly_name_no_space(label):
    # The exact strings the user reported (friendly name, no space after comma).
    assert label("MRI,DOC") == "MRI"
    assert label("CT,DOC") == "CT"
    assert label("CR,DOC") == "CR"
    assert label("DX,DOC") == "DX"
    # parent-only and parent+DOC MUST normalize to the SAME key so they merge
    for parent in ("MRI", "CT", "CR", "DX"):
        assert label(parent) == label(f"{parent},DOC") == parent


def test_user_examples_aggregate(label):
    # MRI = 27 + MRI,DOC = 24 → 51 MRI ; CT = 15 + CT,DOC = 10 → 25 CT
    rows = ["MRI"] * 27 + ["MRI,DOC"] * 24 + ["CT"] * 15 + ["CT,DOC"] * 10
    tally = Counter(label(r) for r in rows)
    assert tally["MRI"] == 51
    assert tally["CT"] == 25
    # exactly two clinical categories, no DOC-combo category survives
    assert set(tally) == {"MRI", "CT"}


def test_summary_method_uses_the_label_helper():
    body = _TABLE.read_text(encoding="utf-8", errors="ignore")
    # The aggregation must route every row through the DOC-merging helper.
    assert "self._modality_summary_label(raw)" in body
