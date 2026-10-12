# Planning rejection diagnostics

Prepared offline on 2026-10-12; not activated. The observed original request failed with SERVER_PLAN_INVALID after successful request validation. Its exact provider-plan rejection branch was not retained and remains unknown.

The existing HTTP error envelope optionally carries a strictly allowlisted rejection descriptor for the three existing SERVER_PLAN_INVALID branches: completion_type_or_bounds, json_not_object, and plan_validation. A plan-validation rejection exposes only the first known validator code and top-level schema field; unknown fields/codes become unknown. No plan, entity value, reason, provider output, patient data or credential is included. HTTP status, machine error code, prompts, provider calls, validation and execution rules are unchanged.

The descriptor survives existing localization, private failed history, HTTP client, remote-planner error and native aggregate diagnostic paths. Legacy diagnostic shape remains unchanged when the descriptor is absent or invalid. This adds evidence, not an automatic repair or a function acceptance claim.
