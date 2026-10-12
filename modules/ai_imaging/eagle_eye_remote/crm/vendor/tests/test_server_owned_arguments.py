"""`data_root` is injected by the server, and only where the tool declares it.

⚠️ THE REGRESSION THIS FILE EXISTS FOR. `/api/dispatch` injected `data_root`
into every call. That was harmless while validation ignored inputs it did not
recognise; the moment validation began REFUSING them, all six tools that read
the local database started failing with

    Unknown input(s): data_root. This tool accepts: dateFrom, dateTo, limit

— an error caused entirely by the server talking to itself, and one the unit
suite could not see because it never went through the HTTP adapter. It was found
by smoking the deployed build against the real database, which is the only place
it existed.
"""

from __future__ import annotations

from reception_crm.adapters.http_api import with_default_data_root
from reception_crm.core.registry import default_registry
from reception_crm.core.validation import validate_input

#: Reads the vendor's HTTP API through a snapshot store, so it needs the root.
NEEDS_ROOT = "daily-summary"
#: Reads the reception database directly, so it does not.
DOES_NOT = "marketing.referrers"


def test_a_tool_that_declares_the_root_is_given_it():
    out = with_default_data_root({"date": "1405/06/02"}, NEEDS_ROOT)
    assert out["data_root"]


def test_a_tool_that_does_not_declare_the_root_is_not_given_it():
    out = with_default_data_root({"dateFrom": "1405/06/01"}, DOES_NOT)
    assert out == {"dateFrom": "1405/06/01"}


def test_every_registered_tool_survives_the_injection_it_will_receive():
    """The whole point: whatever the adapter adds must validate everywhere.

    Iterating the registry rather than naming two tools, because the failure was
    a WHOLE CLASS of tool and picking examples is how a class-wide defect gets a
    test that passes."""
    registry = default_registry()
    for name, definition in registry.tools.items():
        schema = definition.input_schema or {}
        if not schema.get("properties"):
            continue
        arguments = with_default_data_root({}, name)
        unknown = set(arguments) - set(schema["properties"])
        assert not unknown, f"{name} would be sent {sorted(unknown)}, which it does not declare"


def test_an_explicit_root_is_never_overwritten():
    out = with_default_data_root({"data_root": "/given"}, NEEDS_ROOT)
    assert out["data_root"] == "/given"


def test_an_unknown_tool_is_left_to_fail_with_its_own_message():
    """Guessing here would replace 'Unknown tool: x' with something less
    useful, and the dispatcher already says it well."""
    out = with_default_data_root({"a": 1}, "no.such.tool")
    assert out == {"a": 1}


def test_the_local_tools_validate_with_what_the_adapter_sends():
    registry = default_registry()
    for name in ("marketing.referrers", "staff.activity", "audit.name-changes",
                 "appointments.day", "appointments.availability",
                 "appointments.vs-receptions"):
        definition = registry.get(name)
        schema = dict(definition.input_schema or {})
        arguments = with_default_data_root({"date": "1405/06/02",
                                            "dateFrom": "1405/06/01",
                                            "dateTo": "1405/06/03"}, name)
        arguments = {k: v for k, v in arguments.items()
                     if k in (schema.get("properties") or {})}
        validate_input(schema, arguments)
