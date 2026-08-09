"""Guard: chat metadata is seeded wherever a session is born, and a correction
records which report it corrected (2026-08-08).

TWO DORMANT FEATURES, FOUND BY AUDIT RATHER THAN BY FAILURE.

1. `ai_session_meta` did not exist in the production database — the step-1 metadata
   foundation had never run once since it landed. `_seed_session_metadata` was called
   only from `_new_session`, which mints `report-<hex8>` (the "New chat" button).
   Normal reporting mints `report-<epoch>-<hex6>` in `_ensure_local_session`, and a
   study's first chat mints `local-<hex8>` in `_refresh_sessions_for_current_study`.
   Neither seeded. Every session in the database uses one of those two formats.

   Worth recording: the first diagnosis was that `save_auto` never called
   `ensure_schema`. That was WRONG — `save_auto` -> `_write` -> `ensure_schema()` on its
   first line. The chain was always correct; nothing was ever calling it. The test below
   pins the WIRING, which is where the defect actually was.

2. `corrects_msg_id` was always NULL. `kind='correction'` was recorded, but the link to
   the corrected report was not, because the Correction dropdown carries the report text
   and a label — never a msg_id.

Both failed silently, which is why they need structural guards rather than trust.
"""

import ast
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
_META = os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py")
_NT = os.path.join(_ROOT, "modules", "EchoMind", "normal_templates.py")


def _read(p):
    with open(p, encoding="utf-8-sig") as fh:
        return fh.read()


def _functions(src):
    """{name: source} for every function in the module."""
    lines = src.split("\n")
    return {n.name: "\n".join(lines[n.lineno - 1:n.end_lineno])
            for n in ast.walk(ast.parse(src))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


# ── 1. seed wherever a session is born ───────────────────────────────────────

def _minting_functions():
    """Functions that BOTH mint a fresh id and register it as a session."""
    return {name: body for name, body in _functions(_read(_PAGES)).items()
            if "ai_upsert_session(" in body and "uuid.uuid4()" in body}


def test_there_are_session_minting_sites_to_check():
    mint = _minting_functions()
    assert len(mint) >= 3, (
        "the session-minting sites moved — re-anchor this guard before trusting it "
        f"(found {sorted(mint)})"
    )


@pytest.mark.parametrize("name", sorted(_minting_functions()))
def test_every_minting_site_seeds_metadata(name):
    """THE test that would have caught it. Seeding attached to one of three birth
    paths is seeding that never runs: the button nobody presses was wired, and the two
    paths every real session goes through were not."""
    body = _minting_functions()[name]
    assert "_seed_session_metadata" in body, (
        f"{name} mints a session but never seeds its metadata — that chat will have no "
        "case context, and if it is the only birth path in use the whole feature is dead"
    )


def test_the_seed_helper_cannot_break_chat_creation():
    body = _functions(_read(_PAGES))["_seed_session_metadata"]
    assert "try:" in body and "except Exception" in body, "seeding must be fully swallowed"
    assert "populate_for_chat" in body


def test_the_storage_layer_creates_its_own_table():
    """The premise the wiring depends on: once seeding is called, the table appears.
    `_write` is the single writer and must ensure the schema before touching it."""
    fns = _functions(_read(_META))
    assert "ensure_schema" in fns["_write"], "_write no longer guarantees the table exists"
    assert "_write" in fns["save_auto"], "save_auto bypasses the writer that ensures schema"
    assert "save_auto" in fns["populate_for_chat"]


# ── 2. a correction records what it corrected ────────────────────────────────

def test_the_correction_path_resolves_its_source_report():
    src = _read(_PAGES)
    fns = _functions(src)
    assert "_resolve_corrected_msg_id" in fns, "the resolver is gone"
    send = fns["_send_report_correction"]
    assert '_pending_report_kind = "correction"' in send
    assert "_pending_corrects_msg_id = self._resolve_corrected_msg_id" in send


def test_the_resolver_refuses_to_guess():
    """A WRONGLY linked correction corrupts the very history the column exists to make
    analysable. Absent or ambiguous must both yield None."""
    body = _functions(_read(_PAGES))["_resolve_corrected_msg_id"]
    assert "len(hits) == 1" in body, "the ambiguity guard is gone — it may now guess"
    assert body.count("return None") >= 2, "the empty/failure paths no longer return None"
    assert "except Exception" in body, "resolution must never break sending a correction"


def test_the_link_reaches_the_database():
    src = _read(_PAGES)
    i = src.index('if origin == "report" and (not is_user) and raw_report_for_db:')
    seg = src[i:i + 2000]
    assert "corrects_msg_id=_corrects" in seg, "the resolved link is never passed"
    assert "_pending_corrects_msg_id = None" in seg, (
        "the marker is not reset — every later report in the session would claim to "
        "correct the same one"
    )


def test_ai_insert_report_still_accepts_the_link():
    impl = _read(os.path.join(_ROOT, "database", "ai_sessions_db.py"))
    fn = next(n for n in ast.parse(impl).body
              if isinstance(n, ast.FunctionDef) and n.name == "ai_insert_report")
    args = [a.arg for a in fn.args.kwonlyargs] + [a.arg for a in fn.args.args]
    assert "corrects_msg_id" in args


# ── 3. every UI modality can hold a normal template ──────────────────────────

def test_every_ui_modality_can_be_filed_in_the_template_library():
    """OB joined the modality list on 2026-08-06 and was missing here, so an OB normal
    template could not be saved at all. Read both lists from source so the next added
    modality fails here instead of silently having nowhere to go."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_em_nt", _NT)
    nt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nt)

    spec2 = importlib.util.spec_from_file_location(
        "_em_cfg2", os.path.join(_ROOT, "modules", "EchoMind", "ai_chat_config.py"))
    cfg = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(cfg)

    unfilable = [m for m in cfg.REPORT_MODALITIES if nt.canonical_modality(m) == ""]
    assert not unfilable, f"no template slot for {unfilable}"


@pytest.mark.parametrize("spelling", [
    "OBSTETRIC ULTRASOUND", "obstetric ultrasound", "OB ultrasound", "ob us", "obstetric",
])
def test_ob_spellings_resolve(spelling):
    import importlib.util
    spec = importlib.util.spec_from_file_location("_em_nt2", _NT)
    nt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nt)
    assert nt.canonical_modality(spelling) == "OBSTETRIC ULTRASOUND"
