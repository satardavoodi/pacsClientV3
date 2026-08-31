"""Eagle Eye lumbar benchmark: reference reads, report scoring, repeated runs.

The pipeline's morphology decision is not deterministic - the same study run
six times on 2026-08-30 produced three different L5-S1 morphologies. Any change
evaluated at n=1 is therefore uninterpretable, which is what this package
exists to prevent: it runs a captured session N times, parses each FINAL
REPORT into a structured finding set, and scores that against a radiologist
reference read.

Nothing here contains patient data. Reference reads live under
``user_data/ai/eagle_eye/_bench/ground_truth`` (gitignored) and are addressed
by an opaque case id.
"""

from __future__ import annotations

__all__ = ["reference", "scoring"]
