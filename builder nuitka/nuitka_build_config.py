"""Shared configuration for the staged Nuitka build pipeline."""

from pathlib import Path

# Project structure
PROJECT_ROOT = Path(__file__).resolve().parent.parent
NUITKA_ROOT = PROJECT_ROOT / "builder nuitka"

# Output roots
OUTPUT_ROOT = NUITKA_ROOT / "output"
DIST_DIR = OUTPUT_ROOT / "dist"
STAGE_DIR = OUTPUT_ROOT / "stage"
INSTALLER_DIR = NUITKA_ROOT / "installer"
INSTALLER_OUTPUT_DIR = OUTPUT_ROOT / "installer"

# Build state and diagnostics
STATE_FILE = OUTPUT_ROOT / "build_state.json"
LOGS_DIR = OUTPUT_ROOT / "logs"
REPORTS_DIR = OUTPUT_ROOT / "reports"
CHECKPOINTS_DIR = OUTPUT_ROOT / "checkpoints"

# Caches (project-local where possible)
CACHE_DIR = OUTPUT_ROOT / "cache"
NUITKA_CACHE_DIR = OUTPUT_ROOT / "nuitka-cache"
CCACHE_DIR = OUTPUT_ROOT / "ccache"

# Legacy/compat helper paths
PACKAGES_DIR = OUTPUT_ROOT / "packages"
MANIFEST_DIR = STAGE_DIR / "manifest"

# Build constants
APP_NAME = "AIPacs"
INSTALLER_APP_NAME = "AIPacs (Nuitka Edition)"
NUITKA_INSTALLER_GUID = "{3E7B29F2-22DF-4B2C-8D3A-1E7C25772F76}"


def ensure_output_dirs() -> None:
    """Create all required output/caching directories."""
    dirs = [
        OUTPUT_ROOT,
        DIST_DIR,
        STAGE_DIR,
        STAGE_DIR / "core",
        STAGE_DIR / "plugin_packages",
        MANIFEST_DIR,
        INSTALLER_OUTPUT_DIR,
        LOGS_DIR,
        REPORTS_DIR,
        CHECKPOINTS_DIR,
        CACHE_DIR,
        NUITKA_CACHE_DIR,
        CCACHE_DIR,
        PACKAGES_DIR,
    ]
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
