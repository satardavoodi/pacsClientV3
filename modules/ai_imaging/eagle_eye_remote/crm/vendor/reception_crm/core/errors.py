from __future__ import annotations


class ReceptionCoreError(RuntimeError):
    code = "CORE_ERROR"


class ToolNotFoundError(ReceptionCoreError):
    code = "TOOL_NOT_FOUND"


class ToolValidationError(ReceptionCoreError):
    code = "VALIDATION"


class ToolPermissionError(ReceptionCoreError):
    code = "PERMISSION_DENIED"


class ToolConfirmationError(ReceptionCoreError):
    code = "CONFIRMATION_REQUIRED"
