"""SR documents remain selectable without being counted as pixel images."""
from tests.code.ui_services.test_local_thumbnail_stream import subject  # noqa: F401


def test_local_sr_card_survives_zero_pixel_inventory(subject, monkeypatch):
    subject.rows[:] = [dict(subject.rows[0], modality="SR")]
    monkeypatch.setattr(subject.inventory, "inspect_series_pixel_inventory",
                        lambda path: subject.inventory.SeriesPixelInventory(14, 0, 0))
    monkeypatch.setattr(subject.utils, "repair_local_series_thumbnail",
                        lambda *a: (_ for _ in ()).throw(AssertionError("SR pixel thumbnail attempted")))
    entries = subject.owner._build_local_thumbnail_entries("study-a")
    assert len(entries) == 1
    assert entries[0]["modality"] == "SR"
    assert entries[0]["image_count"] == 0
    assert entries[0]["document_count"] == 14
