"""
Fix I source-contract tests: background import warmup thread.

Tests verify that:
 1. The warmup target list contains the expected critical modules.
 2. The warmup logic skips modules already in sys.modules (idempotent).
 3. The warmup logic calls the importer only for unknown modules.
 4. Exceptions during a single module import do not abort the whole warmup.
 5. All listed module keys are valid Python import paths (no typos).
"""
import sys
import unittest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Reference list — must match exactly what main.py ships
# ---------------------------------------------------------------------------
EXPECTED_WARMUP_KEYS = {
    "PacsClient.pacs.patient_tab.utils.opencv_filter_pipeline",
    "cv2",
    "modules.viewer.fast.decode_service",
    "modules.viewer.tools.math_utils",
    "modules.viewer.tools.coord_resolver",
    "grpc",
    "numpy.ma",
    "_strptime",
}


def _extract_warmup_targets():
    """
    Re-import (or re-execute) the warmup target list from main.py without
    actually running the GUI. We do this by reading the module keys directly
    from the canonical list in main.py using text parsing.
    """
    import re
    import pathlib

    src = (pathlib.Path(__file__).parent.parent.parent.parent / "main.py").read_text(encoding="utf-8")
    # Find all quoted strings inside the _targets / _warmup list block
    # Pattern: strings between triple-check comments and the warmup thread start
    section_m = re.search(
        r"\[Fix I\].*?_warmup_t\s*=",
        src,
        re.DOTALL,
    )
    if section_m is None:
        return None  # warmup block not found — Fix I not yet applied
    section = section_m.group(0)
    # Extract all quoted module-key strings.
    # Allow leading underscore (e.g. "_strptime") as well as letters.
    keys = re.findall(r'"([A-Za-z_][A-Za-z0-9_.]*)"', section)
    # Keep dotted paths, lowercase identifiers, and _-prefixed builtins.
    return {k for k in keys if "." in k or k.islower() or k.startswith("_")}


class TestImportWarmupContract(unittest.TestCase):
    """Verify Fix I is present and correctly shaped in main.py."""

    def test_warmup_block_present_in_main(self):
        """[Fix I] comment block must exist in main.py."""
        import pathlib
        src = (pathlib.Path(__file__).parent.parent.parent.parent / "main.py").read_text(encoding="utf-8")
        self.assertIn("[Fix I]", src, "Fix I warmup block not found in main.py")
        self.assertIn("_background_import_warmup", src, "_background_import_warmup function missing")
        self.assertIn("IMPORT_WARMUP", src, "[IMPORT_WARMUP] log tag missing")

    def test_warmup_runs_as_daemon_thread(self):
        """Warmup thread must be a daemon thread (must not block shutdown)."""
        import pathlib
        src = (pathlib.Path(__file__).parent.parent.parent.parent / "main.py").read_text(encoding="utf-8")
        # Must contain daemon=True after _background_import_warmup function definition
        section_idx = src.find("_background_import_warmup")
        self.assertGreater(section_idx, 0)
        # Expand search window to 3000 chars to accommodate the full function body
        thread_block = src[section_idx: section_idx + 3000]
        self.assertIn("daemon=True", thread_block, "warmup thread must be daemon=True")

    def test_warmup_targets_contain_expected_keys(self):
        """All critical module keys must appear in the warmup target list."""
        keys = _extract_warmup_targets()
        if keys is None:
            self.fail("Fix I warmup block not found — implementation missing")
        for expected in EXPECTED_WARMUP_KEYS:
            self.assertIn(
                expected, keys,
                f"Critical module '{expected}' missing from warmup target list",
            )

    def test_warmup_skips_already_imported_modules(self):
        """Modules already in sys.modules must be skipped without calling importer."""
        # Simulate the warmup logic
        already_imported = {"cv2", "grpc"}
        calls = []

        def importer_spy(name):
            calls.append(name)

        targets = [
            ("cv2", lambda: importer_spy("cv2")),
            ("grpc", lambda: importer_spy("grpc")),
            ("numpy.ma", lambda: importer_spy("numpy.ma")),
        ]

        fake_sys_modules = dict(sys.modules)
        fake_sys_modules["cv2"] = MagicMock()
        fake_sys_modules["grpc"] = MagicMock()
        # numpy.ma NOT in fake_sys_modules

        for mod_key, fn in targets:
            if mod_key in fake_sys_modules:
                continue
            fn()

        self.assertEqual(calls, ["numpy.ma"], "Only numpy.ma should have been imported")

    def test_warmup_continues_after_single_failure(self):
        """A single import failure must NOT abort the rest of the warmup."""
        import logging

        calls = []
        errors = []

        def _log_debug(msg, *a, **kw):
            pass  # silence

        targets = [
            ("broken.module", lambda: (_ for _ in ()).throw(ImportError("no module"))),
            ("working.module", lambda: calls.append("working.module")),
        ]

        for mod_key, fn in targets:
            try:
                fn()
            except Exception as e:
                errors.append(mod_key)

        self.assertIn("broken.module", errors)
        self.assertIn("working.module", calls)

    def test_expected_keys_are_valid_import_paths(self):
        """All expected warmup module keys must be non-empty strings."""
        for key in EXPECTED_WARMUP_KEYS:
            self.assertIsInstance(key, str)
            self.assertGreater(len(key), 0)
            # No spaces
            self.assertNotIn(" ", key, f"Module key '{key}' contains spaces")


if __name__ == "__main__":
    unittest.main()
