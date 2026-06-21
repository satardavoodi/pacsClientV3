# Source this in the Linux sandbox before running the AI-PACS test suite:
#     source tools/dev/sandbox_env.sh
# Sets the vendored library path (libEGL / PortAudio) and forces Qt offscreen.
# Harmless to source even before sandbox_setup.sh has run.
_AIPACS_VLIB="/tmp/aipacs-sandbox/vendor/root/usr/lib/x86_64-linux-gnu"
export LD_LIBRARY_PATH="${_AIPACS_VLIB}:${LD_LIBRARY_PATH:-}"
export QT_QPA_PLATFORM="offscreen"
echo "AI-PACS sandbox env: QT_QPA_PLATFORM=offscreen, libEGL/PortAudio on LD_LIBRARY_PATH"
