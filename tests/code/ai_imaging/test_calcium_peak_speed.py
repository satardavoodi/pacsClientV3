"""Exact peak regression runnable with the isolated Breast CPU runtime."""
import unittest
import numpy as np
try:
    from tools.eagle_eye.physical_peaks_reference import extract_physical_peaks as reference
    from tools.eagle_eye.physical_peaks_fast import extract_physical_peaks as candidate
except ModuleNotFoundError as exc:
    if exc.name == "scipy":
        raise unittest.SkipTest("Run peak equivalence with the isolated Breast CPU runtime (scipy).") from exc
    raise

class PeakEquivalence(unittest.TestCase):
    def test_random_masked_and_discrete(self):
        for seed in range(40):
            rng = np.random.default_rng(seed)
            for discrete in (False, True):
                field = rng.random((47,61))
                if discrete: field = np.floor(field * 5)
                for distance in (0,.1,.2,.5):
                    args=dict(threshold=.2,spacing_yx_mm=(.1,.07),min_distance_mm=distance,
                              valid_mask=rng.random(field.shape)>.15,max_peaks=None if seed%2 else 50)
                    np.testing.assert_array_equal(candidate(field,**args),reference(field,**args))
    def test_plateaus_shoulders_and_edges(self):
        for field in (np.ones((9,11)),np.array([[0,1,1,2,0.]]),
                      np.array([[1,0,1],[0,1,0],[1,0,1]]),np.zeros((1,1))):
            args=dict(threshold=0,spacing_yx_mm=(.1,.1),min_distance_mm=.1)
            np.testing.assert_array_equal(candidate(field,**args),reference(field,**args))
    def test_invalid(self):
        for extra in (dict(max_peaks=True),dict(max_peaks=-1),dict(min_distance_mm=-1),
                      dict(spacing_yx_mm=(0,1)),dict(threshold=float('nan'))):
            args=dict(threshold=0,spacing_yx_mm=(1,1),min_distance_mm=1);args.update(extra)
            with self.assertRaises(ValueError): candidate(np.ones((3,3)),**args)

if __name__ == '__main__': unittest.main()
