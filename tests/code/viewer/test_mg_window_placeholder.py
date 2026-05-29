from PacsClient.pacs.patient_tab.utils.dicom_windowing import normalize_window_level


def test_mg_monochrome1_full_range_placeholder_is_treated_as_missing():
    ww, wc = normalize_window_level(
        32768,
        32768,
        treat_legacy_placeholder_as_missing=True,
        treat_mg_full_range_placeholder_as_missing=True,
        modality="MG",
        photometric="MONOCHROME1",
        presentation_intent_type="FOR PRESENTATION",
    )
    assert ww is None
    assert wc is None


def test_mg_full_range_kept_when_heuristic_disabled():
    ww, wc = normalize_window_level(
        32768,
        32768,
        treat_legacy_placeholder_as_missing=True,
        treat_mg_full_range_placeholder_as_missing=False,
        modality="MG",
        photometric="MONOCHROME1",
        presentation_intent_type="FOR PRESENTATION",
    )
    assert ww == 32768.0
    assert wc == 32768.0


def test_non_mg_or_non_monochrome1_not_rejected_by_mg_placeholder_rule():
    ww_ct, wc_ct = normalize_window_level(
        32768,
        32768,
        treat_mg_full_range_placeholder_as_missing=True,
        modality="CT",
        photometric="MONOCHROME2",
    )
    ww_mg_mono2, wc_mg_mono2 = normalize_window_level(
        32768,
        32768,
        treat_mg_full_range_placeholder_as_missing=True,
        modality="MG",
        photometric="MONOCHROME2",
        presentation_intent_type="FOR PRESENTATION",
    )
    assert ww_ct == 32768.0 and wc_ct == 32768.0
    assert ww_mg_mono2 == 32768.0 and wc_mg_mono2 == 32768.0
