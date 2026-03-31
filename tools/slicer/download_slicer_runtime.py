"""
Download the pre-built Slicer runtime from GitHub Releases.

This script downloads and extracts the Slicer runtime zip into
the correct location within the project tree. It's the recommended
way to set up the Advanced 3D Slicer module on a fresh machine.

Usage:
    python tools/slicer/download_slicer_runtime.py
    python tools/slicer/download_slicer_runtime.py --tag slicer-runtime-v0.1.0
    python tools/slicer/download_slicer_runtime.py --url "https://example.com/slicer_runtime.zip"
"""
import argparse
import hashlib
import io
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ── Config ─────────────────────────────────────────────────────────────────
GITHUB_REPO = "Vahid-INO/ai-pacs"
DEFAULT_TAG = "slicer-runtime-v0.1.0"
ASSET_NAME = "slicer_runtime_v0.1.0.zip"

TARGET_DIR = (
    Path(__file__).resolve().parents[2]
    / "modules" / "mpr" / "advanced_3d_slicer"
    / "slicer_custom_app" / "NewMPR2Slicer" / "build"
)


def _get_release_asset_url(repo: str, tag: str, asset_name: str) -> str:
    """Resolve the download URL for a GitHub release asset."""
    api_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    try:
        import json
        req = Request(api_url, headers={"Accept": "application/vnd.github.v3+json"})
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for asset in data.get("assets", []):
            if asset["name"] == asset_name:
                return asset["browser_download_url"]
        names = [a["name"] for a in data.get("assets", [])]
        print(f"ERROR: Asset '{asset_name}' not found in release '{tag}'.")
        print(f"Available assets: {names}")
        sys.exit(1)
    except HTTPError as e:
        if e.code == 404:
            print(f"ERROR: Release '{tag}' not found in {repo}.")
            print(f"Create a release at: https://github.com/{repo}/releases/new")
        else:
            print(f"ERROR: GitHub API returned HTTP {e.code}: {e.reason}")
        sys.exit(1)
    except URLError as e:
        print(f"ERROR: Cannot reach GitHub API: {e.reason}")
        sys.exit(1)


def _download(url: str) -> bytes:
    """Download a file with progress reporting."""
    print(f"Downloading from: {url}")
    req = Request(url, headers={"User-Agent": "aipacs-slicer-downloader/1.0"})
    try:
        with urlopen(req, timeout=300) as resp:
            total = resp.headers.get("Content-Length")
            total = int(total) if total else None
            buf = io.BytesIO()
            downloaded = 0
            while True:
                chunk = resp.read(1048576)  # 1 MB chunks
                if not chunk:
                    break
                buf.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  {downloaded / 1048576:.0f} / {total / 1048576:.0f} MB ({pct:.0f}%)", end="", flush=True)
                else:
                    print(f"\r  {downloaded / 1048576:.0f} MB downloaded", end="", flush=True)
            print()
            return buf.getvalue()
    except (HTTPError, URLError) as e:
        print(f"\nERROR: Download failed: {e}")
        sys.exit(1)


def _extract(data: bytes, target: Path):
    """Extract zip data to target directory."""
    print(f"Extracting to: {target}")
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        total = len(zf.namelist())
        for i, member in enumerate(zf.namelist()):
            zf.extract(member, target)
            if (i + 1) % 500 == 0 or (i + 1) == total:
                print(f"\r  {i + 1} / {total} files", end="", flush=True)
    print()


def main():
    parser = argparse.ArgumentParser(description="Download Slicer runtime for AI-PACS")
    parser.add_argument("--tag", default=DEFAULT_TAG,
                        help=f"GitHub release tag (default: {DEFAULT_TAG})")
    parser.add_argument("--url", default=None,
                        help="Direct download URL (bypasses GitHub API)")
    parser.add_argument("--target", type=Path, default=None,
                        help="Target directory (default: auto-detect)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing build directory")
    args = parser.parse_args()

    target = args.target or TARGET_DIR

    # Safety check
    if target.exists() and any(target.iterdir()):
        if not args.force:
            print(f"WARNING: Target directory already exists and is not empty: {target}")
            print("Use --force to overwrite, or remove it manually first.")
            sys.exit(1)
        else:
            print(f"Removing existing build at {target} ...")
            import shutil
            shutil.rmtree(target, ignore_errors=True)

    # Resolve download URL
    if args.url:
        url = args.url
    else:
        url = _get_release_asset_url(GITHUB_REPO, args.tag, ASSET_NAME)

    # Download
    data = _download(url)
    sha256 = hashlib.sha256(data).hexdigest()
    print(f"  SHA256: {sha256}")
    print(f"  Size: {len(data) / 1048576:.0f} MB")

    # Extract
    _extract(data, target)

    # Verify
    exe = target / "AIPacsAdvancedViewer.exe"
    if exe.exists():
        print(f"\nSUCCESS: Runtime extracted to {target}")
        print(f"Launcher: {exe}")
        print("\nNext steps:")
        print("  1. Run: python tools/slicer/verify_slicer_build.py")
        print("  2. Run the PACS app and test the Advanced MPR button")
    else:
        print(f"\nWARNING: AIPacsAdvancedViewer.exe not found at expected location.")
        print(f"The zip may have a different structure. Check {target} manually.")
        sys.exit(1)


if __name__ == "__main__":
    main()
