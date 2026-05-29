from modules.web_browser.state_store import BrowserStateStore


def test_state_store_migrates_legacy_favorites(tmp_path):
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    legacy_file = legacy_root / "browser_bookmarks.json"
    legacy_file.write_text(
        '{"1": {"name": "Example", "url": "https://example.com"}}',
        encoding="utf-8",
    )

    store = BrowserStateStore(
        root_dir=tmp_path / "state",
        profile_dir=tmp_path / "profile",
        saved_pages_dir=tmp_path / "saved_pages",
        legacy_root=legacy_root,
    )

    favorites = store.load_favorites()

    assert favorites["1"]["url"] == "https://example.com"
    assert (tmp_path / "state" / "favorites.json").exists()


def test_state_store_trims_history(tmp_path):
    store = BrowserStateStore(
        root_dir=tmp_path / "state",
        profile_dir=tmp_path / "profile",
        saved_pages_dir=tmp_path / "saved_pages",
        legacy_root=tmp_path / "legacy",
    )

    payload = [{"url": f"https://example.com/{index}"} for index in range(350)]
    store.save_page_history(payload)
    loaded = store.load_page_history()

    assert len(loaded) == store.MAX_PAGE_HISTORY
    assert loaded[0]["url"] == "https://example.com/0"


def test_state_store_migrates_saved_items_from_existing_entries(tmp_path):
    store = BrowserStateStore(
        root_dir=tmp_path / "state",
        profile_dir=tmp_path / "profile",
        saved_pages_dir=tmp_path / "saved_pages",
        legacy_root=tmp_path / "legacy",
    )

    store.save_saved_pages(
        [
            {
                "title": "Saved Page",
                "url": "https://example.com/page",
                "save_path": "C:/tmp/page.html",
                "saved_at": "2026-03-12T10:00:00",
            }
        ]
    )
    store.save_download_history(
        [
            {
                "filename": "video.mp4",
                "url": "https://example.com/video",
                "save_path": "C:/tmp/video.mp4",
                "timestamp": "2026-03-12T11:00:00",
            }
        ]
    )

    saved_items = store.load_saved_items()

    assert [item["item_type"] for item in saved_items] == ["page", "download"]
    assert (tmp_path / "state" / "saved_items.json").exists()
