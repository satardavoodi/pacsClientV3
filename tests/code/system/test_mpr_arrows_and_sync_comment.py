"""Guards for the MPR arrow-buttons fix + Patient-Tab sync comment (2026-06-06).

1. MPR one-shot transforms (rotate left/right, flip H/V): the toolbar's MPR
   branch used to park `tool_selected` on the transform enum, so the NEXT
   click hit the "already active → clear and return" branch and was EATEN
   (every other arrow click dead) while also destroying the MPR-active
   state. The branch now applies the transform on EVERY click and never
   occupies `tool_selected`.

2. Patient-Tab sync comment: the status dropdown gains a comment box that
   rides the SAME server mechanism as the Main-Page Report popup
   (`patient_widget._change_report_status` → socket report-status service —
   no second storage). A status pick sends status+comment together; a
   comment typed WITHOUT a status pick is flushed as a comment-only update
   when Sync / Sync-and-Close runs.
"""
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TOOLBAR = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
            / "patient_toolbar" / "toolbar_manager.py")
_MPR_LAYOUT = (_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_layout.py")
_MPR_TOOLS = (_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_measurement_tools.py")
_MPR_CROSSHAIR = (_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
                  / "_mpr_crosshair_interact.py")


def _code() -> str:
    src = _TOOLBAR.read_text(encoding="utf-8", errors="ignore")
    return "\n".join(line.split("#", 1)[0] for line in src.splitlines())


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


# ─────────────────────────────── 1. MPR arrows ───────────────────────────

def test_mpr_transforms_apply_on_every_click():
    code = _code()
    for tool in ("ROTATION_LEFT", "ROTATION_RIGHT", "FLIP_HORIZONTAL", "FLIP_VERTICAL"):
        assert f"apply_view_transform(self.tool_access.{tool})" in code, tool
        # tool_selected must be assigned the enum only ONCE (the legacy 2D
        # branch) — the MPR branch no longer parks state on one-shots.
        assignments = code.count(f"self.tool_selected = self.tool_access.{tool}")
        assert assignments == 1, (
            f"{tool}: expected 1 assignment (2D branch only), found {assignments} — "
            "the MPR one-shot branch must not occupy tool_selected"
        )


def test_mpr_transform_branch_has_no_eaten_click_return():
    """The old MPR branch pattern cleared state and returned WITHOUT
    transforming when tool_selected equaled the transform enum."""
    src = _TOOLBAR.read_text(encoding="utf-8", errors="ignore")
    for tool in ("ROTATION_LEFT", "ROTATION_RIGHT", "FLIP_HORIZONTAL", "FLIP_VERTICAL"):
        # locate the MPR branch of this toggle
        marker = f"apply_view_transform(self.tool_access.{tool})"
        idx = src.index(marker)
        branch = src[max(0, idx - 1200):idx]
        assert f"if self.tool_selected == self.tool_access.{tool}:" not in branch, (
            f"{tool}: eaten-click early-return is back in the MPR branch"
        )


# ───────────────────────── 2. sync-workflow comment ─────────────────────

def test_status_dropdown_has_comment_box_wired():
    code = _code()
    assert "_pending_report_comment" in code
    assert "Comment (optional):" in _TOOLBAR.read_text(encoding="utf-8", errors="ignore")
    # status pick sends the typed comment through the same server call
    assert "comment=user_comment" in code
    # sync flushes a comment-only change before uploading
    assert "_flush_pending_report_comment(study_uid)" in code


def test_status_change_does_not_overwrite_comment_with_placeholder():
    """FIX (2026-06-09): a pure status change must NOT post placeholder text to
    the comment endpoint — that clobbered the doctor's real server-side comment.
    The typed comment (possibly empty) is sent as-is; an empty comment is then
    skipped by _change_report_status so the server comment is left intact."""
    code = _code()
    assert "Status changed via toolbar dropdown" not in code, (
        "placeholder comment text must not be sent — it overwrites the real comment"
    )
    assert "comment=user_comment or" not in code


def test_same_status_click_still_syncs_typed_comment():
    """FIX (2026-06-09): clicking the CURRENT status with a comment typed must
    still sync the comment (comment-only flush) instead of early-returning and
    dropping it."""
    src = _TOOLBAR.read_text(encoding="utf-8", errors="ignore")
    start = src.index("def _change_status_from_dropdown")
    end = src.index("def _sync_and_go_home", start) if "_sync_and_go_home" in src[start:] else start + 4000
    branch = src[start:end]
    same_idx = branch.index("new_status == current_status")
    # within the same-status branch, the comment-only flush must be invoked
    same_block = branch[same_idx:same_idx + 700]
    assert "_flush_pending_report_comment" in same_block, (
        "same-status branch must flush the typed comment, not silently skip it"
    )


def test_prefill_only_marks_synced_comment_as_already_sent():
    """FIX (2026-06-09): the dropdown's 'already sent' marker
    (_status_dropdown_initial_comment) must come from a cache entry that is
    actually sync_state=='synced'. A locally-saved-but-unsynced comment must NOT
    suppress the next Sync."""
    src = _TOOLBAR.read_text(encoding="utf-8", errors="ignore")
    assert "_synced_comment" in src
    assert "sync_state') or '') == 'synced'" in src or "== 'synced'" in src
    assert "self._status_dropdown_initial_comment = _synced_comment" in src


# ── Path 2 (viewer) comment sync is observable + uses the shared endpoint ──

def test_pw_panels_comment_sync_logs_and_uses_shared_endpoint():
    """The viewer's _change_report_status (Path 2) must (a) call the SAME shared
    _sync_comment_to_server endpoint as the Main Page and (b) emit structured
    logger output so the sync is visible in app.log (it previously only
    print()ed, making the viewer path invisible)."""
    pw_panels = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui"
                 / "patient_ui" / "patient_widget_core" / "_pw_panels.py")
    src = pw_panels.read_text(encoding="utf-8", errors="ignore")
    assert "logger = logging.getLogger(__name__)" in src
    assert "_sync_comment_to_server(patient_id, comment_text)" in src
    # outcome is logged (not just printed)
    assert "comment synced to server" in src
    assert "comment server sync FAILED" in src
    # the start-of-change structured trace mirrors the Main-Page logger
    assert "[PatientWidget] status change" in src


def test_flush_sends_comment_only_update_via_same_mechanism():
    """Behavioral: run the unbound flush method against a stub toolbar."""
    import importlib.util

    # Load just the method source by executing it against a stub — avoid
    # importing the heavy toolbar module. Extract the function body.
    src = _TOOLBAR.read_text(encoding="utf-8", errors="ignore")
    start = src.index("def _flush_pending_report_comment")
    end = src.index("def _start_patient_sync", start)
    fn_src = "    " + src[start:end].rstrip() + "\n"
    # the flush now emits logger.info on skip/flush — provide a logger so the
    # isolated exec of the repo source doesn't NameError.
    namespace = {"logger": __import__("logging").getLogger("test")}
    exec("class _Holder:\n" + fn_src, namespace)  # noqa: S102 — test-local exec of repo source
    flush = namespace["_Holder"]._flush_pending_report_comment

    calls = []

    class _PatientWidget:
        report_status = "pending"

        def _change_report_status(self, **kwargs):
            calls.append(kwargs)
            return True

    class _Stub:
        _pending_report_comment = "follow up with prior CT"
        _status_dropdown_initial_comment = ""
        patient_widget = _PatientWidget()

    stub = _Stub()
    flush(stub, "1.2.3")
    assert len(calls) == 1
    sent = calls[0]
    assert sent["comment"] == "follow up with prior CT"
    assert sent["old_status"] == sent["new_status"] == "pending"  # comment-only
    assert sent["study_uid"] == "1.2.3"
    # idempotent: second flush with unchanged text is a no-op
    flush(stub, "1.2.3")
    assert len(calls) == 1


def test_flush_noop_when_empty_or_unchanged():
    src = _TOOLBAR.read_text(encoding="utf-8", errors="ignore")
    start = src.index("def _flush_pending_report_comment")
    end = src.index("def _start_patient_sync", start)
    fn_src = "    " + src[start:end].rstrip() + "\n"
    namespace = {"logger": __import__("logging").getLogger("test")}
    exec("class _Holder:\n" + fn_src, namespace)  # noqa: S102
    flush = namespace["_Holder"]._flush_pending_report_comment

    calls = []

    class _PatientWidget:
        report_status = "completed"

        def _change_report_status(self, **kwargs):
            calls.append(kwargs)
            return True

    class _Stub:
        _pending_report_comment = ""
        _status_dropdown_initial_comment = ""
        patient_widget = _PatientWidget()

    flush(_Stub(), "1.2.3")          # nothing typed
    stub2 = _Stub()
    stub2._pending_report_comment = "same"
    stub2._status_dropdown_initial_comment = "same"
    flush(stub2, "1.2.3")            # unchanged from loaded/sent value
    assert calls == []


# ───────────────── 3. MPR toolbar ARROW tool (2026-06-06) ────────────────
# The toolbar ARROW button used to route to the MPR caption tool, which
# instantly spawned a "Text" caption box plus a default diagonal leader
# line in every pane (the reported "arrow doesn't draw correctly"). It now
# places a real two-click vtkLeaderActor2D arrow.

def test_toggle_arrow_mpr_branch_uses_activate_arrow_not_caption():
    src = _TOOLBAR.read_text(encoding="utf-8", errors="ignore")
    start = src.index("def toggle_arrow")
    # bound the search to the MPR branch (ends at the normal-VTK section)
    end = src.index("Normal VTKWidget mode", start)
    branch = _strip_comments(src[start:end])
    assert "mpr_widget.activate_arrow()" in branch, (
        "toggle_arrow MPR branch must call activate_arrow()"
    )
    assert "mpr_widget.activate_caption()" not in branch, (
        "toggle_arrow MPR branch must NOT call activate_caption() — that is "
        "the source of the wrong 'Text' arrows"
    )


def test_mpr_layout_exposes_activate_arrow_delegating_to_tool():
    code = _strip_comments(_MPR_LAYOUT.read_text(encoding="utf-8", errors="ignore"))
    assert "def activate_arrow(self):" in code
    assert "activate_arrow_tool('all')" in code


def test_measurement_tools_arrow_uses_leader_actor_not_caption():
    raw = _MPR_TOOLS.read_text(encoding="utf-8", errors="ignore")
    code = _strip_comments(raw)
    # the arrow tool exists and builds a vtkLeaderActor2D (a real arrow),
    # never a caption "Text" box
    assert "def activate_arrow_tool" in code
    assert "def _activate_arrow_on_view" in code
    assert "def _create_arrow_actor" in code
    assert "vtkLeaderActor2D()" in code
    assert "SetArrowStyleToFilled" in code
    # two-click placement: a tail point is stashed, then the head completes
    assert "_arrow_pending_tail" in code
    assert "LeftButtonPressEvent" in code
    # clear_measurements must clean arrows (raw actors, removed from renderer)
    clear_start = code.index("def clear_measurements")
    clear_body = code[clear_start:clear_start + 1600]
    assert "'arrow'" in clear_body
    assert "RemoveActor2D" in clear_body
    # deactivate must drop the click observers so they don't outlive the tool
    assert "_deactivate_arrow_placement" in code
    # the abort uses the command tag, not the (method-less) interactor
    assert "GetCommand(" in code


def test_mpr_arrow_head_is_proportionate_to_body():
    """The filled head must be large enough to read against the line body
    (reported 'body thick / head small'): vtkLeaderActor2D sizes the head as a
    fraction of the leader length, so both ArrowLength and ArrowWidth are bumped,
    and the body line width is capped so a thick configured width can't dwarf it."""
    code = _strip_comments(_MPR_TOOLS.read_text(encoding="utf-8", errors="ignore"))
    assert "SetArrowLength(0.15)" in code
    assert "SetArrowWidth(0.12)" in code
    assert "SetArrowLength(0.06)" not in code   # the old tiny head is gone
    # body width capped (thinner user settings still honored)
    assert "min(float(st.line_width), 2.0)" in code


def test_crosshair_yields_to_active_arrow_tool():
    """The crosshair press handler must yield while the arrow tool is
    placing, so an arrow click doesn't also move the crosshair."""
    raw = _MPR_CROSSHAIR.read_text(encoding="utf-8", errors="ignore")
    start = raw.index("def on_left_button_press")
    head = _strip_comments(raw[start:start + 1200])
    assert "current_tool" in head and "'arrow'" in head, (
        "on_left_button_press must check measurement_tools.current_tool == 'arrow'"
    )
    # the guard must short-circuit (return) before the crosshair acts
    guard_idx = head.index("current_tool")
    assert "return" in head[guard_idx:guard_idx + 200]
