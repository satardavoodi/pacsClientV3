from __future__ import annotations

from dataclasses import dataclass, field

from .errors import ToolNotFoundError
from .types import ToolDefinition

#: What `list()` and `list_for()` hand back.
#:
#: Named at module level because the class below defines a method called
#: `list`, which shadows the builtin inside the class body — so
#: `-> list[dict[str, object]]` there resolves to the METHOD, not to the type.
#: mypy said so plainly ("Function ... is not valid as a type"), and it is right
#: that the annotation was nonsense; a reader would have taken longer to notice.
ToolDescriptions = list[dict[str, object]]


@dataclass
class ToolRegistry:
    tools: dict[str, ToolDefinition] = field(default_factory=dict)

    def register(self, definition: ToolDefinition) -> None:
        """Add a tool. A NAME MAY ONLY BE CLAIMED ONCE.

        ⚠️ This used to be a plain dict assignment, and a second registration
        replaced the first in silence. It happened: a new appointment-diary tool
        was registered as `appointments.list` and took the name of the existing
        waiting-queue tool. Nothing failed, no test noticed, and the only visible
        symptom would have been the queue tool answering a different question
        from the one its description promised — which is indistinguishable from
        a model choosing badly, and would have been diagnosed as that.

        The registry is the one place that knows every tool's name. It is the
        only place that CAN catch this, so it does.
        """
        existing = self.tools.get(definition.name)
        if existing is not None and existing is not definition:
            raise ValueError(
                f"tool name already registered: {definition.name!r}. Two tools "
                "cannot share a name — the second would silently replace the "
                "first and answer questions the first one's description promised."
            )
        self.tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self.tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Unknown tool: {name}") from exc

    def list(self) -> ToolDescriptions:
        return [self.describe(tool) for tool in self.tools.values()]

    def list_for(self, principal) -> ToolDescriptions:
        """Only the tools this principal may actually use.

        The cheapest way to prevent a call is to not advertise it: an agent
        running as ``agent_readonly`` should never even see a clinical write
        tool in its schema list. This is a *visibility* filter — the permission
        check in ``core.guards`` still runs on every dispatch.
        """
        from ..permissions import load_permissions

        try:
            policy = load_permissions()
        except FileNotFoundError:
            return self.list()

        user = getattr(principal, "user", None)
        center = getattr(principal, "center", None)
        allowed = []
        for tool in self.tools.values():
            decision = policy.check(user, center, tool.name, tool.permission_action, tool.safety)
            if decision.allowed:
                allowed.append(self.describe(tool))
        return allowed

    @staticmethod
    def describe(tool: ToolDefinition) -> dict[str, object]:
        schema = dict(tool.input_schema or {})
        # `data_root` is injected server-side; never advertise it to a client or
        # to the model (llm/interpreter.FORBIDDEN_ARGUMENT_KEYS rejects it too).
        properties = {k: v for k, v in (schema.get("properties") or {}).items() if k != "data_root"}
        required = [k for k in (schema.get("required") or []) if k != "data_root"]
        if schema:
            schema = {**schema, "properties": properties, "required": required}
        return {
            "name": tool.name,
            "kind": tool.kind,
            "description": tool.description,
            "safety": tool.safety,
            "permission_action": tool.permission_action,
            "requires_confirmation": tool.requires_confirmation or requires_human_approval(tool),
            "input_schema": schema,
        }


def requires_human_approval(tool: ToolDefinition) -> bool:
    """True when a tool changes CRM state and therefore needs a human tap.

    Dry-run planners (``permission_action == "plan"``) are read-safe even though
    their *safety* label is a write level — they never call the CRM.
    """
    if tool.requires_confirmation:
        return True
    return tool.safety != "read" and tool.permission_action == "execute"


def default_registry() -> ToolRegistry:
    """The one registry. A tool that is not here does not exist."""
    from .tools.conversations import register_conversation_tools
    from .tools.finance import register_finance_tools
    from .tools.integrity_local import register_integrity_tools
    from .tools.patients import register_patient_tools
    from .tools.people_local import register_people_tools
    from .tools.reports import register_report_tools
    from .tools.receptions import register_reception_tools
    from .tools.reports_local import register_local_report_tools
    from .tools.writes import register_write_tools

    registry = ToolRegistry()
    register_report_tools(registry)
    register_patient_tools(registry)
    # Reads the reception database directly. Registered unconditionally: the
    # tools themselves report "not available here" when that database is not
    # reachable, which is a better answer than a tool that silently vanishes
    # depending on where the agent happens to be installed.
    register_local_report_tools(registry)
    register_reception_tools(registry)
    register_integrity_tools(registry)
    # Referrers, staff activity windows, the name-change trail and the whole
    # appointment diary. Twenty-one of the seventy v3 benchmark questions could
    # not be answered without these, and in every case the data was already in
    # the database the agent was reading — the gap was the tool, not the record.
    register_people_tools(registry)
    # The patient chat, on the CENTRAL server. Registered unconditionally for the
    # same reason as the local tools above, and for a sharper one: when this was
    # absent the model did not say "I cannot see the conversation system" — it
    # answered the question with reception data instead.
    register_conversation_tools(registry)
    # Money BY MEANING rather than by field. Registered after the report tools it
    # delegates to, and deliberately routed through the same dispatcher, so a
    # metric can never be served from a private path that drifts from the tool
    # everything else reads.
    register_finance_tools(registry)
    register_write_tools(registry)
    return registry
