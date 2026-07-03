"""AIPacs — Nuitka build specification (complete).

This is the single source of truth for the *simple / monolithic* Nuitka build,
driven by ``build_nuitka.py`` at the project root:

    python build_nuitka.py                        # uses this spec by default
    python build_nuitka.py --clean                # clean dist/build first
    python build_nuitka.py --dry-run              # print the Nuitka command only
    python build_nuitka.py --onefile              # single-file exe (slower start)

It is intentionally a *direct translation* of the working PyInstaller build
(`AIPacs.spec` at the project root). Whenever you add a data dir, hidden import,
plugin, codec, or exclude to `AIPacs.spec`, mirror it here so the two build
back-ends stay in lock-step. See `builder nuitka/README_NUITKA_BUILD.md`.

NOTE ON SEPARATION OF CONCERNS
------------------------------
There are two Nuitka entry points in this repo, and they do NOT overlap:

* ``build_nuitka.py`` + this spec  → the simple, monolithic standalone build
  (everything bundled into one ``dist`` tree). Best for a quick, reproducible,
  hard-to-reverse-engineer executable. This is what this file configures.
* ``builder nuitka/build_nuitka_release.py`` → the staged, checkpointed release
  pipeline (Engine + external plugin packages + Inno Setup installer). It has
  its own inclusion logic and reads only ``LTO`` / ``ICON`` / ``ENTRY_POINT`` /
  ``OPTIONAL_DATA`` / ``NOFOLLOW_IMPORTS`` from this file.

Neither touches the PyInstaller pipeline (`AIPacs.spec`, `builder/`).
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Project layout
# --------------------------------------------------------------------------- #
# This spec lives in ``<project>/builder nuitka/``; the project root is its
# parent. ``build_nuitka.py`` resolves every relative path below against the
# project root (its own directory), so keep these relative to the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _exists(rel: str) -> bool:
    return (PROJECT_ROOT / rel).exists()


# --------------------------------------------------------------------------- #
# Core build identity
# --------------------------------------------------------------------------- #
ENTRY_POINT = "main.py"
APP_NAME = "AIPacs"

# Output tree kept *inside* the nuitka builder folder so it never collides with
# the PyInstaller build (`builder/output`) or the staged pipeline
# (`builder nuitka/output`). Nuitka writes ``main.dist`` under this directory.
OUTPUT_DIR = "builder nuitka/output/dist/AIPacs_nuitka"

STANDALONE = True          # one self-contained folder (default, fastest startup)
ONEFILE = False            # flip to True (or pass --onefile) for a single .exe
WINDOWS_CONSOLE = False    # no console window for the GUI app
ICON = "Qss/images/favicon.ico"

# --------------------------------------------------------------------------- #
# Nuitka plugins
# --------------------------------------------------------------------------- #
# The PySide6 plugin is mandatory — it bundles the Qt runtime, the platform
# plugins (windows/qwindows.dll), QML, and the shiboken bridge correctly.
PLUGINS = [
    "pyside6",
]

# --------------------------------------------------------------------------- #
# Package data to force-embed (Nuitka --include-package-data)
# --------------------------------------------------------------------------- #
# PySide6 is handled by build_nuitka.py directly; these are the extra packages
# whose *data files* (fonts, resources) must ship or the app misbehaves.
PACKAGE_DATA = [
    "qtawesome",       # icon fonts — missing => blank toolbar icons
    "Custom_Widgets",  # QSS/JSON theme assets used by the custom widgets
]

# --------------------------------------------------------------------------- #
# Distribution metadata (Nuitka --include-distribution-metadata)
# --------------------------------------------------------------------------- #
# pylibjpeg discovers its DICOM decoder plugins (libjpeg / openjpeg / rle) via
# each distribution's *.dist-info METADATA entry points. Bundling the modules
# alone leaves pylibjpeg reporting ZERO decoders, so every JPEG 2000 /
# JPEG-lossless / RLE image silently fails to decode in the frozen build.
# This is the Nuitka equivalent of PyInstaller's copy_metadata() calls.
DIST_METADATA = [
    "pylibjpeg",
    "pylibjpeg-libjpeg",
    "pylibjpeg-openjpeg",
    "pylibjpeg-rle",
]

# --------------------------------------------------------------------------- #
# Whole-package includes (Nuitka --include-package)
# --------------------------------------------------------------------------- #
# --include-package pulls in the package AND all of its submodules, so we do not
# have to enumerate every submodule the way PyInstaller's collect_submodules()
# does. Keep this list to packages that are imported dynamically / lazily and
# therefore not reliably discovered by Nuitka's static import following.
INCLUDE_PACKAGES = [
    # First-party
    "PacsClient",
    "database",
    # NOTE: do NOT blanket-include the whole `modules` package. It does a
    # recursive filesystem walk that sweeps in the 789 MB Advanced 3D Slicer
    # vendored CPython (build/python-install/Lib/test/...) and crashes Nuitka
    # 4.0.8 (listcomp_2__.0_clone) — and --nofollow-import-to does NOT override
    # that walk. Instead, Nuitka follows the modules actually imported from
    # main.py, and we force-include the specific dynamically-loaded subpackages
    # below (zeta_mpr, orthogonal, EchoMind). Add more here if a runtime
    # ModuleNotFoundError appears for a lazily-imported modules.* subpackage.
    "modules.EchoMind",
    # settings_ui is imported lazily via package __getattr__/import_module.
    "PacsClient.pacs.workstation_ui.settings_ui",
    # MPR / 3D (dynamic imports through toolbar handlers)
    "modules.mpr.zeta_mpr",
    "modules.mpr.orthogonal",
    # UI / third-party with dynamic submodule loading
    "Custom_Widgets",
    "vtkmodules",
    # Numerics / medical imaging
    "numpy",
    "pydicom",
    "pynetdicom",
    "SimpleITK",
    "pandas",
]

# --------------------------------------------------------------------------- #
# Forced / hidden imports (Nuitka --include-module)
# --------------------------------------------------------------------------- #
# Mirror of AIPacs.spec hiddenimports. --include-module forces a single module
# in even when Nuitka cannot see the import statically (lazy imports, plugin
# discovery, C-extension entry points).
FORCED_IMPORTS = [
    # Project bootstrap helpers
    "_project_root",
    "aipacs_runtime",
    "PacsClient.utils.data_paths",
    # Database
    "database",
    "database.core",
    "database.manager",
    # PySide6 essentials (the plugin covers the runtime; these guarantee the
    # Python bindings are compiled in even if only imported lazily)
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtPrintSupport",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "shiboken6",
    # VTK utility submodules (imported lazily by the render backends)
    "vtkmodules.all",
    "vtkmodules.util",
    "vtkmodules.util.data_model",
    "vtkmodules.util.execution_model",
    "vtkmodules.util.numpy_support",
    "vtkmodules.util.keys",
    "vtkmodules.util.colors",
    "vtkmodules.util.misc",
    "vtkmodules.util.vtkAlgorithm",
    "vtkmodules.util.vtkConstants",
    "vtkmodules.util.vtkImageExportToArray",
    "vtkmodules.util.vtkImageImportFromArray",
    "vtkmodules.qt",
    "vtkmodules.qt.QVTKRenderWindowInteractor",
    "vtk",
    # numpy internals
    "numpy.core",
    "numpy.core._multiarray_umath",
    "numpy.core._dtype_ctypes",
    "numpy.core._methods",
    "numpy._core",
    "numpy._core.multiarray",
    "numpy._core._multiarray_umath",
    "numpy._core._methods",
    "numpy.linalg",
    "numpy.fft",
    "numpy.random",
    # Medical imaging
    "SimpleITK",
    "SimpleITK._SimpleITK",
    "pydicom",
    "pydicom.encoders",
    "pydicom.pixel_data_handlers",
    "pydicom.pixel_data_handlers.numpy_handler",
    # Compressed-DICOM decode handlers (must all ship — see DIST_METADATA note)
    "pydicom.pixel_data_handlers.pylibjpeg_handler",
    "pydicom.pixel_data_handlers.pillow_handler",
    "pydicom.pixel_data_handlers.rle_handler",
    "pydicom.pixel_data_handlers.gdcm_handler",  # no-ops gracefully if absent
    "pylibjpeg",
    "pylibjpeg.utils",
    "libjpeg",   # pylibjpeg-libjpeg plugin (JPEG baseline/extended/lossless)
    "openjpeg",  # pylibjpeg-openjpeg plugin (JPEG 2000)
    "rle",       # pylibjpeg-rle plugin (RLE Lossless)
    "PIL",
    "PIL.Image",
    "pydicom.fileset",   # DICOMDIR creation (CD writing)
    "pydicom.uid",
    "pydicom.dataset",
    "pydicom.charset",
    "pynetdicom",
    "pynetdicom.sop_class",
    # Document / OCR (imported lazily; bundle so installed app matches dev)
    "pypdf",
    "pptx",
    "pytesseract",
    # Network / RPC
    "grpc",
    "grpc._cython.cygrpc",
    "googleapiclient",
    "googleapiclient.discovery",
    "google.auth",
    "google.oauth2",
    # UI libraries
    "qasync",
    "qtawesome",
    "qtawesome.iconic_font",
    "qtawesome.fonts",
    "Custom_Widgets",
    "Custom_Widgets.QAppSettings",
    "Custom_Widgets.Widgets",
    # Data handling
    "pandas",
    "pandas._libs",
    "pandas._libs.tslibs",
    "natsort",
    # Sound
    "sounddevice",
    "soundfile",
    "speech_recognition",
    # System
    "sqlite3",
    "asyncio",
    "concurrent.futures",
    # Misc third-party
    "openai",
    "dotenv",
    "cv2",
    # Zeta MPR entry modules (the package include above pulls submodules, these
    # guarantee the individually-referenced modules survive optimisation)
    "modules.mpr.zeta_mpr.curved_mpr",
    "modules.mpr.zeta_mpr.CurveMPR",
    "modules.mpr.orthogonal",
]

# --------------------------------------------------------------------------- #
# Excludes (Nuitka --nofollow-import-to)
# --------------------------------------------------------------------------- #
# Mirror of AIPacs.spec excludes. Keeps the build smaller and avoids pulling in
# conflicting Qt bindings or huge unused ML stacks. fitz/pymupdf are excluded
# because they crash the compile and are imported conditionally at runtime.
EXCLUDES = [
    "PyQt5",
    "PyQt6",
    "tkinter",
    "torch",
    "tensorflow",
    "transformers",
    "pytest",
    "IPython",
    "jupyter",
    "fitz",
    "pymupdf",
    # Advanced 3D Slicer is a SEPARATE external application (~789 MB) that ships
    # its OWN embedded CPython under
    # modules/mpr/advanced_3d_slicer/slicer_custom_app/.../build/python-install/.
    # It is launched as an external process (slicer_launcher.py), never imported
    # into this exe. Compiling it (a) is wrong and (b) triggers a Nuitka 4.0.8
    # internal optimizer crash (AssertionError: listcomp_2__.0_clone) on the
    # vendored CPython test-suite. Never let the broad `modules` include sweep it.
    "modules.mpr.advanced_3d_slicer",
]

# ``NOFOLLOW_IMPORTS`` is read by BOTH build back-ends. For the simple
# monolithic build we fold the excludes in here as well; the staged release
# pipeline only consumes the ``modules.*`` entries (to keep optional plugins
# external) and ignores the rest.
NOFOLLOW_IMPORTS = list(EXCLUDES)

# --------------------------------------------------------------------------- #
# Data directories / files (Nuitka --include-data-dir / --include-data-files)
# --------------------------------------------------------------------------- #
# (source_relative_to_project_root, destination_relative_to_exe). Only entries
# that actually exist on disk are emitted (build_nuitka.py guards with is_dir/
# is_file), so absent optional files are skipped cleanly.
DATA_DIRS = [
    ("PacsClient", "PacsClient"),
    ("Fonts", "Fonts"),
    ("Qss", "Qss"),          # icons + images live here
    ("config", "config"),
    # EchoMind Secretary non-python data (catalog + prompts); without these the
    # frozen Secretary finds an EMPTY catalog and LLM-fallback commands fail.
    ("modules/EchoMind/secretary/catalog", "modules/EchoMind/secretary/catalog"),
    ("modules/EchoMind/secretary/prompts", "modules/EchoMind/secretary/prompts"),
    ("json-styles", "json-styles"),
    ("generated-files", "generated-files"),
]

# Single-file / optional data. build_nuitka.py places a file at
# ``dest/basename`` (or at the exe root when dest == ".").
OPTIONAL_DATA = [
    ("modules/EchoMind/secretary/module_map.yaml", "modules/EchoMind/secretary"),
    ("servers.json", "."),
    ("browser_bookmarks.json", "."),
    # Software-OpenGL (Mesa) fallback DLLs — required on machines without a GPU
    # OpenGL driver so VTK/Qt still render. Copied next to the exe.
    ("graphics_runtime/opengl32sw.dll", "."),
    ("graphics_runtime/osmesa.dll", "."),
    ("graphics_runtime/pipe_swrast.dll", "."),
]

# Prune data entries whose source is missing so a partial checkout still builds.
DATA_DIRS = [(s, d) for (s, d) in DATA_DIRS if _exists(s)]
OPTIONAL_DATA = [(s, d) for (s, d) in OPTIONAL_DATA if _exists(s)]

# --------------------------------------------------------------------------- #
# Runtime environment (Nuitka has no PyInstaller-style runtime hooks)
# --------------------------------------------------------------------------- #
# PyInstaller used hooks/runtime_hook_numpy.py to pin BLAS thread counts and
# hooks/runtime_hook_vtk.py to pre-import vtkmodules.util. build_nuitka.py sets
# these env vars for the *build* process; the VTK pre-imports are covered by the
# FORCED_IMPORTS above. If you need them at *runtime*, set them in main.py's
# very first lines (they are performance/stability tweaks, not correctness).
RUNTIME_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}

# --------------------------------------------------------------------------- #
# Compiler / performance knobs
# --------------------------------------------------------------------------- #
# LTO: "auto" | "yes" | "no". "yes" gives the smallest/hardest binary but is the
# slowest to build; "auto" is a safe default that also drives the staged
# pipeline.
LTO = "auto"

# C compiler: None (let Nuitka pick MSVC/clang) | "msvc" | "clang" | "mingw64" |
# "zig". Leave None for the most reliable Windows build with Visual Studio.
C_COMPILER = None

# Parallel C compile jobs. 0 => Nuitka default (all cores).
JOBS = 0

SHOW_PROGRESS = True
SHOW_MEMORY = False

# Nuitka XML compilation report (written under the output tree).
REPORT_FILE = "builder nuitka/output/reports/nuitka_build_report.xml"

# Extra verbatim flags appended last. These improve reproducibility / stability:
#   --assume-yes-for-downloads : never block on an interactive prompt (ccache/zig)
#   --python-flag=no_site      : ignore site-packages customisations at runtime
#   --python-flag=static_hashes: deterministic hashing (reproducible builds)
#   --python-flag=safe_path    : do not import from the CWD in the frozen app
#   --remove-output            : delete the intermediate .build tree on success
EXTRA_FLAGS = [
    "--assume-yes-for-downloads",
    "--python-flag=static_hashes",
    "--python-flag=safe_path",
    "--remove-output",
]
