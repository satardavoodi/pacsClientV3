"""SeriesRef — the ONE immutable series-identity authority (OPT-35, 2026-07-14).

WHY THIS EXISTS
---------------
To display one series the viewer used to independently re-answer the same question —
*"which study does this display key belong to, and where do its bytes and rows live?"* —
at FOUR separate stages (disk path, DB ``study_pk``, cache key, render gate), each
deriving the answer from **mutable tab state** (``import_folder_path``,
``metadata_fixed['study_pk']``) that any other load could overwrite.

Every multi-study patient whose studies share SERIES NUMBERS found a stage where the
derivations disagreed, and each time a bespoke guard was added:

    48912 / 29694  disk path (plain key)     -> AIPACS_PRIMARY_SERIES_POISON_GUARD
    49836          disk path (tab repoint)   -> AIPACS_TAB_PATH_PRIMARY_ONLY
    50238          DB study_pk               -> AIPACS_PRIMARY_STUDY_PK_GUARD
    (+ 48952 / 48296 / 48476 / 48101)        -> five more flags

Nine flags answering ONE question. This module answers it ONCE: a display key is
resolved into a frozen :class:`SeriesRef` and every downstream stage CONSUMES it and
derives nothing.

    SeriesRef
        display_key    "3"  or  "1000003"   <- the UI handle (ALWAYS a digit string)
        study_uid      the series' OWN study
        study_pk       that study's pk (filled by the consumer; see below)
        series_uid     globally unique — THE identity
        series_number  the series' own (disk / original) number
        series_path    SOURCE_PATH/<study_uid>/<series_number>
        study_slot     0 = primary study
        source         'entry' | 'slot_fallback' | 'derived'  (see CONFIDENCE)

PURITY (deliberate)
-------------------
Stdlib only. No Qt, no VTK, no pydicom, no numpy, and — importantly — **no database**.
That keeps it unit-testable offscreen and keeps the DB round-trip out of this layer.
``study_pk`` is therefore left ``None`` by the builder and filled in by the caller via
:meth:`SeriesRef.with_study_pk` using its own cached lookup. The RULE the caller must
follow is a one-liner, and it is the whole point of the refactor:

    study_pk = pk_of(ref.study_uid)

That single rule satisfies BOTH polarities that previously needed two opposing guards:
a PLAIN key's entry carries ``study_uid == primary`` (slot 0, offset 0), so it resolves
to the PRIMARY pk (the 50238 fix); an OFFSET key's entry carries its own study, so it
resolves to that study's pk (the 48101 fix). Neither ever consults tab state.

CONFIDENCE (``source``) — why a ref is not always safe to act on
----------------------------------------------------------------
* ``entry``          — resolved from the series' own ``_server_series_info`` entry, which
                       the multi-study index builder stamps with ``study_uid``,
                       ``_orig_series_number`` and an absolute ``series_path``. This is
                       the authority; act on it.
* ``slot_fallback``  — an OFFSET key whose entry was dropped by a later rebuild,
                       recomputed from the STABLE slot order using the documented
                       ``SOURCE_PATH/<study_uid>/<orig>`` layout. Act on it.
* ``derived``        — no entry and not an offset key (the ordinary SINGLE-study case).
                       The path is *inferred* as ``SOURCE_PATH/<primary>/<key>``, which is
                       WRONG for an externally-imported study whose folder lives outside
                       SOURCE_PATH. Callers MUST NOT override a working legacy path with a
                       ``derived`` ref — use it for identity (study_uid / series_uid) only.

CORRECTIONS THIS MODULE IS REQUIRED TO HONOUR (each is pinned by a guard test)
-----------------------------------------------------------------------------
* **C1 — NEVER ``int()`` a server-provided series field.** A radiography device omitted
  ``SeriesNumber`` (legal: type-2) and the server serialised it as the literal string
  ``"None"``; ``int("None")`` raised and aborted an ENTIRE study's metadata build, so the
  study never downloaded (OPT-25 / Roshana). Use :func:`parse_series_number`, which is
  tolerant and NEVER raises.
* **C2 — the synthetic reserved band 900001..999999 stays a PLAIN key.** It is
  deliberately BELOW the 1_000_000 offset threshold. A synthetic number must never be
  mistaken for an offset key.
* **C3 — healthy data is byte-identical, including TYPE.** ``"02"`` stays the string
  ``"02"`` — folder / thumbnail naming depends on it. Never "clean up" a valid number.
* **C4 — images are fetched by ``series_uid``, never by series number.** The number is
  local naming / ordering only. That is what makes this whole scheme safe.
* **C11 — the offset-key scheme (``slot*1_000_000 + orig``) stays.** It is the UI handle,
  not the identity. Do not turn ``display_key`` into a composite string: the ZetaBoost
  warmup callback hard-requires a digit key (``isdigit()`` / ``int(sn)``) — C10.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = [
    "SeriesRef",
    "MULTISTUDY_OFFSET",
    "parse_series_number",
    "is_offset_key",
    "build_series_ref_table",
    "resolve_series_ref",
    "shadow_compare",
]

# The multi-study display-key offset. A key >= this belongs to a NON-primary study
# (slot = key // OFFSET, original number = key % OFFSET). Synthetic series numbers for
# devices that omit SeriesNumber live in 900001..999999 — deliberately BELOW this, so
# they remain PLAIN (primary-study) keys. (C2, C11)
MULTISTUDY_OFFSET = 1_000_000


def parse_series_number(value: Any) -> Optional[int]:
    """Tolerantly parse a series number. NEVER raises. Returns ``None`` if unusable.

    **C1.** The server can send the literal string ``"None"`` for a missing (type-2)
    ``SeriesNumber``; ``"None"`` is a truthy non-empty string, so the classic
    ``int(str(v) or 0)`` guard does not fire and ``int()`` raises — which once aborted an
    entire study's metadata build and stopped the study downloading at all.

    Delegates to the canonical network-layer predicate when it is importable so there is
    exactly ONE parsing rule in the codebase; the inline fallback keeps this module pure
    and importable in isolation (offscreen tests).
    """
    try:  # the ONE canonical predicate (modules/network/series_identity.py)
        from modules.network.series_identity import parse_series_number as _canonical
        return _canonical(value)
    except Exception:
        pass
    if value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    if not text or text.lower() in ("none", "null", "nan", "n/a", ""):
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def is_offset_key(display_key: Any) -> bool:
    """True when *display_key* is a multi-study OFFSET key (a NON-primary study).

    A plain key — including a synthetic 900001..999999 number (C2) — is False.
    """
    n = parse_series_number(display_key)
    return n is not None and n >= MULTISTUDY_OFFSET


@dataclass(frozen=True)
class SeriesRef:
    """Immutable identity of ONE series. Resolve once; thread it; derive nothing."""

    display_key: str            # the UI handle — ALWAYS a digit string (C10/C11)
    study_uid: str              # the series' OWN study (never the tab's, unless it is)
    series_number: str          # the series' own disk/original number (C3: type preserved)
    series_path: str            # SOURCE_PATH/<study_uid>/<series_number>
    series_uid: Optional[str] = None   # globally unique — THE identity (C4)
    study_pk: Optional[int] = None     # filled by the consumer: pk_of(ref.study_uid)
    study_slot: int = 0
    source: str = "derived"     # 'entry' | 'slot_fallback' | 'derived'

    # ── properties ────────────────────────────────────────────────────────
    @property
    def study_path(self) -> str:
        """The STUDY folder (the parent of ``series_path``) — what the disk loader wants."""
        return str(PurePath(self.series_path).parent)

    @property
    def is_primary(self) -> bool:
        """True when this series belongs to the tab's PRIMARY study (slot 0)."""
        return self.study_slot == 0

    @property
    def is_authoritative(self) -> bool:
        """True when the ref's PATH may be acted on.

        ``derived`` refs infer the path as ``SOURCE_PATH/<primary>/<key>``, which is wrong
        for an externally-imported study living outside SOURCE_PATH — so a caller must not
        override a working legacy path with one. Their IDENTITY fields (study_uid /
        series_uid) are still usable.
        """
        return self.source in ("entry", "slot_fallback")

    def with_study_pk(self, study_pk: Optional[int]) -> "SeriesRef":
        """Return a copy carrying the resolved ``study_pk`` (the ref stays immutable)."""
        return replace(self, study_pk=study_pk)


def _entry_series_uid(entry: Mapping[str, Any]) -> Optional[str]:
    for field in ("series_uid", "series_instance_uid", "SeriesInstanceUID"):
        val = entry.get(field)
        if val:
            text = str(val).strip()
            if text:
                return text
    return None


def _ref_from_entry(
    display_key: str,
    entry: Mapping[str, Any],
    primary_study_uid: str,
    source_root: Optional[str],
) -> Optional[SeriesRef]:
    """Build a ref from a ``_server_series_info`` entry, or None if it is not authoritative.

    Requires BOTH ``series_path`` AND ``_orig_series_number`` — only the multi-study index
    builder stamps the latter, so a single-study entry correctly returns None here and the
    caller falls through to the ``derived`` path (keeping single-study byte-identical).
    """
    orig = entry.get("_orig_series_number")
    path = entry.get("series_path")
    if not orig or not path:
        return None
    study_uid = str(entry.get("study_uid") or primary_study_uid or "").strip()
    if not study_uid:
        return None
    try:
        slot = int(entry.get("_study_slot", 0) or 0)
    except (TypeError, ValueError):
        slot = 0
    # C3: the number's TEXT is preserved exactly as stamped ("02" stays "02").
    return SeriesRef(
        display_key=str(display_key),
        study_uid=study_uid,
        series_number=str(orig),
        series_path=str(path),
        series_uid=_entry_series_uid(entry),
        study_slot=slot,
        source="entry",
    )


def build_series_ref_table(
    server_series_info: Optional[Mapping[str, Any]],
    primary_study_uid: str,
    source_root: Optional[str] = None,
) -> Dict[str, SeriesRef]:
    """Build the display_key -> SeriesRef table ONCE, where the series info lands.

    Called from the same place that already builds ``_server_series_info`` (the multi-study
    index rebuild / the metadata sink), so per-load resolution becomes an **O(1) dict
    lookup instead of a re-computation** — that is the "speed" half of the directive: the
    ``Path.exists()`` probes and the guard scans leave the click -> first-image path.

    Only entries that are AUTHORITATIVE (carry ``series_path`` + ``_orig_series_number``)
    produce a ref here. Everything else is resolved lazily by :func:`resolve_series_ref`,
    which is what keeps single-study tabs byte-identical.
    """
    table: Dict[str, SeriesRef] = {}
    if not isinstance(server_series_info, Mapping):
        return table
    primary = str(primary_study_uid or "").strip()
    for key, entry in server_series_info.items():
        if not isinstance(entry, Mapping):
            continue
        ref = _ref_from_entry(str(key), entry, primary, source_root)
        if ref is not None:
            table[str(key)] = ref
    return table


def _ordered_studies(
    studies_index: Optional[Mapping[str, Any]],
    primary_study_uid: str,
    slot_order: Optional[Sequence[str]] = None,
) -> List[str]:
    """The STABLE slot order (primary always slot 0), matching the index builder.

    The stable order matters: a study's slot — and therefore its offset keys — must NOT
    shift when another previous exam is merged later, or the SAME key would resolve to two
    different studies over time and a drag could load the WRONG study.
    """
    studies = dict(studies_index or {})
    primary = str(primary_study_uid or "").strip()
    if slot_order:
        ordered = [su for su in slot_order if su in studies]
        if ordered:
            return ordered
    return ([primary] if primary in studies else []) + sorted(
        su for su in studies.keys() if su != primary
    )


def resolve_series_ref(
    display_key: Any,
    table: Optional[Mapping[str, SeriesRef]] = None,
    *,
    server_series_info: Optional[Mapping[str, Any]] = None,
    primary_study_uid: str = "",
    source_root: Optional[str] = None,
    studies_index: Optional[Mapping[str, Any]] = None,
    slot_order: Optional[Sequence[str]] = None,
) -> Optional[SeriesRef]:
    """Resolve ONE display key to its :class:`SeriesRef`. Never raises.

    Resolution order — each tier mirrors a real failure the legacy code learned to handle:

    1. **the prebuilt table** (O(1), the common path);
    2. **the live entry** (the table may predate a merge);
    3. **the slot fallback** for an OFFSET key whose entry a later rebuild dropped — without
       this, such a key silently fell back to the PRIMARY study path and the series would
       not load ("a later study's series won't load, the previous image stays");
    4. **derived** — the ordinary single-study case. Path is INFERRED, so the ref is marked
       non-authoritative (see :attr:`SeriesRef.is_authoritative`).
    """
    key = str(display_key)
    primary = str(primary_study_uid or "").strip()

    # 1. prebuilt table
    if table:
        ref = table.get(key)
        if ref is not None:
            return ref

    # 2. live entry
    if isinstance(server_series_info, Mapping):
        entry = server_series_info.get(key)
        if entry is None:
            entry = server_series_info.get(display_key)
        if isinstance(entry, Mapping):
            ref = _ref_from_entry(key, entry, primary, source_root)
            if ref is not None:
                return ref

    key_int = parse_series_number(key)  # C1: tolerant, never raises
    if key_int is None:
        return None

    # 3. offset-key slot fallback (entry dropped by a later rebuild)
    if key_int >= MULTISTUDY_OFFSET and source_root:
        slot = key_int // MULTISTUDY_OFFSET
        orig = key_int % MULTISTUDY_OFFSET
        ordered = _ordered_studies(studies_index, primary, slot_order)
        if 0 <= slot < len(ordered):
            study_uid = str(ordered[slot])
            return SeriesRef(
                display_key=key,
                study_uid=study_uid,
                series_number=str(orig),
                series_path=str(PurePath(source_root) / study_uid / str(orig)),
                series_uid=None,
                study_slot=slot,
                source="slot_fallback",
            )
        return None  # out of range: refuse to guess (never fall back to the primary study)

    # 4. derived (single-study / plain key with no entry) — identity only, path INFERRED
    if not primary or not source_root:
        return None
    return SeriesRef(
        display_key=key,
        study_uid=primary,
        series_number=key,
        series_path=str(PurePath(source_root) / primary / key),
        series_uid=None,
        study_slot=0,
        source="derived",
    )


def shadow_compare(
    ref: Optional[SeriesRef],
    *,
    legacy_study_path: Any = None,
    legacy_series_number: Any = None,
    legacy_study_pk: Any = None,
) -> Dict[str, Any]:
    """Compare the ref against what the LEGACY derivation produced. Pure; never raises.

    This is the **regression oracle** for the whole migration (plan §5): during Phase 0
    nothing consumes the ref, so a ``mismatch`` means the TABLE is wrong and must be fixed
    before any consumer is migrated. Once a stage is consuming the ref, the same comparison
    keeps reporting how often the OLD derivation *would have been* wrong — i.e. it is a
    permanent, production record of the bug class, not a one-off check.

    Returns ``{'mismatch': bool, 'fields': [...], 'detail': {...}}``. ``ref is None`` is
    NOT a mismatch (nothing to say); neither is a ``None`` legacy value (not yet computed).
    """
    out: Dict[str, Any] = {"mismatch": False, "fields": [], "detail": {}}
    if ref is None:
        return out

    def _norm_path(value: Any) -> str:
        if value in (None, ""):
            return ""
        return str(PurePath(str(value))).rstrip("\\/").lower()

    if legacy_study_path not in (None, ""):
        legacy_p, ref_p = _norm_path(legacy_study_path), _norm_path(ref.study_path)
        if legacy_p != ref_p:
            out["fields"].append("study_path")
            out["detail"]["study_path"] = {"legacy": str(legacy_study_path), "ref": ref.study_path}

    if legacy_series_number not in (None, ""):
        if str(legacy_series_number).strip() != str(ref.series_number).strip():
            out["fields"].append("series_number")
            out["detail"]["series_number"] = {
                "legacy": str(legacy_series_number), "ref": ref.series_number,
            }

    # Only meaningful once the ref actually carries a resolved pk.
    if ref.study_pk is not None and legacy_study_pk is not None:
        if str(legacy_study_pk) != str(ref.study_pk):
            out["fields"].append("study_pk")
            out["detail"]["study_pk"] = {"legacy": str(legacy_study_pk), "ref": str(ref.study_pk)}

    out["mismatch"] = bool(out["fields"])
    return out
