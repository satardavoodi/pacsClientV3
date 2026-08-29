"""One-off: print the staged prompt sizes and fingerprints.

Used to sanity-check a calibration edit - the numbers go into the plan doc so
a later revision can be compared against a recorded baseline.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from modules.ai_imaging.eagle_eye_lumbar import analysis_prompt as p

for s in p.LUMBAR_PATHOLOGY.stages:
    print("%-20s v%-7s %6d chars  %s  %s (%s)" % (
        s.id, s.version, len(s.text), s.fingerprint[:16],
        s.model_default, s.model_feature))
print("pipeline %-11s v%-7s          %s" % (
    p.LUMBAR_PATHOLOGY.id, p.LUMBAR_PATHOLOGY.version,
    p.LUMBAR_PATHOLOGY.fingerprint[:16]))
