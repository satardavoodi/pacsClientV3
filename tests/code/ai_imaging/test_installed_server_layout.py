"""Server payload selection cannot fall back to mutable shared packages."""
import pytest


def package(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.installed_layout import seal
    from modules.ai_imaging.eagle_eye_remote.release_package import stamp
    core = tmp_path / 'revision' / 'core'
    core.mkdir(parents=True)
    (core / 'AIPacs.exe').write_bytes(b'synthetic-core')
    packages = core.parent / 'plugin_packages'
    packages.mkdir()
    (packages / 'model.bin').write_bytes(b'synthetic-model')
    seal(core, packages)
    stamp(core, 'test')
    return core, packages


def test_server_selects_only_core_bound_sibling(tmp_path, monkeypatch):
    import aipacs_runtime as runtime
    core, packages = package(tmp_path)
    monkeypatch.setattr(runtime, 'is_frozen', lambda: True)
    monkeypatch.setattr(runtime, 'install_root', lambda: core)
    assert runtime.bundled_module_packages_search_roots() == [packages]


def test_changed_selector_refuses_fallback(tmp_path, monkeypatch):
    import aipacs_runtime as runtime
    core, _ = package(tmp_path)
    (core / 'eagle-eye-payloads.json').write_text('{}')
    monkeypatch.setattr(runtime, 'is_frozen', lambda: True)
    monkeypatch.setattr(runtime, 'install_root', lambda: core)
    with pytest.raises(ValueError, match='changed'):
        runtime.bundled_module_packages_search_roots()


def test_payload_identity_detects_sibling_revision_change(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.installed_layout import selection
    from modules.ai_imaging.eagle_eye_remote.startup_barrier import payload_identity
    core, packages = package(tmp_path)
    selected = selection(core)
    assert len(payload_identity(core, selected)) == 64
    (packages / 'model.bin').write_bytes(b'changed')
    with pytest.raises(ValueError, match='revision mismatch'):
        payload_identity(core, selected)


def test_server_inventory_rejects_unlisted_sibling(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.installed_layout import selection
    from tools.eagle_eye.installed_release_host import InstalledReleaseHost
    core, _ = package(tmp_path)
    private = tmp_path / 'private'
    private.mkdir()
    config = private / 'server.json'
    config.write_text('{}')
    class Backend:
        def protect(self, path):
            pass
    host = InstalledReleaseHost(core.parent, private, config, Backend())
    selected = selection(core)
    host.describe(core, payloads=selected)
    (core.parent / 'unlisted.dll').write_bytes(b'extra')
    with pytest.raises(ValueError, match='unlisted'):
        host.describe(core, payloads=selected)
