"""Shared guard for MG paired-series (combined viewer) selection.

Why this module exists
----------------------
The ``series`` DB table stores ``series_name`` as NULL for studies whose series
rows were written without a folder-derived name.  Example: the four MG series of
study ``2.16.840.1.113669.632.20.20260802.113626638.6.18`` (patient 52795) all
have ``series_name IS NULL`` while carrying distinct descriptions
(``R-CC``, ``L-CC``, ``R-MLO``, ``L-MLO``).

Several call sites read that value with::

    series_name = str(series_info.get('series_name', ''))

``str(None)`` is the literal string ``'None'``, which is *truthy*.  Consequences:

* ``ViewerController._rebuild_series_index()`` accepted ``'None'`` as a real
  name and bucketed EVERY MG series of the study under one key::

      _paired_series_map == {'None': ['2', '4', '6', '8']}

* the switch / warmup paths then paired the current series with the *first
  other* number in that bucket, attaching L-CC as ``vtk_image_data_2`` of the
  R-MLO viewport.

``CustomCombineImageViewers.get_count_of_slices()`` returns ``Z1 + Z2``, so a
single-image MLO view reported "1 / 2" and scrolling to slice 1 called
``change_local_series('series_2')`` and swapped in the CC image.

Normalising the sentinel here makes an absent series name *unpairable*, which is
the correct behaviour: only a genuine, shared, non-empty series name may pair.
Studies that do carry real series names are unaffected.

Kill switch
-----------
Set ``AIPACS_DISABLE_SERIES_NAME_PAIRING_GUARD=1`` to restore the legacy
(pre-guard) behaviour without editing code.
"""

import os

_DISABLE_ENV = "AIPACS_DISABLE_SERIES_NAME_PAIRING_GUARD"

# Values that must never be treated as a real, shareable series name.
# 'none' covers str(None); 'unknown' covers the `.get(..., 'Unknown')` default
# used by the layout path; the rest are defensive.
_EMPTY_SENTINELS = frozenset({"", "none", "null", "nan", "unknown", "n/a", "-"})

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def pairing_guard_enabled() -> bool:
    """Guard is ON by default; env var opts back into the legacy behaviour."""
    try:
        return str(os.environ.get(_DISABLE_ENV, "")).strip().lower() not in _TRUTHY
    except Exception:
        return True


def normalize_series_name(value) -> str:
    """Return a series name usable as a pairing key, or '' when there is none.

    ``None``, ``'None'``, ``''``, whitespace and the other placeholder spellings
    in ``_EMPTY_SENTINELS`` all collapse to ``''`` (i.e. "no pairing key").
    """
    if not pairing_guard_enabled():
        # Legacy reproduction: the raw `str(...)` conversion the call sites used,
        # sentinels and all — `str(None)` is the truthy literal 'None'.
        try:
            return str(value)
        except Exception:
            return ""
    if value is None:
        return ""
    try:
        text = str(value).strip()
    except Exception:
        return ""
    if text.lower() in _EMPTY_SENTINELS:
        return ""
    return text


def can_pair_series_names(name_a, name_b) -> bool:
    """True only when both series carry the SAME non-empty, real series name.

    Replaces the bare ``series_name_2 == series_name`` equality checks, which
    evaluated True for ``None == None`` and ``'None' == 'None'``.
    """
    key_a = normalize_series_name(name_a)
    if not key_a:
        return False
    return key_a == normalize_series_name(name_b)
