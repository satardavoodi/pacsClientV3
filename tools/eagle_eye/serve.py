"""Start the source Eagle Eye job service using an explicit deployment config."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from modules.ai_imaging.eagle_eye_remote.server import serve

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    serve(json.loads(args.config.read_text(encoding='utf-8-sig')))
