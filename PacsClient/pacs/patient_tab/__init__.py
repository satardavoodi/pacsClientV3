def __getattr__(name):
    """Lazy re-exports to avoid circular imports at module load time."""
    _MAP = {
        "AiMainWindow": ("modules.ai_imaging.ai_module_ui", "AiMainWindow"),
        "PatientWidget": ("PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget", "PatientWidget"),
        "CallerTypes": ("PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget", "CallerTypes"),
        "ReceptionDataTab": ("modules.ai_imaging.ai_module_ui.service_tab", "ReceptionDataTab"),
        "CurvedMPRModule": ("modules.mpr.curved_mpr.curved_mpr_module", "CurvedMPRModule"),
        "CurvedMPRView": ("modules.mpr.curved_mpr.curved_mpr_view", "CurvedMPRView"),
        "show_curved_mpr": ("modules.mpr.curved_mpr.curved_mpr_view", "show_curved_mpr"),
        "CurvedMPRPanoramicView": ("modules.mpr.curved_mpr.curved_mpr_panoramic_view", "CurvedMPRPanoramicView"),
    }
    if name in _MAP:
        import importlib
        mod_path, attr = _MAP[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")