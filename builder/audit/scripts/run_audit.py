#!/usr/bin/env python3
"""
Repository build audit for PyInstaller packaging (Windows / onedir).

Generates:
- builder/inventory/*.json
- builder/audit/reports/AUDIT_SUMMARY.md
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import tomllib  # py>=3.11
except Exception:  # pragma: no cover
    tomllib = None


EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".idea",
    ".vscode",
    "node_modules",
    "backups",
    "backup",
    "venv",
    ".venv",
    ".venv_build",
    "dist",
    "build",
    "builder",  # avoid scanning generated builder artifacts/scripts
}

RESOURCE_EXTENSIONS = {
    ".ui",
    ".qss",
    ".qrc",
    ".json",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".conf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".svg",
    ".ico",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".scss",
    ".css",
    ".glsl",
    ".vert",
    ".frag",
    ".stl",
    ".obj",
    ".mtl",
    ".txt",
}

RUNTIME_DATA_EXTENSIONS = {".db", ".sqlite", ".sqlite3", ".log", ".dcm", ".dicom", ".bak"}

SUSPICIOUS_DATA_DIR_KEYWORDS = (
    "cache",
    "download",
    "dicom",
    "thumbnail",
    "attachment",
    "log",
    "database",
    "generated-files",
    "temp",
    "tmp",
    "output",
    "report",
)

IMPORT_TO_PACKAGE_HINT = {
    "PySide6": "PySide6",
    "vtk": "vtk",
    "vtkmodules": "vtk",
    "SimpleITK": "SimpleITK",
    "pydicom": "pydicom",
    "pynetdicom": "pynetdicom",
    "grpc": "grpcio",
    "qasync": "qasync",
    "numpy": "numpy",
    "pandas": "pandas",
    "openai": "openai",
    "dotenv": "python-dotenv",
    "python_dotenv": "python-dotenv",
    "qtawesome": "QtAwesome",
    "comtypes": "comtypes",
    "sounddevice": "sounddevice",
    "soundfile": "soundfile",
    "SpeechRecognition": "SpeechRecognition",
    "pyaudio": "pyaudio",
    "webrtcvad": "webrtcvad",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return path.read_text(encoding="latin-1", errors="replace")


def safe_json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def repo_rel(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except Exception:
        return path.as_posix()


def _excluded_names_lower() -> set[str]:
    return {x.lower() for x in EXCLUDED_DIR_NAMES}


def iter_files(repo_root: Path) -> Iterable[Path]:
    excluded = _excluded_names_lower()
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d.lower() not in excluded]
        root_path = Path(root)
        for name in files:
            yield root_path / name


def iter_python_files(repo_root: Path) -> Iterable[Path]:
    for p in iter_files(repo_root):
        if p.suffix.lower() == ".py":
            yield p


@dataclass
class PythonFileScan:
    path: str
    imports: set[str] = field(default_factory=set)
    top_level_imports: set[str] = field(default_factory=set)
    pyside6_submodules: set[str] = field(default_factory=set)
    vtk_submodules: set[str] = field(default_factory=set)
    dynamic_risk_patterns: set[str] = field(default_factory=set)
    dynamic_literal_imports: set[str] = field(default_factory=set)
    has_qapplication: bool = False
    has_qcore_app: bool = False
    has_main_guard: bool = False
    has_exec_call: bool = False
    has_argparse_main: bool = False
    has_freeze_support: bool = False
    mentions_slicer: bool = False
    mentions_aipacs_advanced_viewer_exe: bool = False
    errors: list[str] = field(default_factory=list)


def get_call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = get_call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def parse_python_file(path: Path, repo_root: Path) -> tuple[PythonFileScan, list[dict[str, Any]], set[str]]:
    text = read_text(path)
    rel = repo_rel(path, repo_root)
    fs = PythonFileScan(path=rel)
    findings: list[dict[str, Any]] = []
    env_var_refs: set[str] = set()

    fs.has_qapplication = bool(re.search(r"\bQApplication\s*\(", text))
    fs.has_qcore_app = bool(re.search(r"\bQ(Core|Gui)Application\s*\(", text))
    fs.has_main_guard = "__name__" in text and "__main__" in text
    fs.has_exec_call = bool(re.search(r"\.exec\s*\(", text))
    fs.has_argparse_main = "argparse.ArgumentParser" in text
    fs.has_freeze_support = "freeze_support" in text
    fs.mentions_slicer = "slicer" in rel.lower() or "3d slicer" in text.lower()
    fs.mentions_aipacs_advanced_viewer_exe = "AIPacsAdvancedViewer.exe" in text

    for label, pattern in [
        ("importlib.import_module", r"\bimportlib\.import_module\s*\("),
        ("__import__", r"\b__import__\s*\("),
        ("pkgutil.iter_modules", r"\bpkgutil\.iter_modules\s*\("),
        ("exec", r"(?<!\.)\bexec\s*\("),
        ("eval", r"(?<!\.)\beval\s*\("),
        ("spec_from_file_location", r"\bimportlib\.util\.spec_from_file_location\s*\("),
    ]:
        if re.search(pattern, text):
            fs.dynamic_risk_patterns.add(label)

    for pat in [
        re.compile(r"os\.getenv\(\s*['\"]([A-Z0-9_]+)['\"]\s*\)"),
        re.compile(r"os\.environ\.get\(\s*['\"]([A-Z0-9_]+)['\"]\s*\)"),
        re.compile(r"os\.environ\[\s*['\"]([A-Z0-9_]+)['\"]\s*\]"),
    ]:
        for m in pat.finditer(text):
            env_var_refs.add(m.group(1))

    runtime_rules = [
        ("sqlite_usage", re.compile(r"\bsqlite3\.connect\s*\(")),
        ("db_file_ref", re.compile(r"\.(sqlite|sqlite3|db)\b", re.IGNORECASE)),
        ("mkdir", re.compile(r"\.(mkdir|makedirs)\s*\(")),
        ("open_write", re.compile(r"\bopen\s*\([^)]*,\s*['\"][wa]\+?['\"]")),
        ("tempfile", re.compile(r"\btempfile\.")),
        ("cwd_usage", re.compile(r"\bos\.getcwd\s*\(")),
        ("qstandardpaths", re.compile(r"\bQStandardPaths\b")),
        ("path_home", re.compile(r"\bPath\.home\s*\(")),
        ("appdata_ref", re.compile(r"\b(APPDATA|LOCALAPPDATA)\b")),
        ("log_usage", re.compile(r"\blogging\b|\b\.log\b", re.IGNORECASE)),
        ("dicom_storage", re.compile(r"\bdicom\b", re.IGNORECASE)),
        ("cache_usage", re.compile(r"\bcache\b", re.IGNORECASE)),
        ("attachment_usage", re.compile(r"\battachment(s)?\b", re.IGNORECASE)),
        ("download_usage", re.compile(r"\bdownload(s|er)?\b", re.IGNORECASE)),
        ("dotenv_usage", re.compile(r"\b(load_dotenv|dotenv|\.env)\b", re.IGNORECASE)),
        ("openai_usage", re.compile(r"\bopenai\b|\bOPENAI_API_KEY\b", re.IGNORECASE)),
        ("token_usage", re.compile(r"\btoken\b|\bapi[_-]?key\b", re.IGNORECASE)),
        ("subprocess_exe", re.compile(r"\bsubprocess\.(run|Popen)\b|\.exe\b", re.IGNORECASE)),
    ]
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        for category, pat in runtime_rules:
            if pat.search(line):
                findings.append(
                    {
                        "path": rel,
                        "line": lineno,
                        "category": category,
                        "snippet": stripped[:300],
                    }
                )

    try:
        tree = ast.parse(text, filename=str(path))
    except Exception as exc:
        fs.errors.append(f"AST parse failed: {exc}")
        return fs, findings, env_var_refs

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name:
                    fs.imports.add(name)
                    fs.top_level_imports.add(name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                fs.imports.add(node.module)
                fs.top_level_imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            call_name = get_call_name(node.func) or ""
            if call_name in {"importlib.import_module", "__import__"}:
                fs.dynamic_risk_patterns.add(call_name)
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    fs.dynamic_literal_imports.add(node.args[0].value)
            elif call_name.startswith("pkgutil."):
                fs.dynamic_risk_patterns.add(call_name)
            elif call_name in {"exec", "eval"}:
                fs.dynamic_risk_patterns.add(call_name)
            elif call_name == "importlib.util.spec_from_file_location":
                fs.dynamic_risk_patterns.add(call_name)

    for imp in fs.imports:
        if imp.startswith("PySide6."):
            fs.pyside6_submodules.add(imp)
        if imp.startswith("vtkmodules."):
            fs.vtk_submodules.add(imp)

    return fs, findings, env_var_refs


def detect_entrypoints(file_scans: list[PythonFileScan]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for fs in file_scans:
        p = fs.path.lower()
        name = Path(fs.path).name.lower()
        score = 0
        reasons: list[str] = []
        if name in {"main.py", "app.py", "__main__.py"}:
            score += 5
            reasons.append(f"candidate filename {name}")
        if name.startswith("run") and name.endswith(".py"):
            score += 2
            reasons.append("run*.py candidate")
        if "launch" in name and "slicer" in name:
            score += 6
            reasons.append("slicer launch filename")
        if fs.has_main_guard:
            score += 3
            reasons.append("__main__ guard")
        if fs.has_qapplication:
            score += 8
            reasons.append("QApplication creation")
        elif fs.has_qcore_app:
            score += 4
            reasons.append("Qt application creation")
        if fs.has_exec_call and (fs.has_qapplication or fs.has_qcore_app):
            score += 4
            reasons.append("Qt app exec() call")
        if fs.has_argparse_main:
            score += 2
            reasons.append("argparse CLI")
        if fs.has_freeze_support:
            score += 3
            reasons.append("freeze_support")
        if fs.mentions_slicer:
            score += 5
            reasons.append("slicer content/path")
        if fs.mentions_aipacs_advanced_viewer_exe:
            score += 6
            reasons.append("AIPacsAdvancedViewer.exe reference")
        if p == "main.py":
            score += 4
            reasons.append("repo root main.py")
        if "test" in p:
            score -= 5
            reasons.append("test penalty")
        candidates.append(
            {
                "path": fs.path,
                "score": score,
                "reasons": reasons,
                "has_qapplication": fs.has_qapplication,
                "has_main_guard": fs.has_main_guard,
                "mentions_slicer": fs.mentions_slicer,
            }
        )

    app_a_candidates = sorted(
        [c for c in candidates if not c["mentions_slicer"] and c["has_main_guard"]],
        key=lambda c: (c["has_qapplication"], c["score"]),
        reverse=True,
    )
    app_b_candidates = sorted(
        [c for c in candidates if c["mentions_slicer"] and c["has_main_guard"]],
        key=lambda c: c["score"],
        reverse=True,
    )

    def format_app(key: str, picked: dict[str, Any] | None) -> dict[str, Any]:
        if not picked:
            return {"name": None, "entrypoint": None, "how_detected": "No candidate found"}
        if key == "appA":
            name = "AIPacs"
        else:
            name = "AIPacsAdvancedViewerLauncher"
            if picked["path"].endswith("slicer_launcher.py"):
                name = "AIPacsSlicerLauncherModule"
        return {
            "name": name,
            "entrypoint": picked["path"],
            "how_detected": f"score={picked['score']}; " + "; ".join(picked["reasons"]),
        }

    return {
        "appA": format_app("appA", app_a_candidates[0] if app_a_candidates else None),
        "appB": format_app("appB", app_b_candidates[0] if app_b_candidates else None),
        "candidates": sorted(candidates, key=lambda c: c["score"], reverse=True)[:25],
        "generated_at_utc": now_utc_iso(),
    }


def build_imports_summary(file_scans: list[PythonFileScan]) -> dict[str, Any]:
    full_counts: Counter[str] = Counter()
    top_counts: Counter[str] = Counter()
    unique_imports: set[str] = set()
    pyside6_submodules: set[str] = set()
    vtk_submodules: set[str] = set()
    dynamic_literal_imports: set[str] = set()
    dynamic_risk_files: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []

    for fs in file_scans:
        for imp in fs.imports:
            unique_imports.add(imp)
            full_counts[imp] += 1
        for root in fs.top_level_imports:
            top_counts[root] += 1
        pyside6_submodules.update(fs.pyside6_submodules)
        vtk_submodules.update(fs.vtk_submodules)
        dynamic_literal_imports.update(fs.dynamic_literal_imports)
        if fs.dynamic_risk_patterns:
            dynamic_risk_files.append({"path": fs.path, "patterns": sorted(fs.dynamic_risk_patterns)})
        for err in fs.errors:
            parse_errors.append({"path": fs.path, "error": err})

    suggested_hiddenimports: set[str] = set()
    suggested_hiddenimports.update(pyside6_submodules)
    suggested_hiddenimports.update(vtk_submodules)
    if any(x == "SimpleITK" or x.startswith("SimpleITK.") for x in unique_imports):
        suggested_hiddenimports.update({"SimpleITK", "SimpleITK._SimpleITK"})
    if any(x == "vtkmodules" or x.startswith("vtkmodules.") for x in unique_imports):
        suggested_hiddenimports.update({"vtkmodules", "vtkmodules.util", "vtkmodules.util.numpy_support"})
    for x in dynamic_literal_imports:
        if x and not x.startswith("."):
            suggested_hiddenimports.add(x)

    pyside_webengine = any(
        m.startswith("PySide6.QtWebEngine") or m.startswith("PySide6.QtWebChannel")
        for m in pyside6_submodules
    )

    return {
        "generated_at_utc": now_utc_iso(),
        "scanned_python_files": len(file_scans),
        "unique_imports": sorted(unique_imports),
        "per_module_counts": dict(top_counts.most_common()),
        "full_import_counts": dict(full_counts.most_common()),
        "special_modules": {
            "pyside6_detected": "PySide6" in top_counts,
            "pyside6_submodules": sorted(pyside6_submodules),
            "pyside6_webengine_detected": pyside_webengine,
            "vtk_detected": "vtk" in top_counts or "vtkmodules" in top_counts,
            "vtkmodules_submodules": sorted(vtk_submodules),
            "simpleitk_detected": "SimpleITK" in top_counts,
            "multiprocessing_detected": "multiprocessing" in top_counts,
        },
        "dynamic_import_risks": {
            "count": len(dynamic_risk_files),
            "files": sorted(dynamic_risk_files, key=lambda x: x["path"]),
            "requires_hiddenimports_review": len(dynamic_risk_files) > 0,
        },
        "dynamic_literal_imports": sorted(dynamic_literal_imports),
        "suggested_hiddenimports": sorted(suggested_hiddenimports),
        "parse_errors": parse_errors,
    }


def parse_requirements_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    deps: list[str] = []
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        deps.append(line)
    return deps


def parse_pyproject_dependencies(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "dependencies": [], "optional_dependencies": {}}
    result: dict[str, Any] = {"exists": True, "dependencies": [], "optional_dependencies": {}}
    if tomllib is None:
        result["error"] = "tomllib unavailable (Python 3.11+ required)"
        return result
    try:
        data = tomllib.loads(read_text(path))
        project = data.get("project", {})
        result["dependencies"] = project.get("dependencies", []) or []
        result["optional_dependencies"] = project.get("optional-dependencies", {}) or {}
    except Exception as exc:
        result["error"] = str(exc)
    return result


def run_pip_freeze_if_controlled() -> dict[str, Any]:
    venv = os.environ.get("VIRTUAL_ENV", "")
    info: dict[str, Any] = {
        "attempted": False,
        "ran": False,
        "controlled_venv": False,
        "venv_path": venv or None,
        "pip_freeze": [],
    }
    if not venv:
        info["reason"] = "No active venv; skipped by policy (only run in .venv_build)"
        return info
    if Path(venv).name.lower() != ".venv_build":
        info["reason"] = "Active venv is not .venv_build; skipped by policy"
        return info
    info["controlled_venv"] = True
    info["attempted"] = True
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        info["returncode"] = proc.returncode
        info["pip_freeze"] = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        if proc.stderr:
            info["stderr"] = proc.stderr[-4000:]
        info["ran"] = proc.returncode == 0
        if not info["ran"]:
            info["reason"] = "pip freeze returned non-zero"
    except Exception as exc:
        info["error"] = str(exc)
        info["traceback"] = traceback.format_exc(limit=2)
    return info


def infer_packages_from_imports(top_counts: Counter[str]) -> list[dict[str, Any]]:
    inferred: list[dict[str, Any]] = []
    for module, count in top_counts.most_common():
        pkg_hint = IMPORT_TO_PACKAGE_HINT.get(module)
        if pkg_hint:
            inferred.append({"import_root": module, "package_hint": pkg_hint, "count": count})
    return inferred


def recommended_pin_placeholders(requirements_txt: list[str], inferred_deps: list[dict[str, Any]]) -> list[dict[str, str]]:
    req_map: dict[str, str] = {}
    for dep in requirements_txt:
        key = re.split(r"[<>=!~\[]", dep, maxsplit=1)[0].strip().lower()
        if key:
            req_map[key] = dep
    core = ["PyInstaller", "pyinstaller-hooks-contrib", "PySide6", "vtk", "SimpleITK", "qasync", "numpy"]
    for d in inferred_deps:
        core.append(d["package_hint"])
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for pkg in core:
        key = pkg.lower()
        if key in seen:
            continue
        seen.add(key)
        declared = req_map.get(key)
        if declared:
            rec = declared if "==" in declared else f"{pkg}==<pin-me>"
        else:
            rec = f"{pkg}==<pin-me>"
        out.append({"package": pkg, "recommended": rec})
    return out


def build_dependency_tree_json(repo_root: Path, imports_summary: dict[str, Any]) -> dict[str, Any]:
    requirements_txt = parse_requirements_file(repo_root / "requirements.txt")
    pyproject = parse_pyproject_dependencies(repo_root / "pyproject.toml")
    top_counts = Counter(imports_summary.get("per_module_counts", {}))
    inferred = infer_packages_from_imports(top_counts)
    freeze_info = run_pip_freeze_if_controlled()
    return {
        "generated_at_utc": now_utc_iso(),
        "declared_dependencies": {
            "requirements_txt_exists": (repo_root / "requirements.txt").exists(),
            "requirements_txt": requirements_txt,
            "pyproject_toml": pyproject,
        },
        "inferred_dependencies_from_imports": inferred,
        "environment_dependencies": freeze_info,
        "recommended_pinned_versions": recommended_pin_placeholders(requirements_txt, inferred),
        "notes": [
            "Re-run audit in .venv_build after installing dependencies to capture accurate pip freeze.",
            "Validate PySide6/VTK/SimpleITK compatibility before pinning build toolchain.",
        ],
    }


def summarize_resource_inventory(repo_root: Path) -> dict[str, Any]:
    counts_by_ext: Counter[str] = Counter()
    top_dirs: Counter[str] = Counter()
    files_by_category: dict[str, list[str]] = defaultdict(list)
    ui_dirs: set[str] = set()
    qss_dirs: set[str] = set()
    qrc_dirs: set[str] = set()
    config_dirs: set[str] = set()

    for path in iter_files(repo_root):
        suffix = path.suffix.lower()
        if suffix not in RESOURCE_EXTENSIONS:
            continue
        rel = repo_rel(path, repo_root)
        counts_by_ext[suffix] += 1
        top_dirs[rel.split("/", 1)[0]] += 1

        if suffix == ".ui":
            files_by_category["ui_files"].append(rel)
            ui_dirs.add(str(Path(rel).parent).replace("\\", "/"))
        elif suffix in {".qss", ".scss", ".css"}:
            files_by_category["stylesheets"].append(rel)
            qss_dirs.add(str(Path(rel).parent).replace("\\", "/"))
        elif suffix == ".qrc":
            files_by_category["qt_resource_collections"].append(rel)
            qrc_dirs.add(str(Path(rel).parent).replace("\\", "/"))
        elif suffix in {".json", ".yaml", ".yml", ".ini", ".cfg", ".conf"}:
            if len(files_by_category["config_like"]) < 1000:
                files_by_category["config_like"].append(rel)
            config_dirs.add(str(Path(rel).parent).replace("\\", "/"))
        elif suffix in {".ttf", ".otf", ".woff", ".woff2"}:
            files_by_category["fonts"].append(rel)
        elif suffix in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".svg", ".ico"}:
            if len(files_by_category["images_sample"]) < 300:
                files_by_category["images_sample"].append(rel)
        else:
            if len(files_by_category["other_resource_files_sample"]) < 200:
                files_by_category["other_resource_files_sample"].append(rel)

    likely_roots: list[dict[str, Any]] = []
    runtime_like_top_dirs = {"education", "attachment", "thumbnails", "database", "generated-files", "logs", "output"}

    def candidate_allowed(rel_path: str) -> bool:
        norm = rel_path.replace("\\", "/").strip()
        if not norm or norm == ".":
            return False
        top = norm.split("/", 1)[0].lower()
        if top in runtime_like_top_dirs:
            return False
        lower = norm.lower()
        if any(k in lower for k in ("generated-files", "attachment/", "thumbnails/", "database/reception_reports")):
            return False
        return True
    candidates = [
        ("Qss", "Global UI styles, icons, and images"),
        ("Fonts", "Fonts loaded at runtime"),
        ("education_assets", "Bundled educational thumbnails/assets (non-runtime static assets)"),
        ("json-styles", "JSON stylesheet resources"),
        ("config", "Configuration templates/defaults (filter secrets/local overrides)"),
        ("modules/cd_burner/assets", "CD burner assets"),
        ("modules/mpr/advanced_3d_slicer/slicer_custom_app/branding", "Slicer launcher branding assets"),
        ("modules/mpr/advanced_3d_slicer/slicer_custom_app/docs", "Slicer launcher docs/contract"),
    ]
    for rel in sorted(ui_dirs | qss_dirs | qrc_dirs):
        candidates.append((rel, "Detected UI/QSS/QRC directory"))
    # config-like directories are only kept if they look like static app config, not runtime data
    for rel in sorted(config_dirs):
        if rel.split("/", 1)[0].lower() in {"config", "json-styles", "echomind", "pacsclient"}:
            candidates.append((rel, "Detected config-like directory"))

    seen = set()
    for rel, reason in candidates:
        norm = rel.replace("\\", "/")
        if norm in seen:
            continue
        seen.add(norm)
        p = repo_root / norm
        if not candidate_allowed(norm):
            continue
        if not p.exists():
            continue
        if p.is_dir():
            file_count = sum(1 for x in p.rglob("*") if x.is_file())
            likely_roots.append({"path": norm, "type": "dir", "file_count": file_count, "reason": reason})
        else:
            likely_roots.append({"path": norm, "type": "file", "file_count": 1, "reason": reason})

    return {
        "generated_at_utc": now_utc_iso(),
        "counts_by_extension": dict(counts_by_ext.most_common()),
        "top_level_resource_directories": dict(top_dirs.most_common(50)),
        "files_by_category": {k: sorted(v) for k, v in files_by_category.items()},
        "likely_package_data_paths": sorted(likely_roots, key=lambda x: x["path"]),
    }


def scan_runtime_paths_and_privacy(repo_root: Path, runtime_findings: list[dict[str, Any]], env_var_refs: set[str]) -> dict[str, Any]:
    path_var_hits: list[dict[str, Any]] = []
    secrets_hits: list[dict[str, Any]] = []
    env_files: list[str] = []
    existing_sensitive_artifacts: list[dict[str, Any]] = []
    must_not_package_paths: set[str] = set()
    sensitive_bucket_counts: Counter[str] = Counter()

    path_assign_re = re.compile(r"(?P<var>[A-Z][A-Z0-9_]*_PATH)\s*=\s*(?P<expr>.+)")
    secret_re = re.compile(r"(\.env\b|load_dotenv|OPENAI_API_KEY|api[_-]?key|token|Authorization)", re.IGNORECASE)

    for py_path in iter_python_files(repo_root):
        rel = repo_rel(py_path, repo_root)
        text = read_text(py_path)
        for lineno, line in enumerate(text.splitlines(), start=1):
            m = path_assign_re.search(line)
            if m:
                expr = m.group("expr").strip()
                if "Path(" in expr or "BASE_PATH" in expr or any(k in expr.lower() for k in SUSPICIOUS_DATA_DIR_KEYWORDS):
                    path_var_hits.append(
                        {"path": rel, "line": lineno, "variable": m.group("var"), "expression": expr[:400]}
                    )
            if secret_re.search(line):
                secrets_hits.append({"path": rel, "line": lineno, "snippet": line.strip()[:300]})

    for path in iter_files(repo_root):
        rel = repo_rel(path, repo_root)
        lname = path.name.lower()
        lower_rel = rel.lower()

        if lname.startswith(".env"):
            env_files.append(rel)
            must_not_package_paths.add(rel)

        if path.is_file() and path.suffix.lower() in RUNTIME_DATA_EXTENSIONS:
            reason = f"runtime-like extension {path.suffix.lower()}"
            if len(existing_sensitive_artifacts) < 2000:
                existing_sensitive_artifacts.append({"path": rel, "type": "file", "reason": reason})
            top = rel.split("/", 1)[0]
            sensitive_bucket_counts[f"top:{top}"] += 1
            sensitive_bucket_counts[f"ext:{path.suffix.lower()}"] += 1
            # Prefer directory/pattern exclusions over enumerating every file.
            if path.suffix.lower() in {".dcm", ".dicom"}:
                top_lower = top.lower()
                parent_glob = f"{Path(rel).parent.as_posix()}/**"
                if top_lower in {"education", "source", "thumbnails", "attachment", "generated-files", "database", "segments"}:
                    must_not_package_paths.add(f"{top}/**")
                elif any(seg in rel.lower() for seg in ("cache", "dicom", "download", "thumbnail", "attachment", "source/")):
                    must_not_package_paths.add(parent_glob)
                else:
                    # Avoid over-broad exclusions such as PacsClient/**; keep exact file path if uncertain.
                    must_not_package_paths.add(rel)
            else:
                must_not_package_paths.add(rel)

        parts_lower = [p.lower() for p in Path(rel).parts]
        has_runtime_dir_segment = any(p in {"generated-files", "thumbnails", "attachment", "attachments", "logs", "log"} for p in parts_lower)
        has_reception_reports = "database" in parts_lower and "reception_reports" in parts_lower
        if path.is_file() and (has_runtime_dir_segment or has_reception_reports):
            if len(existing_sensitive_artifacts) < 2000:
                existing_sensitive_artifacts.append(
                    {"path": rel, "type": "file", "reason": "runtime/generated/user-data-like location"}
                )
            sensitive_bucket_counts[f"top:{rel.split('/',1)[0]}"] += 1
            parts = rel.split("/")
            keyword_indices = [i for i, part in enumerate(parts[:-1]) if part.lower() in {"database", "generated-files", "thumbnails", "attachment", "attachments", "logs", "log"}]
            if keyword_indices:
                idx = keyword_indices[0]
                must_not_package_paths.add("/".join(parts[: idx + 1]) + "/**")
            else:
                must_not_package_paths.add(f"{rel.split('/',1)[0]}/**")

    for top in ("database", "generated-files", "thumbnails", "attachment", "logs", "output", "Education", "source", "Segments"):
        if (repo_root / top).exists():
            must_not_package_paths.add(top)

    runtime_counts = Counter(item["category"] for item in runtime_findings)
    runtime_sample = sorted(runtime_findings, key=lambda x: (x["path"], x["line"]))[:500]

    return {
        "generated_at_utc": now_utc_iso(),
        "runtime_data_risk_findings_count_by_category": dict(runtime_counts.most_common()),
        "runtime_data_risk_findings_sample": runtime_sample,
        "path_variable_definitions": sorted(path_var_hits, key=lambda x: (x["path"], x["line"]))[:500],
        "existing_sensitive_artifacts": sorted(existing_sensitive_artifacts, key=lambda x: x["path"])[:2000],
        "sensitive_artifact_buckets": dict(sensitive_bucket_counts.most_common(100)),
        "must_not_package_detected_paths": sorted(must_not_package_paths),
        "must_not_package_patterns": [
            "Education/**",
            "database/**",
            "generated-files/**",
            "thumbnails/**",
            "attachment/**",
            "downloads/**",
            "cache/**",
            "logs/**",
            "**/*.db",
            "**/*.sqlite",
            "**/*.sqlite3",
            "**/*.log",
            "**/*.dcm",
            "**/*.dicom",
            "**/.env",
            "**/.env.*",
        ],
        "secrets_and_config_scan": {
            "env_files_found": sorted(set(env_files)),
            "env_var_refs_in_code": sorted(env_var_refs),
            "sensitive_lines_sample": sorted(secrets_hits, key=lambda x: (x["path"], x["line"]))[:400],
            "notes": [
                "Do not include .env files in datas.",
                "Load secrets from environment variables or external config under LocalAppData.",
            ],
        },
        "recommended_runtime_storage": {
            "windows_localappdata_root": r"%LOCALAPPDATA%\\AIPacs",
            "suggested_subdirs": [
                "cache",
                "downloads",
                "dicom",
                "thumbnails",
                "attachments",
                "logs",
                "db",
                "tmp",
                "education",
                "slicer-launcher",
            ],
            "qt_recommendation": "Use QStandardPaths.AppLocalDataLocation / GenericCacheLocation rather than writing into dist/ or project root.",
        },
    }


def scan_repo_binaries_and_external_refs(repo_root: Path) -> dict[str, Any]:
    repo_binaries: list[dict[str, Any]] = []
    exe_refs: Counter[str] = Counter()
    subprocess_files: list[str] = []
    exe_literal_re = re.compile(r"['\"]([^'\"]+?\.exe)['\"]", re.IGNORECASE)
    subprocess_re = re.compile(r"\bsubprocess\.(run|Popen|call|check_call|check_output)\b")

    for path in iter_files(repo_root):
        rel = repo_rel(path, repo_root)
        suffix = path.suffix.lower()
        if suffix in {".dll", ".pyd", ".exe"}:
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = None
            repo_binaries.append({"path": rel, "suffix": suffix, "size_bytes": size_bytes})
        if suffix == ".py":
            text = read_text(path)
            if subprocess_re.search(text):
                subprocess_files.append(rel)
            for m in exe_literal_re.finditer(text):
                exe_refs[m.group(1)] += 1

    return {
        "generated_at_utc": now_utc_iso(),
        "repo_local_binaries": sorted(repo_binaries, key=lambda x: x["path"]),
        "repo_local_binaries_count": len(repo_binaries),
        "external_binaries_referenced_in_code": [
            {"literal": literal, "count": count} for literal, count in exe_refs.most_common()
        ],
        "subprocess_usage_files_sample": sorted(subprocess_files)[:500],
    }


def _scan_package_binaries(pkg_name: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "package": pkg_name,
        "available": False,
        "package_dir": None,
        "dll_count": 0,
        "pyd_count": 0,
        "dlls": [],
        "pyds": [],
        "errors": [],
    }
    try:
        import importlib.util

        spec = importlib.util.find_spec(pkg_name)
        if spec is None:
            result["errors"].append("Module spec not found")
            return result
        if spec.submodule_search_locations:
            base_dir = Path(next(iter(spec.submodule_search_locations)))
        elif spec.origin:
            origin_path = Path(spec.origin).resolve()
            # Single-file modules (e.g. vtk.py wrapper) should not trigger a recursive
            # scan of the entire site-packages directory.
            if origin_path.is_file():
                result["available"] = True
                result["package_dir"] = str(origin_path.parent)
                result["module_file"] = str(origin_path)
                result["scan_mode"] = "single_file_module_no_recursive_scan"
                return result
            base_dir = origin_path.parent
        else:
            result["errors"].append("No package path in spec")
            return result
        if not base_dir.exists():
            result["errors"].append("Package dir does not exist")
            return result

        result["available"] = True
        result["package_dir"] = str(base_dir)
        dlls: list[str] = []
        pyds: list[str] = []
        for item in base_dir.rglob("*"):
            if not item.is_file():
                continue
            if item.suffix.lower() == ".dll":
                dlls.append(str(item))
            elif item.suffix.lower() == ".pyd":
                pyds.append(str(item))
        result["dll_count"] = len(dlls)
        result["pyd_count"] = len(pyds)
        result["dlls"] = dlls[:500]
        result["pyds"] = pyds[:500]
    except Exception as exc:
        result["errors"].append(str(exc))
    return result


def collect_runtime_binary_inventory(imports_summary: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    dll_inventory: dict[str, Any] = {
        "generated_at_utc": now_utc_iso(),
        "environment_package_binaries": {},
    }
    qt_plugins_inventory: dict[str, Any] = {
        "generated_at_utc": now_utc_iso(),
        "available": False,
        "pyside6_detected_in_imports": imports_summary.get("special_modules", {}).get("pyside6_detected", False),
        "pyside6_webengine_detected_in_imports": imports_summary.get("special_modules", {}).get("pyside6_webengine_detected", False),
    }

    for pkg in ("vtkmodules", "SimpleITK", "vtk"):
        dll_inventory["environment_package_binaries"][pkg] = _scan_package_binaries(pkg)

    try:
        from PySide6.QtCore import QLibraryInfo

        plugin_path = None
        qml_path = None
        if hasattr(QLibraryInfo, "path"):
            plugin_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
            try:
                qml_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath)
            except Exception:
                qml_path = None
        elif hasattr(QLibraryInfo, "location"):
            plugin_path = QLibraryInfo.location(QLibraryInfo.PluginsPath)  # type: ignore[attr-defined]
            try:
                qml_path = QLibraryInfo.location(QLibraryInfo.QmlImportsPath)  # type: ignore[attr-defined]
            except Exception:
                qml_path = None

        qt_plugins_inventory["available"] = True
        qt_plugins_inventory["qt_plugins_path"] = plugin_path
        qt_plugins_inventory["qt_qml_path"] = qml_path

        if plugin_path:
            plugin_dir = Path(plugin_path)
            qt_plugins_inventory["qt_plugins_path_exists"] = plugin_dir.exists()
            if plugin_dir.exists():
                subdir_counts: dict[str, int] = {}
                important = [
                    "platforms",
                    "imageformats",
                    "styles",
                    "iconengines",
                    "tls",
                    "networkinformation",
                    "multimedia",
                    "printsupport",
                    "sqldrivers",
                    "webenginecore",
                    "webview",
                ]
                for d in sorted([p for p in plugin_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
                    subdir_counts[d.name] = sum(1 for x in d.rglob("*") if x.is_file())
                qt_plugins_inventory["plugin_subdir_file_counts"] = subdir_counts
                qt_plugins_inventory["important_plugin_subdirs_present"] = {k: (plugin_dir / k).exists() for k in important}
                samples: dict[str, list[str]] = {}
                for k in important:
                    d = plugin_dir / k
                    if d.exists():
                        samples[k] = [str(x) for x in d.rglob("*") if x.is_file()][:50]
                qt_plugins_inventory["important_plugin_files_sample"] = samples

        if qml_path:
            qml_dir = Path(qml_path)
            qt_plugins_inventory["qt_qml_path_exists"] = qml_dir.exists()
            if qml_dir.exists():
                qt_plugins_inventory["qml_top_level_modules_sample"] = sorted([d.name for d in qml_dir.iterdir() if d.is_dir()])[:200]
    except Exception as exc:
        qt_plugins_inventory["errors"] = [str(exc)]

    return dll_inventory, qt_plugins_inventory


def derive_high_risk_items(imports_summary: dict[str, Any], runtime_inventory: dict[str, Any], qt_plugins_inventory: dict[str, Any]) -> list[str]:
    special = imports_summary.get("special_modules", {})
    risks: list[str] = []
    if special.get("pyside6_detected"):
        risks.append("PySide6 Qt plugin collection (platforms/imageformats/styles minimum)")
    if special.get("pyside6_webengine_detected"):
        risks.append("Qt WebEngine plugin/resources/QML packaging if WebEngine path is used")
    if special.get("vtk_detected"):
        risks.append("VTK hiddenimports and native DLL collection (vtkmodules.*)")
    if special.get("simpleitk_detected"):
        risks.append("SimpleITK pyd/DLL collection")
    if special.get("multiprocessing_detected"):
        risks.append("multiprocessing spawn behavior in frozen builds (freeze_support, child module imports)")
    if qt_plugins_inventory.get("available"):
        risks.append("OpenGL/software rendering compatibility on Windows (Qt + VTK)")
    runtime_counts = runtime_inventory.get("runtime_data_risk_findings_count_by_category", {})
    if runtime_counts.get("cwd_usage", 0) or runtime_counts.get("open_write", 0) or runtime_counts.get("mkdir", 0):
        risks.append("Project/dist-relative runtime writes may leak data into packaged folders")
    seen = set()
    out: list[str] = []
    for r in risks:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def build_audit_summary_markdown(
    repo_root: Path,
    entrypoints: dict[str, Any],
    imports_summary: dict[str, Any],
    dependency_tree: dict[str, Any],
    resource_inventory: dict[str, Any],
    runtime_inventory: dict[str, Any],
    dll_inventory: dict[str, Any],
    qt_plugins_inventory: dict[str, Any],
    repo_binary_inventory: dict[str, Any],
) -> str:
    special = imports_summary.get("special_modules", {})
    app_a = entrypoints.get("appA", {})
    app_b = entrypoints.get("appB", {})
    hidden = imports_summary.get("suggested_hiddenimports", [])
    runtime_exclusions = runtime_inventory.get("must_not_package_detected_paths", [])
    slicer_exe_present = any(
        item["path"].lower().endswith("aipacsadvancedviewer.exe")
        for item in repo_binary_inventory.get("repo_local_binaries", [])
    )
    slicer_runtime_note = (
        "Custom Slicer runtime binary detected in repo."
        if slicer_exe_present
        else "Custom Slicer runtime binary (AIPacsAdvancedViewer.exe) not present in repo; App B is a launcher and requires an external or locally built Slicer runtime."
    )
    high_risk = derive_high_risk_items(imports_summary, runtime_inventory, qt_plugins_inventory)

    lines: list[str] = []
    lines.append("# Audit Summary")
    lines.append("")
    lines.append(f"- Generated (UTC): `{now_utc_iso()}`")
    lines.append(f"- Repo root: `{repo_root}`")
    lines.append("")
    lines.append("## Entrypoints")
    lines.append("")
    lines.append(f"- App A: `{app_a.get('entrypoint')}` ({app_a.get('name')})")
    lines.append(f"  - Detection: {app_a.get('how_detected')}")
    lines.append(f"- App B: `{app_b.get('entrypoint')}` ({app_b.get('name')})")
    lines.append(f"  - Detection: {app_b.get('how_detected')}")
    lines.append("")
    lines.append("## GUI / Heavy Libraries")
    lines.append("")
    lines.append(f"- PySide6 detected: `{special.get('pyside6_detected')}`")
    lines.append(f"- VTK/vtkmodules detected: `{special.get('vtk_detected')}`")
    lines.append(f"- SimpleITK detected: `{special.get('simpleitk_detected')}`")
    lines.append(f"- multiprocessing detected: `{special.get('multiprocessing_detected')}`")
    if special.get("pyside6_submodules"):
        lines.append(f"- PySide6 submodules ({len(special.get('pyside6_submodules', []))})")
        for mod in special.get("pyside6_submodules", [])[:80]:
            lines.append(f"  - `{mod}`")
    if special.get("vtkmodules_submodules"):
        lines.append(f"- vtkmodules submodules ({len(special.get('vtkmodules_submodules', []))})")
        for mod in special.get("vtkmodules_submodules", [])[:80]:
            lines.append(f"  - `{mod}`")
    lines.append("")
    lines.append("## Dynamic Import Risks / Hiddenimports")
    lines.append("")
    lines.append(f"- Dynamic import risk files: `{imports_summary.get('dynamic_import_risks', {}).get('count', 0)}`")
    lines.append(f"- Suggested hiddenimports ({len(hidden)} total, preview):")
    for item in hidden[:80]:
        lines.append(f"  - `{item}`")
    if len(hidden) > 80:
        lines.append(f"  - `... +{len(hidden) - 80} more`")
    lines.append("")
    lines.append("## Runtime Data Paths (Privacy Critical)")
    lines.append("")
    lines.append("- Must not package (detected paths/patterns preview):")
    for item in runtime_exclusions[:80]:
        lines.append(f"  - `{item}`")
    if len(runtime_exclusions) > 80:
        lines.append(f"  - `... +{len(runtime_exclusions) - 80} more`")
    runtime_root = runtime_inventory.get("recommended_runtime_storage", {}).get("windows_localappdata_root")
    lines.append(f"- Recommended runtime root: `{runtime_root}`")
    lines.append(f"- {runtime_inventory.get('recommended_runtime_storage', {}).get('qt_recommendation', '')}")
    lines.append("")
    lines.append("## Slicer Runtime Requirement")
    lines.append("")
    lines.append(f"- {slicer_runtime_note}")
    lines.append("- External binaries referenced in code:")
    for item in repo_binary_inventory.get("external_binaries_referenced_in_code", [])[:50]:
        lines.append(f"  - `{item['literal']}` (count={item['count']})")
    lines.append("")
    lines.append("## Qt Plugins / DLL Inventory (Environment)")
    lines.append("")
    lines.append(f"- Qt plugins inventory available: `{qt_plugins_inventory.get('available')}`")
    if qt_plugins_inventory.get("qt_plugins_path"):
        lines.append(f"- Qt plugins path: `{qt_plugins_inventory.get('qt_plugins_path')}`")
    for pkg in ("vtkmodules", "SimpleITK", "vtk"):
        info = dll_inventory.get("environment_package_binaries", {}).get(pkg, {})
        lines.append(
            f"- {pkg}: available=`{info.get('available')}`, pyd_count=`{info.get('pyd_count', 0)}`, dll_count=`{info.get('dll_count', 0)}`"
        )
    lines.append("")
    lines.append("## Resource Inventory")
    lines.append("")
    for ext in [".ui", ".qss", ".qrc", ".png", ".svg", ".ico", ".json", ".ttf"]:
        value = resource_inventory.get("counts_by_extension", {}).get(ext)
        if value is not None:
            lines.append(f"- `{ext}`: `{value}`")
    lines.append("- Likely package data roots:")
    for item in resource_inventory.get("likely_package_data_paths", [])[:80]:
        lines.append(f"  - `{item['path']}` ({item['type']}, files={item['file_count']}) - {item['reason']}")
    lines.append("")
    lines.append("## High-Risk Packaging Items")
    lines.append("")
    for item in high_risk:
        lines.append(f"- {item}")
    if not high_risk:
        lines.append("- None detected (unexpected for this codebase)")
    lines.append("")
    env_dep = dependency_tree.get("environment_dependencies", {})
    lines.append("## Dependency Tree / Environment Notes")
    lines.append("")
    if env_dep.get("ran"):
        lines.append(f"- pip freeze captured from controlled venv: `{env_dep.get('venv_path')}`")
    else:
        lines.append(f"- pip freeze not captured: {env_dep.get('reason', env_dep.get('error', 'unknown reason'))}")
    lines.append("- Re-run audit inside `.venv_build` after installing build/runtime dependencies.")
    lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run packaging audit and inventory generation")
    parser.add_argument("--repo-root", type=Path, default=None, help="Repository root (defaults to script parents[3])")
    parser.add_argument("--verbose", action="store_true", help="Print progress")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    repo_root = (args.repo_root or script_path.parents[3]).resolve()
    builder_root = repo_root / "builder"
    audit_root = builder_root / "audit"
    inventory_root = builder_root / "inventory"
    reports_root = audit_root / "reports"
    scans_root = audit_root / "scans"

    for p in [builder_root, audit_root, inventory_root, reports_root, scans_root]:
        p.mkdir(parents=True, exist_ok=True)

    py_files = list(iter_python_files(repo_root))
    if args.verbose:
        print(f"[audit] repo={repo_root}")
        print(f"[audit] python_files={len(py_files)}")

    file_scans: list[PythonFileScan] = []
    runtime_findings: list[dict[str, Any]] = []
    env_var_refs: set[str] = set()
    for py in py_files:
        fs, findings, envs = parse_python_file(py, repo_root)
        file_scans.append(fs)
        runtime_findings.extend(findings)
        env_var_refs.update(envs)

    entrypoints = detect_entrypoints(file_scans)
    imports_summary = build_imports_summary(file_scans)
    dependency_tree = build_dependency_tree_json(repo_root, imports_summary)
    resource_inventory = summarize_resource_inventory(repo_root)
    runtime_inventory = scan_runtime_paths_and_privacy(repo_root, runtime_findings, env_var_refs)
    repo_binary_inventory = scan_repo_binaries_and_external_refs(repo_root)
    dll_env_inventory, qt_plugins_inventory = collect_runtime_binary_inventory(imports_summary)
    dll_inventory = {**dll_env_inventory, "repo_binary_inventory": repo_binary_inventory}

    safe_json_dump(inventory_root / "entrypoints.json", entrypoints)
    safe_json_dump(inventory_root / "imports_summary.json", imports_summary)
    safe_json_dump(inventory_root / "dependencies_tree.json", dependency_tree)
    safe_json_dump(inventory_root / "resource_inventory.json", resource_inventory)
    safe_json_dump(inventory_root / "runtime_data_paths_inventory.json", runtime_inventory)
    safe_json_dump(inventory_root / "dll_inventory.json", dll_inventory)
    safe_json_dump(inventory_root / "qt_plugins_inventory.json", qt_plugins_inventory)

    audit_md = build_audit_summary_markdown(
        repo_root,
        entrypoints,
        imports_summary,
        dependency_tree,
        resource_inventory,
        runtime_inventory,
        dll_inventory,
        qt_plugins_inventory,
        repo_binary_inventory,
    )
    (reports_root / "AUDIT_SUMMARY.md").write_text(audit_md, encoding="utf-8")

    safe_json_dump(
        scans_root / "scan_run_metadata.json",
        {
            "generated_at_utc": now_utc_iso(),
            "repo_root": str(repo_root),
            "python_files_scanned": len(py_files),
            "inventory_outputs": [
                "builder/inventory/entrypoints.json",
                "builder/inventory/imports_summary.json",
                "builder/inventory/dependencies_tree.json",
                "builder/inventory/dll_inventory.json",
                "builder/inventory/qt_plugins_inventory.json",
                "builder/inventory/resource_inventory.json",
                "builder/inventory/runtime_data_paths_inventory.json",
                "builder/audit/reports/AUDIT_SUMMARY.md",
            ],
        },
    )

    if args.verbose:
        print("[audit] complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
