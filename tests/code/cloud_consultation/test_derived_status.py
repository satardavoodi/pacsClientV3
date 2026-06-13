"""Guards for the derived consultation capabilities (owner directive 2026-06-11).

Qt-free: ``consultation_capabilities`` is pure derived state — internal
consultations need license + identity only; external additionally needs the
hub Google identity. The status text is the dropdown's one-line summary.
"""

import pytest

from modules.cloud_consultation.ui.derived_status import (
    STATUS_ACTIVE,
    STATUS_INTERNAL_ONLY,
    STATUS_NOT_ENABLED,
    consultation_capabilities,
)


def caps(linked, hub, module=True):
    return consultation_capabilities(
        "user@test",
        identity_linked=linked,
        hub_available=hub,
        module_available=module,
    )


# ── the full linked/hub/module matrix ──────────────────────────────────────────
@pytest.mark.parametrize(
    "linked,hub,module,internal,external,status",
    [
        # linked + hub + license → fully active
        (True, True, True, True, True, STATUS_ACTIVE),
        # linked, NO hub → internal only (license + identity, no hub needed)
        (True, False, True, True, False, STATUS_INTERNAL_ONLY),
        # not linked → nothing enabled regardless of hub
        (False, True, True, False, False, STATUS_NOT_ENABLED),
        (False, False, True, False, False, STATUS_NOT_ENABLED),
        # module gate off → nothing enabled even when linked + hub
        (True, True, False, False, False, STATUS_NOT_ENABLED),
        (True, False, False, False, False, STATUS_NOT_ENABLED),
        (False, False, False, False, False, STATUS_NOT_ENABLED),
    ],
)
def test_capability_matrix(linked, hub, module, internal, external, status):
    c = caps(linked, hub, module)
    assert c["identity_linked"] is linked
    assert c["consultation_active"] is linked  # the link implies authorization
    assert c["hub_available"] is hub
    assert c["internal_enabled"] is internal
    assert c["external_enabled"] is external
    assert c["status_text"] == status


def test_external_always_implies_internal_and_hub():
    for linked in (True, False):
        for hub in (True, False):
            for module in (True, False):
                c = caps(linked, hub, module)
                if c["external_enabled"]:
                    assert c["internal_enabled"] and c["hub_available"]
                if c["internal_enabled"]:
                    assert c["identity_linked"]


def test_result_shape_is_exactly_the_contract():
    c = caps(True, True)
    assert set(c) == {
        "identity_linked", "consultation_active", "hub_available",
        "internal_enabled", "external_enabled", "status_text",
    }
    assert all(isinstance(c[k], bool) for k in c if k != "status_text")
    assert isinstance(c["status_text"], str) and c["status_text"]


def test_truthy_inputs_are_normalised_to_bools():
    c = consultation_capabilities(
        "user@test", identity_linked=1, hub_available="", module_available=object()
    )
    assert c["identity_linked"] is True
    assert c["hub_available"] is False
    assert c["internal_enabled"] is True
    assert c["status_text"] == STATUS_INTERNAL_ONLY


def test_live_probes_never_raise_for_unknown_user():
    # No overrides: every probe runs live and must fail soft, never raise.
    c = consultation_capabilities("nonexistent-user-for-derived-status-test")
    assert isinstance(c, dict) and set(c) >= {"external_enabled", "status_text"}
