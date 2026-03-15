from importlib import import_module

__all__ = [
    "EchoMindSettingsWidget",
    "InstallationModuleSettingsWidget",
    "SettingsTabWidget",
    "StorageCleanupPanelWidget",
]

_EXPORTS = {
    "EchoMindSettingsWidget": (".echomind_settings", "EchoMindSettingsWidget"),
    "InstallationModuleSettingsWidget": (".installation_module_settings", "InstallationModuleSettingsWidget"),
    "SettingsTabWidget": (".settings_ui", "SettingsTabWidget"),
    "StorageCleanupPanelWidget": (".storage_cleanup_panel", "StorageCleanupPanelWidget"),
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name, package=__name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals().keys()) | set(__all__))
