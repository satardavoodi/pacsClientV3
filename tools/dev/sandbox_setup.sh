#!/usr/bin/env bash
# =============================================================================
# sandbox_setup.sh
#
# Recreate the AI-PACS Python runtime *inside an agent's headless Linux sandbox*
# (Ubuntu 22.04, non-root) so the offscreen pytest suite, import checks and ruff
# can run there. This is NOT for the Windows clinical workstation — that still
# runs the VS Code source build (see CLAUDE.md). Nothing here touches the repo.
#
# Why a script: the sandbox is ephemeral (packages are wiped between sessions),
# so this is the one command to rebuild the environment. It is idempotent and
# the heavy wheels download resumably — if an agent's per-command time limit
# interrupts it, just run it again and it resumes / skips what's done.
#
# Usage (from inside the sandbox):
#     bash tools/dev/sandbox_setup.sh
#     # then, to run tests:
#     source tools/dev/sandbox_env.sh   # exports LD_LIBRARY_PATH + QT_QPA_PLATFORM
#     python3 -m pytest tests/code/<target> -p no:debugging -q
#
# Optional: set AIPACS_WHEEL_CACHE to a persistent dir to avoid re-downloading
# the ~360 MB of PySide6/vtk wheels every session.
# =============================================================================
set -uo pipefail

PKG="--break-system-packages"
ROOT="/tmp/aipacs-sandbox"
VENDOR="$ROOT/vendor"
WHEELS="${AIPACS_WHEEL_CACHE:-$ROOT/wheels}"
VLIB="$VENDOR/root/usr/lib/x86_64-linux-gnu"
mkdir -p "$VENDOR" "$WHEELS"

echo "==> [1/5] Vendoring system libs (libEGL, PortAudio) without root ..."
# Qt needs libEGL.so.1; sounddevice/pyaudio need libportaudio. apt-get *download*
# works with the prebuilt index (apt-get *update*/install would need root).
cd "$VENDOR"
for p in libegl1 libglvnd0 libportaudio2 portaudio19-dev; do
  ls "${p}"_*.deb >/dev/null 2>&1 || apt-get download "$p" 2>/dev/null || \
    echo "    (warn: could not download $p)"
done
for d in *.deb; do [ -f "$d" ] && dpkg -x "$d" root 2>/dev/null; done
echo "    libs: $(ls "$VLIB" 2>/dev/null | grep -ciE 'EGL|portaudio') shared objects vendored"

echo "==> [2/5] Installing light + medium pip packages ..."
python3 -m pip install $PKG -q \
  pynetdicom==2.1.1 "pydicom>=2.4.0" \
  pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg pylibjpeg-rle \
  grpcio "google==3.0.0" "google-api-python-client==2.168.0" \
  "google-auth>=2.29.0" "google-auth-oauthlib>=1.2.0" \
  natsort==8.4.0 qasync QtAwesome "openai==1.97.0" "requests[socks]>=2.31.0" \
  python-dotenv "SpeechRecognition>=3.10.0" "keyring>=24.0.0" "cryptography>=42.0.0" \
  pypdf python-pptx pytesseract psutil "pydantic>=2.0" \
  soundfile sounddevice webrtcvad \
  numpy pandas opencv-python-headless "pytest>=8" \
  || echo "    (warn: some light packages failed — re-run to retry)"

echo "==> [3/5] Building pyaudio against vendored PortAudio ..."
CPATH="$VENDOR/root/usr/include" LIBRARY_PATH="$VLIB" \
  python3 -m pip install $PKG -q pyaudio || echo "    (pyaudio optional — skipped)"

echo "==> [4/5] Heavy wheels (PySide6, vtk, SimpleITK) — resumable download ..."
# Resolve the exact wheel URLs (no download), then wget -c so an interrupted run
# resumes instead of restarting. pip then installs from the local cache.
python3 -m pip install $PKG --dry-run --no-deps --ignore-installed --report "$ROOT/_rep.json" \
  "PySide6==6.10.2" "PySide6-Essentials==6.10.2" "PySide6-Addons==6.10.2" "shiboken6==6.10.2" \
  "vtk==9.6.2" "SimpleITK==2.5.3" >/dev/null 2>&1 || true
python3 - "$ROOT/_rep.json" "$WHEELS/urls.txt" <<'PY' 2>/dev/null || true
import json, sys
rep, out = sys.argv[1], sys.argv[2]
urls = [i["download_info"]["url"] for i in json.load(open(rep)).get("install", [])]
open(out, "w").write("\n".join(urls) + "\n")
print(f"    {len(urls)} wheel URLs resolved")
PY
[ -s "$WHEELS/urls.txt" ] && ( cd "$WHEELS" && wget -c -q -i urls.txt && echo "    download pass complete" )
python3 -m pip install $PKG --no-index --find-links "$WHEELS" \
  "PySide6==6.10.2" "vtk==9.6.2" "SimpleITK==2.5.3" \
  && echo "    heavy wheels installed" \
  || echo "    (heavy wheels incomplete — RE-RUN this script to resume the download)"

echo "==> [5/5] Verifying the environment ..."
cat > "$ROOT/../aipacs_env_check.py" <<'PY' 2>/dev/null || true
PY
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH="$VLIB:${LD_LIBRARY_PATH:-}" python3 - <<'PY'
mods = ["PySide6", "vtk", "SimpleITK", "pydicom", "pynetdicom", "cv2", "numpy",
        "pandas", "qasync", "qtawesome", "sounddevice", "soundfile", "pydantic"]
bad = []
for m in mods:
    try: __import__(m)
    except Exception as e: bad.append(f"{m}: {str(e)[:50]}")
from PySide6 import QtWidgets
QtWidgets.QApplication([])
import PySide6
print(f"    PySide6 {PySide6.__version__} offscreen OK | {len(mods)-len(bad)}/{len(mods)} core imports OK")
if bad: print("    NOTE inert/failed:", "; ".join(bad))
print("    (comtypes is Windows-only and stays inert on Linux — expected)")
PY

echo ""
echo "DONE. Before running tests, load the env:  source tools/dev/sandbox_env.sh"
