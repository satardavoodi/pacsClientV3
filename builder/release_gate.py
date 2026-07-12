"""Release gate — build-time guards against "works in source, missing in installed build".

Background (2026-06-11, docs/pipelines/online-consultation-education.md §12–§13)
-------------------------------------------------------------------------------
Three independent mechanisms shipped a build where Online Consultation worked in
source runs but was silently missing/disabled in the frozen install:

1. ``seed_user_config_defaults()`` never seeded config SUBDIRECTORY files, so
   feature-flag files (``identity/identity.json``,
   ``cloud_consultation/cloud_consultation.json``) never reached
   ``%APPDATA%\\AIPacs\\config``.
2. The installer's Pascal ``WriteInstallationProfile()`` lagged
   ``MODULE_CATALOG`` — the component copied files but the module was never
   enabled in ``installation_profile.json``.
3. Builds were not rebuilt after ``tools/dev/sync_plugin_mirrors.py`` — a stale
   plugin-mirror payload risk.

This module is the BUILD-TIME layer of the prevention system (the repo-level
layer is ``tests/code/builder/test_release_parity_guards.py``; the field layer
is ``tools/maintenance/install_doctor.py``). It is wired into
``builder/build_release.py`` (escape hatch: ``--skip-release-gate``,
emergencies only) and is also runnable stand-alone:

    python builder/release_gate.py --pre-build      # mirror freshness only
    python builder/release_gate.py --stage-check    # checks against builder/output/stage
    python builder/release_gate.py                  # both

Checks
------
PRE-BUILD
    * source_freshness        — the build tree IS the current release source:
      not behind its upstream and on a release branch. Catches a build PC parked
      on a stale/old branch, or one that forgot ``git pull`` (the 2026-06-16
      incident: a secondary build PC sitting on an old ``DR.vahid`` (v2.2.x)
      branch froze pre-v3.2.0 MPR bytecode while all dev lands on
      beta-version/main — only the post-stage MPR gate caught it, after a full
      build). This fails FAST, before PyInstaller runs.
    * plugin_mirrors          — payload mirrors SHA-equal to canonical sources.
POST-STAGE
    * frozen_runtime_pyz      — the staged AIPacs.exe's embedded PYZ carries the
      CURRENT ``aipacs_runtime``: catalog ids == source MODULE_CATALOG ids and
      the config-migration sentinel symbols exist.
    * stage_config_parity     — every shippable repo ``config/`` template exists
      under ``stage/core/engine/config`` with identical bytes (and no
      ``secrets/`` file leaked into the stage).
    * stage_plugin_packages   — every optional catalog id has its staged package
      under ``stage/plugin_packages`` (advanced_mpr respected as conditional).
    * education_payload_set   — the education plugin-mirror payload contains the
      same ``*.py`` file SET as ``modules/education`` (catches a NEW canonical
      file that was never synced — invisible to the hash check, which only walks
      payload→canonical).

The gate is deliberately FAST: it hashes only config templates and ``.py``
payload files — never the 800 MB+ binary bundle.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aipacs_runtime as runtime  # noqa: E402

BUILDER_DIR = PROJECT_ROOT / "builder"
STAGE_DIR = BUILDER_DIR / "output" / "stage"
STAGE_CORE_DIR = STAGE_DIR / "core"
STAGED_PLUGIN_PACKAGE_DIR = STAGE_DIR / "plugin_packages"
MIRROR_VERIFIER_PATH = PROJECT_ROOT / "tools" / "dev" / "verify_plugin_mirrors.py"
EDUCATION_CANONICAL_DIR = PROJECT_ROOT / "modules" / "education"
EDUCATION_MIRROR_PAYLOAD_DIR = (
    BUILDER_DIR / "plugin package" / "packages" / "education"
    / "payload" / "python" / "modules" / "education"
)

# Sentinel symbols that MUST be present in the frozen aipacs_runtime bytecode.
# These are the 2026-06-11 config-migration fixes; a stage whose PYZ lacks them
# was built from a pre-fix source tree (mechanism #1 would ship again).
PYZ_RUNTIME_SENTINELS = (
    "migrate_user_config_defaults",
    "_seed_config_subdirectories",
    "sync_runtime_profile_with_catalog",
    "CONFIG_FAMILY_VERSIONS",
)

# ---------------------------------------------------------------------------
# Shared config-template rules (also imported by the parity tests)
# ---------------------------------------------------------------------------

# Mirrors of the seeding rules in aipacs_runtime (fall back to the documented
# values so the gate still works against an older runtime module).
CONFIG_SEED_SKIP_DIRNAMES = frozenset(
    getattr(runtime, "_CONFIG_SEED_SKIP_DIRNAMES", {"secrets", "__pycache__"})
)
CONFIG_SEED_SKIP_FILENAMES = frozenset(
    getattr(runtime, "_CONFIG_SEED_SKIP_FILENAMES", {".gitignore"})
)

# Explicit, documented exclude list — files under config/ that are deliberately
# NOT seeded into the roaming user config root:
#   installation_profile.json — installer-owned. AIPacs_Setup.iss
#       WriteInstallationProfile() writes the real one to
#       %PROGRAMDATA%\AIPacs\config; the repo copy is only the dev-mode default
#       and seed_user_config_defaults() skips it by name.
# Everything else under config/ (including identity/google_oauth.json — the
# OAuth client template MUST ship) is expected to seed.
CONFIG_TEMPLATE_EXCLUDES = frozenset({"installation_profile.json"})


def iter_seedable_config_templates(repo_root: Path | None = None) -> list[Path]:
    """Relative paths (POSIX-style parts) of every repo config/ file that the
    frozen seeding pipeline (seed_user_config_defaults +
    _seed_config_subdirectories) is expected to deliver to the roaming root."""
    root = (repo_root or PROJECT_ROOT) / "config"
    out: list[Path] = []
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in CONFIG_SEED_SKIP_DIRNAMES for part in rel.parts[:-1]):
            continue
        if rel.name in CONFIG_SEED_SKIP_FILENAMES:
            continue
        if len(rel.parts) == 1 and rel.name in CONFIG_TEMPLATE_EXCLUDES:
            continue
        out.append(rel)
    return out


# ---------------------------------------------------------------------------
# Result plumbing
# ---------------------------------------------------------------------------

@dataclass
class GateCheck:
    name: str
    status: str  # "PASS" | "WARN" | "FAIL"
    details: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status != "FAIL"


def _passed(name: str, *details: str) -> GateCheck:
    return GateCheck(name, "PASS", list(details))


def _warned(name: str, *details: str) -> GateCheck:
    return GateCheck(name, "WARN", list(details))


def _failed(name: str, *details: str) -> GateCheck:
    return GateCheck(name, "FAIL", list(details))


# ---------------------------------------------------------------------------
# PRE-BUILD: source freshness (the "built from a stale checkout" failure mode)
# ---------------------------------------------------------------------------
# 2026-06-16: a release build run on a secondary build PC produced an installer
# whose frozen MPR bytecode predated the v3.2.0 geometry fixes — because that
# clone was parked on an OLD branch (the p2 remote's default 'DR.vahid', v2.2.x)
# while all development lands on beta-version/main. PyInstaller faithfully froze
# the stale source; only the post-stage MPR gate caught it, after a full build.
# This pre-build check fails FAST when the working tree is not current release
# source, so "I changed the code but the build shipped old code" cannot recur
# silently. Deliberately conservative — it FAILS only on unambiguous staleness
# (definitely behind upstream / definitely a non-release branch); anything
# uncertain (no git, no upstream, offline, dirty tree) is a non-blocking WARN.

_DEFAULT_RELEASE_BRANCHES = ("beta-version", "main")


def _sf_env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _release_branches() -> set[str]:
    """Release branch allow-list (override via AIPACS_RELEASE_BRANCHES, a
    comma/semicolon separated list). Empty override disables the branch check."""
    raw = os.environ.get("AIPACS_RELEASE_BRANCHES")
    if raw is not None and raw.strip() == "":
        return set()
    if raw:
        return {b.strip() for b in raw.replace(";", ",").split(",") if b.strip()}
    return set(_DEFAULT_RELEASE_BRANCHES)


def check_source_freshness(repo_root: Path | None = None) -> GateCheck:
    """Fail the build when the working tree is not the current release source.

    Catches the two real "stale source shipped" mechanisms:
      * the checkout is BEHIND its upstream (someone forgot ``git pull``), and
      * the checkout is parked on a non-release branch (e.g. an old ``DR.vahid``
        / ``32bit`` clone on the build PC) while releases live on
        beta-version/main.

    Opt out entirely with ``AIPACS_SKIP_SOURCE_FRESHNESS=1`` (or the build's
    ``--skip-release-gate``). Deliberate off-branch builds: set
    ``AIPACS_ALLOW_OFFBRANCH_BUILD=1`` or ``AIPACS_RELEASE_BRANCHES``. Offline
    builds that should not hit the network: ``AIPACS_SKIP_GIT_FETCH=1``.
    """
    import shutil
    import subprocess

    name = "source_freshness"
    root = repo_root or PROJECT_ROOT

    if _sf_env_flag("AIPACS_SKIP_SOURCE_FRESHNESS"):
        return _warned(name, "skipped via AIPACS_SKIP_SOURCE_FRESHNESS")

    git = shutil.which("git")
    if git is None:
        return _warned(name, "git not on PATH — cannot verify the build source is current")

    def _git(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            [git, "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )

    try:
        inside = _git("rev-parse", "--is-inside-work-tree")
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return _warned(
                name,
                f"{root} is not a git work tree — freshness cannot be verified; "
                "ensure this is the intended, up-to-date release source.",
            )

        head = _git("rev-parse", "HEAD").stdout.strip()
        branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        details = [f"HEAD={head[:10]} branch={branch or '(detached)'}"]

        dirty = [
            ln
            for ln in _git("status", "--porcelain", "--untracked-files=no").stdout.splitlines()
            if ln.strip()
        ]
        if dirty:
            details.append(
                f"working tree has {len(dirty)} uncommitted change(s) — they WILL be "
                "built but are recorded in no commit"
            )

        fetched = False
        if not _sf_env_flag("AIPACS_SKIP_GIT_FETCH"):
            try:
                fetched = _git("fetch", "--quiet", timeout=90.0).returncode == 0
            except Exception:
                fetched = False

        upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        upstream_name = upstream.stdout.strip() if upstream.returncode == 0 else ""
        behind: int | None = None
        if upstream_name:
            rc = _git("rev-list", "--count", "HEAD..@{u}")
            if rc.returncode == 0 and rc.stdout.strip().isdigit():
                behind = int(rc.stdout.strip())

        problems: list[str] = []

        if behind:  # not None and > 0
            msg = (
                f"build tree is {behind} commit(s) BEHIND {upstream_name or 'upstream'} — "
                "run 'git pull' before building (you are about to freeze stale source)."
            )
            if fetched:
                problems.append(msg)
            else:
                details.append("WARN: " + msg + " [upstream ref may be stale: fetch skipped/failed]")

        allowed = _release_branches()
        if (
            allowed
            and branch
            and branch not in allowed
            and not _sf_env_flag("AIPACS_ALLOW_OFFBRANCH_BUILD")
        ):
            problems.append(
                f"current branch '{branch}' is not a release branch {sorted(allowed)} — a "
                "release must build from the release branch (e.g. 'git checkout main && "
                "git pull'). Override a deliberate off-branch build with "
                "AIPACS_ALLOW_OFFBRANCH_BUILD=1, or set AIPACS_RELEASE_BRANCHES."
            )

        if not upstream_name:
            details.append("no upstream tracking branch — 'behind' could not be checked")

        if problems:
            return _failed(name, *(problems + details))
        return _passed(name, *details)
    except Exception as exc:  # pragma: no cover - never let the gate crash the build
        return _warned(name, f"source-freshness check error (non-fatal): {exc}")


# ---------------------------------------------------------------------------
# PRE-BUILD: plugin mirror freshness (mechanism #3)
# ---------------------------------------------------------------------------

def _load_mirror_verifier():
    spec = importlib.util.spec_from_file_location(
        "aipacs_verify_plugin_mirrors", MIRROR_VERIFIER_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {MIRROR_VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the verifier defines @dataclass classes, and
    # dataclasses resolves the defining module via sys.modules at class-creation
    # time (AttributeError on NoneType.__dict__ otherwise, Python 3.13).
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def check_plugin_mirrors() -> GateCheck:
    name = "plugin_mirrors"
    if not MIRROR_VERIFIER_PATH.exists():
        return _failed(name, f"verifier missing: {MIRROR_VERIFIER_PATH}")
    try:
        verifier = _load_mirror_verifier()
        report = verifier.verify_plugin_mirrors(PROJECT_ROOT)
    except Exception as exc:  # pragma: no cover - defensive
        return _failed(name, f"mirror verification crashed: {exc}")
    if report.ok:
        return _passed(
            name,
            f"{len(report.matches)} mirror pair(s) match, "
            f"{len(report.plugin_only)} plugin-only, {report.pairs_checked} checked",
        )
    details = [
        "plugin payload mirrors have DRIFTED from canonical sources — "
        "run: python tools/dev/sync_plugin_mirrors.py  (then re-verify with "
        "python tools/dev/verify_plugin_mirrors.py)"
    ]
    for pair in report.mismatches[:20]:
        details.append(f"  drift: {pair.plugin}: {pair.payload} != {pair.canonical}")
    return _failed(name, *details)


# ---------------------------------------------------------------------------
# POST-STAGE: frozen PYZ probe (generalized from
# "D:\work space AI-Pacs company\tools\verify_frozen_runtime.py")
# ---------------------------------------------------------------------------

def locate_stage_pyz(stage_core: Path) -> Path | None:
    """Find the PYZ for a frozen app root (staged OR installed): a loose *.pyz
    at the top of the engine/_internal dir first, then the PYZ embedded in
    AIPacs.exe's CArchive (extracted to a temp file). Deliberately does NOT
    rglob the whole root — on an installed machine that would scan User Data."""
    search_dirs = [stage_core]
    for layout in ("engine", "Engine", "_internal"):
        candidate = stage_core / layout
        if candidate.is_dir():
            search_dirs.append(candidate)
    for directory in search_dirs:
        pyz = next(iter(directory.glob("PYZ-00.pyz")), None) or next(iter(directory.glob("*.pyz")), None)
        if pyz is not None:
            return pyz
    exe = stage_core / "AIPacs.exe"
    if not exe.exists():
        return None
    from PyInstaller.archive.readers import CArchiveReader

    car = CArchiveReader(str(exe))
    toc = car.toc if isinstance(car.toc, dict) else {
        entry[-2] if len(entry) > 2 else entry[0]: entry for entry in car.toc
    }
    pyz_name = next((n for n in toc if str(n).endswith(".pyz")), None)
    if pyz_name is None:
        return None
    data = car.extract(pyz_name)
    if isinstance(data, tuple):
        data = data[-1]
    tmp = Path(tempfile.mkdtemp(prefix="aipacs_release_gate_")) / "embedded.pyz"
    tmp.write_bytes(data)
    return tmp


def read_frozen_module_code(pyz_path: Path, module_name: str = "aipacs_runtime"):
    """Return the code object for *module_name* from a PYZ archive (or None)."""
    from PyInstaller.archive.readers import ZlibArchiveReader

    arch = ZlibArchiveReader(str(pyz_path))
    names = list(arch.toc.keys()) if isinstance(arch.toc, dict) else [e[0] for e in arch.toc]
    if module_name not in names:
        return None
    code = arch.extract(module_name)
    if isinstance(code, tuple):  # (is_pkg, code) in some PyInstaller versions
        code = code[-1]
    return code


def frozen_catalog_ids(code) -> tuple[set[str] | None, str]:
    """Best extraction of MODULE_CATALOG ids from frozen aipacs_runtime bytecode.

    Primary strategy: exec the module code in a scratch namespace (the module's
    top level only imports stdlib and defines constants/functions — no side
    effects) and read MODULE_CATALOG exactly. Fallback: walk the bytecode's
    string constants and report None for "exact set unavailable" (callers then
    do a subset assertion instead of equality).
    """
    namespace: dict = {"__name__": "aipacs_runtime_frozen_probe", "__file__": "<pyz>"}
    try:
        exec(code, namespace)  # noqa: S102 - our own frozen module, stdlib-only top level
        catalog = namespace.get("MODULE_CATALOG") or []
        return {str(item["id"]) for item in catalog}, "exec"
    except Exception:
        return None, "consts"


def collect_code_symbols(code) -> tuple[set[str], set[str]]:
    """Recursively collect (names, string constants) from a code object."""
    names: set[str] = set()
    strings: set[str] = set()

    def walk(co) -> None:
        names.update(getattr(co, "co_names", ()))
        for const in getattr(co, "co_consts", ()):
            if isinstance(const, str):
                strings.add(const)
            elif hasattr(const, "co_code"):
                names.add(const.co_name)
                walk(const)

    walk(code)
    return names, strings


def check_frozen_runtime(stage_core: Path | None = None) -> GateCheck:
    name = "frozen_runtime_pyz"
    core = stage_core or STAGE_CORE_DIR
    exe = core / "AIPacs.exe"
    if not exe.exists():
        return _failed(name, f"staged executable missing: {exe}")
    try:
        pyz = locate_stage_pyz(core)
    except Exception as exc:
        return _failed(name, f"PYZ extraction failed for {exe}: {exc}")
    if pyz is None:
        return _failed(name, f"no PYZ found on disk or embedded in {exe}")
    try:
        code = read_frozen_module_code(pyz, "aipacs_runtime")
    except Exception as exc:
        return _failed(name, f"PYZ read failed ({pyz}): {exc}")
    if code is None:
        return _failed(name, f"aipacs_runtime not found in frozen PYZ ({pyz})")

    details: list[str] = []
    source_ids = {str(item["id"]) for item in runtime.MODULE_CATALOG}
    frozen_ids, method = frozen_catalog_ids(code)
    names, strings = collect_code_symbols(code)

    if frozen_ids is not None:
        missing = sorted(source_ids - frozen_ids)
        extra = sorted(frozen_ids - source_ids)
        if missing or extra:
            return _failed(
                name,
                "frozen MODULE_CATALOG ids do not match the source catalog — the "
                "staged PYZ is STALE; rebuild (use --clean-build if needed).",
                f"  missing in frozen build: {missing}",
                f"  unexpected in frozen build: {extra}",
            )
        details.append(f"catalog ids match source ({len(frozen_ids)} ids, method={method})")
    else:
        missing = sorted(mid for mid in source_ids if mid not in strings)
        if missing:
            return _failed(
                name,
                "frozen aipacs_runtime is missing catalog id string(s) "
                f"{missing} — the staged PYZ predates the current MODULE_CATALOG; rebuild.",
            )
        details.append(
            f"catalog ids present as constants ({len(source_ids)} ids, "
            "exec probe unavailable — subset check only)"
        )

    sentinel_missing = [
        wanted for wanted in PYZ_RUNTIME_SENTINELS
        if wanted not in names and wanted not in strings
    ]
    if sentinel_missing:
        return _failed(
            name,
            "frozen aipacs_runtime lacks the config-migration sentinels "
            f"{sentinel_missing} — the staged PYZ predates the 2026-06-11 "
            "install-staleness fix; rebuild before shipping.",
        )
    details.append(f"sentinels present: {list(PYZ_RUNTIME_SENTINELS)}")
    return _passed(name, *details)


# ---------------------------------------------------------------------------
# POST-STAGE: config template parity (mechanism #1's shipping precondition)
# ---------------------------------------------------------------------------

def _stage_engine_config_dir(stage_core: Path) -> Path | None:
    for layout in ("engine", "_internal"):
        candidate = stage_core / layout / "config"
        if candidate.is_dir():
            return candidate
    direct = stage_core / "config"
    return direct if direct.is_dir() else None


def check_stage_config_parity(stage_core: Path | None = None) -> GateCheck:
    name = "stage_config_parity"
    core = stage_core or STAGE_CORE_DIR
    staged_config = _stage_engine_config_dir(core)
    if staged_config is None:
        return _failed(name, f"no engine config directory found under {core}")

    import hashlib

    def digest(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    # The staged bundle must carry the SANITIZED template (centre-specific values
    # emptied), NOT the developer's raw config/. Expected bytes are produced by the
    # same function the build uses, so the two can never disagree.
    from builder.config_sanitizer import sanitize_bytes, scan_for_center_values

    def bdigest(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    missing: list[str] = []
    differing: list[str] = []
    templates = iter_seedable_config_templates()
    for rel in templates:
        src = PROJECT_ROOT / "config" / rel
        dst = staged_config / rel
        if not dst.exists():
            missing.append(rel.as_posix())
            continue
        expected = sanitize_bytes(rel.as_posix(), src.read_bytes())
        if bdigest(expected) != digest(dst):
            differing.append(rel.as_posix())

    # A secrets file must NEVER ship inside the bundle.
    leaked_secrets = [
        p.relative_to(staged_config).as_posix()
        for p in staged_config.rglob("*")
        if p.is_file() and "secrets" in p.relative_to(staged_config).parts[:-1]
    ]

    # HARD STOP: no centre-specific value (server IP, API key, OAuth client
    # secret, reception URL, …) may ever reach a client build.
    center_leaks = scan_for_center_values(staged_config)

    if missing or differing or leaked_secrets or center_leaks:
        details = []
        if missing:
            details.append(
                f"templates missing from staged engine config: {missing} — the "
                "frozen build cannot seed them; rebuild so the bundle picks up config/."
            )
        if differing:
            details.append(
                f"staged templates do not match the SANITIZED expectation: {differing} "
                "— the stage is stale or was built from raw config/; rebuild."
            )
        if leaked_secrets:
            details.append(
                f"SECRET files leaked into the staged bundle: {leaked_secrets} — "
                "remove them; secrets/ must never ship."
            )
        if center_leaks:
            details.append(
                "CENTRE-SPECIFIC VALUES WOULD SHIP: "
                + ", ".join(f"{f}:{k} ({why})" for f, k, why in center_leaks)
                + " — extend builder/config_sanitizer.SANITIZE so the production "
                "build seeds empty fields."
            )
        return _failed(name, *details)
    return _passed(
        name,
        f"{len(templates)} config template(s) match the sanitized expectation in "
        f"{staged_config}; no centre-specific values present",
    )


# ---------------------------------------------------------------------------
# POST-STAGE: plugin package staging completeness (mechanism #2's payload side)
# ---------------------------------------------------------------------------

def check_stage_plugin_packages(stage_dir: Path | None = None) -> GateCheck:
    name = "stage_plugin_packages"
    staged_root = (stage_dir or STAGE_DIR) / "plugin_packages"
    if not staged_root.is_dir():
        return _failed(name, f"staged plugin package directory missing: {staged_root}")

    from builder.plugin_package_registry import plugin_package_definition_map

    try:
        definitions = plugin_package_definition_map(optional_only=True)
    except Exception as exc:
        return _failed(name, f"could not load plugin package definitions: {exc}")

    import json

    feed_availability: dict[str, bool] = {}
    feed_path = staged_root / runtime.MODULE_PACKAGE_FEED_FILENAME
    if feed_path.exists():
        try:
            feed = json.loads(feed_path.read_text(encoding="utf-8")) or {}
            for entry in feed.get("packages") or []:
                feed_availability[str(entry.get("module_id") or "")] = bool(entry.get("available"))
        except Exception as exc:
            return _failed(name, f"unreadable staged package feed {feed_path}: {exc}")
    else:
        return _failed(name, f"staged package feed missing: {feed_path}")

    problems: list[str] = []
    warnings: list[str] = []
    for module_id, definition in sorted(definitions.items()):
        package_dir = staged_root / module_id
        manifest = package_dir / runtime.MODULE_PACKAGE_MANIFEST_FILENAME
        conditional = str(definition.get("build_strategy") or "") == "runtime_payload"
        if conditional and not feed_availability.get(module_id, False):
            # advanced_mpr's Slicer runtime is conditionally available; an
            # explicit unavailable feed entry is a deliberate operator choice
            # (AIPACS_ALLOW_MISSING_ADVANCED_MPR) — warn, do not fail.
            warnings.append(
                f"{module_id}: runtime payload marked unavailable in the feed (conditional — OK)"
            )
            continue
        if not package_dir.is_dir():
            problems.append(
                f"{module_id}: staged package directory missing ({package_dir}) — "
                "build_module_packages did not produce it"
            )
            continue
        if not manifest.exists():
            problems.append(f"{module_id}: {runtime.MODULE_PACKAGE_MANIFEST_FILENAME} missing in {package_dir}")
    if problems:
        return _failed(name, *problems)
    if warnings:
        return _warned(name, *warnings)
    return _passed(name, f"all {len(definitions)} optional package(s) staged under {staged_root}")


# ---------------------------------------------------------------------------
# POST-STAGE: education payload file-set parity (mechanism #3 — the case the
# hash verifier cannot see: a NEW canonical file never synced into the mirror)
# ---------------------------------------------------------------------------

def _python_file_set(root: Path) -> set[str]:
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
    }


def check_education_payload_set() -> GateCheck:
    name = "education_payload_set"
    if not EDUCATION_CANONICAL_DIR.is_dir():
        return _failed(name, f"canonical education tree missing: {EDUCATION_CANONICAL_DIR}")
    if not EDUCATION_MIRROR_PAYLOAD_DIR.is_dir():
        return _failed(name, f"education mirror payload missing: {EDUCATION_MIRROR_PAYLOAD_DIR}")
    canonical = _python_file_set(EDUCATION_CANONICAL_DIR)
    mirror = _python_file_set(EDUCATION_MIRROR_PAYLOAD_DIR)
    canonical_only = sorted(canonical - mirror)
    mirror_only = sorted(mirror - canonical)
    if canonical_only or mirror_only:
        return _failed(
            name,
            "education plugin-mirror payload file set differs from modules/education — "
            "run: python tools/dev/sync_plugin_mirrors.py  then rebuild.",
            f"  canonical-only (never synced): {canonical_only}",
            f"  mirror-only (stale leftovers): {mirror_only}",
        )
    return _passed(name, f"{len(canonical)} education .py file(s) mirrored 1:1")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# BINARY ARCHITECTURE SCAN (ARM64 plan §7.3, 2026-07-07)
# ---------------------------------------------------------------------------
# "Do not accidentally install x64-only native DLLs into an ARM64-native
# application" — and vice versa. Reads the PE header machine field of every
# staged .exe/.dll/.pyd and compares against the build's target architecture.
# Called by build_release.py post-stage: ENFORCED for --arch arm64 (a single
# x64 binary in the native tree = broken install), warn-only for x64 unless
# AIPACS_ENFORCE_ARCH_SCAN=1 (established x64 trees may legitimately carry the
# odd x86 helper — establish the baseline before enforcing).

PE_MACHINE_NAMES = {0x014C: "x86", 0x01C4: "ARMNT", 0x8664: "x64", 0xAA64: "arm64"}
_ARCH_TO_MACHINE = {"x64": 0x8664, "arm64": 0xAA64}
_BINARY_SUFFIXES = {".exe", ".dll", ".pyd"}


def read_pe_machine(path: Path) -> int | None:
    """PE header machine value of a Windows binary; None when unreadable."""
    try:
        with open(path, "rb") as fh:
            if fh.read(2) != b"MZ":
                return None
            fh.seek(0x3C)
            pe_off = int.from_bytes(fh.read(4), "little")
            fh.seek(pe_off)
            if fh.read(4) != b"PE\x00\x00":
                return None
            return int.from_bytes(fh.read(2), "little")
    except Exception:
        return None


def check_stage_binary_architecture(
    stage_dir: Path | None = None,
    expected_arch: str = "x64",
    enforce: bool = True,
) -> GateCheck:
    """Every staged native binary must match the target architecture."""
    name = "stage_binary_architecture"
    expected_machine = _ARCH_TO_MACHINE.get(expected_arch)
    if expected_machine is None:
        return _failed(name, f"unknown expected_arch {expected_arch!r}")
    stage = stage_dir or STAGE_DIR
    root = stage / "core" if (stage / "core").exists() else stage
    if not root.exists():
        return _warned(name, f"no staged tree at {root} — nothing to scan")

    scanned = 0
    mismatches: list[str] = []
    unreadable = 0
    for path in root.rglob("*"):
        if path.suffix.lower() not in _BINARY_SUFFIXES or not path.is_file():
            continue
        machine = read_pe_machine(path)
        if machine is None:
            unreadable += 1
            continue
        scanned += 1
        if machine != expected_machine:
            got = PE_MACHINE_NAMES.get(machine, hex(machine))
            mismatches.append(f"{path.relative_to(root)} = {got}")

    if not mismatches:
        return _passed(
            name,
            f"{scanned} binaries scanned under {root} — all {expected_arch}"
            + (f" ({unreadable} unreadable skipped)" if unreadable else ""),
        )
    detail = [
        f"expected {expected_arch}; {len(mismatches)} wrong-architecture binaries "
        f"out of {scanned} scanned under {root}:",
        *mismatches[:20],
    ]
    if len(mismatches) > 20:
        detail.append(f"... and {len(mismatches) - 20} more")
    return _failed(name, *detail) if enforce else _warned(name, *detail)


def run_pre_build_gate() -> list[GateCheck]:
    return [check_source_freshness(), check_plugin_mirrors()]


def run_post_stage_gate(stage_dir: Path | None = None) -> list[GateCheck]:
    stage = stage_dir or STAGE_DIR
    core = stage / "core"
    return [
        check_frozen_runtime(core),
        check_stage_config_parity(core),
        check_stage_plugin_packages(stage),
        check_education_payload_set(),
    ]


def report(checks: list[GateCheck], label: str = "") -> bool:
    """Print per-check lines + the RELEASE_GATE summary; True when no FAIL."""
    for check in checks:
        print(f"[{check.status}] {check.name}")
        for line in check.details:
            print(f"        {line}")
    ok = all(check.ok for check in checks)
    summary = ", ".join(f"{check.name}={check.status}" for check in checks)
    suffix = f" ({label})" if label else ""
    print(f"RELEASE_GATE: {'PASS' if ok else 'FAIL'}{suffix} [{summary}]")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIPacs release gate (see module docstring).")
    parser.add_argument("--pre-build", action="store_true", help="Run only the pre-build checks (mirror freshness).")
    parser.add_argument("--stage-check", action="store_true", help="Run only the post-stage checks against builder/output/stage.")
    parser.add_argument("--stage-dir", default="", help="Override the stage directory (default: builder/output/stage).")
    args = parser.parse_args(argv)

    run_pre = args.pre_build or not args.stage_check
    run_stage = args.stage_check or not args.pre_build
    stage_dir = Path(args.stage_dir) if args.stage_dir else STAGE_DIR

    checks: list[GateCheck] = []
    label_parts: list[str] = []
    if run_pre:
        checks.extend(run_pre_build_gate())
        label_parts.append("pre-build")
    if run_stage:
        if (stage_dir / "core").exists():
            checks.extend(run_post_stage_gate(stage_dir))
            label_parts.append("post-stage")
        else:
            checks.append(_failed("stage_present", f"no stage found at {stage_dir} — build first or pass --stage-dir"))
    ok = report(checks, label=" + ".join(label_parts))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
