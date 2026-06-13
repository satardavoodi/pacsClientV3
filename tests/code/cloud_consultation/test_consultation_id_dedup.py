"""Resume/retry de-dup guard (ADR-0009 hardening): a fixed consultation_id is
honored end-to-end so a paused→resumed or retried upload reuses the SAME
consultation instead of creating a duplicate. Default (no id) stays random.
Qt-free."""
import os
import tempfile

from modules.cloud_consultation.consultation.envelope import build_envelope
from modules.cloud_consultation.consultation.service import seal_package_as_consultation


def test_build_envelope_reuses_fixed_id():
    a = build_envelope(case_title="t", clinical_question="q", from_user={}, consultation_id="FIXED")
    b = build_envelope(case_title="t", clinical_question="q", from_user={}, consultation_id="FIXED")
    assert a.consultation_id == b.consultation_id == "FIXED"


def test_build_envelope_default_is_random():
    a = build_envelope(case_title="t", clinical_question="q", from_user={})
    b = build_envelope(case_title="t", clinical_question="q", from_user={})
    assert a.consultation_id != b.consultation_id and len(a.consultation_id) >= 16


def test_seal_forwards_consultation_id():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "manifest.json"), "w").write('{"x":1}')
    s1 = seal_package_as_consultation(d, case_title="t", clinical_question="q",
                                      from_user={}, consultation_id="CID-1")
    s2 = seal_package_as_consultation(d, case_title="t", clinical_question="q",
                                      from_user={}, consultation_id="CID-1")
    assert s1.consultation_id == s2.consultation_id == "CID-1"
