"""Test fixtures for the EchoMind Command Layer unit tests.

Keeps the project root on sys.path so ``from modules.EchoMind.secretary
import ...`` resolves.
"""
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
