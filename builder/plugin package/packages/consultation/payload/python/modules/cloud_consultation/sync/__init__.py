"""Resumable, state-tracked sync between a local consultation package and the cloud.

Qt-free core (``models``, ``engine``, ``state_machine``) so it is fully unit-testable.
The optional :mod:`modules.cloud_consultation.sync.worker` (a QThread wrapper) is
imported on demand by the UI, not here.
"""
