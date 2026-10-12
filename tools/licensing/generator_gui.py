"""Compatibility entry point for the company generator in modules/LicenseGenerator."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from modules.LicenseGenerator.license_generator import LicenseGeneratorWindow, main


if __name__ == '__main__':
    raise SystemExit(main())
