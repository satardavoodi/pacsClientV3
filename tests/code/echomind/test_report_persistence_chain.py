"""Guard: EchoMind's generated reports actually reach `ai_reports` (Phase A).

BACKGROUND — two separate defects, both silent:

1. `ai_reports` had 0 rows despite a writer existing. `ai_chat_pages` persists via

       fn = getattr(U, "ai_insert_report", None) or getattr(U, "ai_upsert_report", None)
       if callable(fn): fn(...)

   and `fn` was ALWAYS None, because `database/manager.py` had no passthrough.
   A `getattr`-guarded call that can never resolve is indistinguishable from one
   that works: no exception, no log, no row. Every report survived only as an
   HTML bubble.

2. While fixing (1) I pushed a copy of `database/manager.py` based on a stale
   snapshot, which silently deleted `ai_count_messages_by_session` — the
   2026-07-31 panel-open N+1 fix. That name is imported EAGERLY by
   `PacsClient/utils/__init__.py`, and `PacsClient/utils/db_manager` is a pure
   lazy forwarder with no fallback, so the deletion did not degrade one feature:
   it made `import PacsClient.utils` raise ImportError for the whole app.

The first test below is the one that would have caught (2) in under a second.

These are static (AST/text) checks on purpose — importing `PacsClient.utils`
pulls in Qt and the DB layer, which is too heavy for the code suite.
"""

import ast
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_FACADE = os.path.join(_ROOT, "PacsClient", "utils", "__init__.py")
_MANAGER = os.path.join(_ROOT, "database", "manager.py")
_IMPL = os.path.join(_ROOT, "database", "ai_sessions_db.py")
_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")


def _read(path):
    with open(path, encoding="utf-8-sig") as fh:
        return fh.read()


def _bound_names(src):
    """Every module-level name `src` binds: def, class, import, assignment."""
    tree = ast.parse(src)
    out = {n.name for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.Assign):
            out.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return out


def _facade_imports():
    """Names `PacsClient/utils/__init__` pulls from the db_manager shim."""
    names = []
    for node in ast.walk(ast.parse(_read(_FACADE))):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "db_manager":
            names += [a.name for a in node.names]
    return names


# ── 1. the whole-app invariant ───────────────────────────────────────────────

def test_every_facade_export_resolves_in_the_manager():
    """`PacsClient.utils.db_manager` is a lazy shim that forwards to
    `database.manager` and raises AttributeError when the name is absent — there
    is no fallback and no `__getattr__` in the manager to catch the miss. So a
    name in the facade's import list that the manager does not define is not a
    dormant export: it is an ImportError at `import PacsClient.utils`, which is
    on the startup path of the entire workstation.
    """
    wanted = _facade_imports()
    assert wanted, "the facade's db_manager import block moved — re-anchor this guard"
    missing = sorted(set(wanted) - _bound_names(_read(_MANAGER)))
    assert not missing, (
        "database/manager.py does not define %r, which PacsClient/utils/__init__ "
        "imports eagerly — `import PacsClient.utils` will raise ImportError and the "
        "app will not start" % (missing,)
    )


def test_the_shim_really_has_no_fallback():
    """The premise of the test above. If a fallback is ever added, that test's
    failure message becomes wrong and should be rewritten, not deleted."""
    src = _read(os.path.join(_ROOT, "PacsClient", "utils", "db_manager.py"))
    assert "__getattr__" in src and "raise AttributeError" in src


@pytest.mark.parametrize("name", [
    "ai_insert_report",
    "ai_fetch_reports_for_session",
    "ai_fetch_reports_map_for_session",
    "ai_fetch_reports_for_study",
    "ai_count_messages_by_session",
])
def test_the_report_chain_is_complete_end_to_end(name):
    """impl -> manager -> facade. A break at ANY link turns the guarded call site
    into a no-op (or, for the eager list, into a startup crash)."""
    assert f"def {name}" in _read(_IMPL), f"{name} is missing from ai_sessions_db"
    assert f"def {name}" in _read(_MANAGER), f"{name} has no manager passthrough"
    assert name in _facade_imports(), f"{name} is not exported by PacsClient.utils"


# ── 2. the audit columns ─────────────────────────────────────────────────────

@pytest.mark.parametrize("col", ["physician_id", "model", "modality", "corrects_msg_id"])
def test_ai_insert_report_accepts_the_audit_fields(col):
    tree = ast.parse(_read(_IMPL))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "ai_insert_report")
    kwonly = [a.arg for a in fn.args.kwonlyargs] + [a.arg for a in fn.args.args]
    assert col in kwonly, f"ai_insert_report cannot record {col}"


@pytest.mark.parametrize("col", ["physician_id", "model", "modality", "corrects_msg_id"])
def test_the_insert_actually_writes_the_audit_columns(col):
    """Accepting a kwarg and storing it are different things, and SQLite will not
    complain about the difference: the first cut of this change extended the
    signature but not the INSERT, so rows written with physician_id='vahid' read
    back NULL. Silent data loss that only a round-trip revealed."""
    src = _read(_IMPL)
    i = src.index("def ai_insert_report")
    body = src[i:src.index("\ndef ", i + 10)]
    j = body.index("INSERT INTO ai_reports")
    stmt = body[j:body.index(")", body.index("VALUES", j))]
    assert col in stmt, (
        f"ai_insert_report takes {col} but never writes it — the column stays NULL"
    )


def test_the_insert_placeholders_match_the_column_count():
    """A column/placeholder mismatch is the classic way this breaks after an edit."""
    src = _read(_IMPL)
    i = src.index("def ai_insert_report")
    body = src[i:src.index("\ndef ", i + 10)]
    j = body.index("INSERT INTO ai_reports")
    cols = body[body.index("(", j) + 1:body.index(")", j)]
    values = body[body.index("VALUES(", j) + 7:body.index(")", body.index("VALUES(", j))]
    assert len([c for c in cols.split(",") if c.strip()]) == values.count("?"), (
        "the audited INSERT names %d columns but binds %d placeholders"
        % (len([c for c in cols.split(",") if c.strip()]), values.count("?"))
    )


def test_a_missing_audit_column_cannot_lose_the_report():
    """Report content is the physician's work; attribution is bookkeeping. On an
    install whose ALTER did not land, the write must degrade to the original
    columns rather than raise and discard the report."""
    src = _read(_IMPL)
    i = src.index("def ai_insert_report")
    body = src[i:src.index("\ndef ", i + 10)]
    assert body.count("INSERT INTO ai_reports") == 2, (
        "there is no fallback INSERT — one failed ALTER would now cost the report "
        "itself, not just its metadata"
    )
    assert "except Exception" in body[body.index("INSERT INTO ai_reports"):]


@pytest.mark.parametrize("col", ["physician_id", "model", "modality", "corrects_msg_id"])
def test_the_migration_adds_the_audit_columns(col):
    """`ai_reports` predates these columns on every existing install, so they must
    arrive by ALTER, not only by CREATE TABLE."""
    src = _read(_IMPL)
    i = src.index("def ai_ensure_schema")
    body = src[i:src.index("\ndef ", i + 10)]
    assert col in body, f"{col} is never added to an existing ai_reports"
    assert "ADD COLUMN" in body


def test_the_migration_cannot_break_startup():
    """A failed ALTER must never stop the schema pass — an older DB missing one
    column should lose that column's audit value, not the application."""
    src = _read(_IMPL)
    i = src.index("def ai_ensure_schema")
    body = src[i:src.index("\ndef ", i + 10)]
    j = body.index("ADD COLUMN")
    window = body[max(0, j - 400):j + 200]
    assert window.count("try:") >= 2 and "except Exception" in window


# ── 3. the call site records who/what ────────────────────────────────────────

def _call_site():
    src = _read(_PAGES)
    i = src.index('if origin == "report" and (not is_user) and raw_report_for_db:')
    return src[i:i + 1600]


@pytest.mark.parametrize("kwarg", ["kind=", "physician_id=", "model=", "modality="])
def test_the_persisted_row_carries_attribution(kwarg):
    assert kwarg in _call_site(), (
        f"the report is stored without {kwarg.rstrip('=')} — the row cannot be "
        "attributed later, which is the entire point of Phase A"
    )


def test_a_correction_is_stored_as_a_correction():
    """A correction is the physician saying 'not that — this'. It is the highest
    signal record we keep, and it is only usable if it is separable from a fresh
    generation."""
    src = _read(_PAGES)
    i = src.index("def _send_report_correction")
    j = src.index("\n    def ", i + 10)
    assert '_pending_report_kind = "correction"' in src[i:j], (
        "the correction path no longer marks the next report — corrections and "
        "fresh reports will be indistinguishable in ai_reports"
    )
    assert '_pending_report_kind' in _call_site()


def test_the_pending_kind_is_consumed_once():
    """It must be cleared after use, or every later report in the session inherits
    'correction'."""
    body = _call_site()
    assert "_pending_report_kind = None" in body, "the marker is never reset"


def test_persistence_never_breaks_the_chat():
    """Storing a report is bookkeeping. It must not be able to take down the
    bubble the physician is waiting for."""
    src = _read(_PAGES)
    i = src.index('if origin == "report" and (not is_user) and raw_report_for_db:')
    tail = src[i:i + 1800]
    assert "except Exception" in tail, "the persistence block is not guarded"
