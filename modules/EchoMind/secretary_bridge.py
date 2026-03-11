from __future__ import annotations


def get_runtime_home_widget():
    try:
        from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget

        return get_home_widget()
    except Exception:
        return None


def create_secretary_orchestrator(home_widget=None):
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator

    return SecretaryOrchestrator(
        home_widget=home_widget or get_runtime_home_widget(),
        use_brain=True,
    )

