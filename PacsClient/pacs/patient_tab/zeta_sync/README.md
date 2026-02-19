# Zeta Sync Module

Central synchronization utilities for linking cursor/position and slice changes
across viewer combinations (MPR↔MPR, MPR↔2D, 2D↔2D).

**Goal:** keep sync logic isolated here and use adapter callbacks from viewers.
