"""AI-PACS ``cloud_consultation`` module — Drive-backed physician consultation.

Phase 2 (current): the cloud **transport** layer and a transport-agnostic engine
that mirrors an existing Offline Cloud *package folder* to/from a cloud provider
(Google Drive first). Phases 3-6 add the consultation envelope, resumable sync
engine, assignment, and notifications.

Boundaries:
  * This module owns the ``CloudTransport`` abstraction + the package mirror engine.
  * It depends on :mod:`modules.Identity` ONLY to obtain authenticated credentials
    (it never performs OAuth or touches the server login).
  * It reuses the existing Offline Cloud package format unchanged
    (``PacsClient.utils.offline_cloud``) — Drive is just a transport.

Design reference:
    docs/plans/cloud-consultation/GOOGLE_DRIVE_CONSULTATION_PLAN_2026-05-31.md

Import safety: this package ``__init__`` imports nothing heavy. Provider/Qt/Google
imports are local to where they are used.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
