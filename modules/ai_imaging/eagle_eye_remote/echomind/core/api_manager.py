"""Headless, request-scoped replacement for the Qt credential singleton."""
from types import SimpleNamespace
from modules.ai_imaging.eagle_eye_remote.echomind.runtime import company_identity, current_settings


class Manage:
    @classmethod
    def instance(cls):
        return cls()

    def get_center_and_gapgpt_key(self):
        return company_identity()

    def is_validated(self):
        try:
            company_identity()
            return True
        except (ValueError, OSError):
            return False

    def ensure_detected(self):
        center, key = company_identity()
        return SimpleNamespace(center_display=center, gapgpt_key=key)

    def detect_center(self, key=None):
        return self.ensure_detected()

    def get_detected_center_display(self):
        return company_identity()[0]

    def update_usage(self, *args, **kwargs):
        pass  # Usage is returned to the authenticated caller; no desktop log/database.

    update_usage_total = update_usage


class APIKeyManager(Manage):
    def validate_key(self, key):
        if key != current_settings().get("api_key"):
            return False, None, "Invalid EchoMind access code"
        try:
            return True, company_identity()[0], None
        except (ValueError, OSError):
            return False, None, "Invalid EchoMind access code"
