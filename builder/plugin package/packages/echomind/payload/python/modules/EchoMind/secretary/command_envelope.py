"""Typed command envelopes for the unified Command Layer."""
from __future__ import annotations
from typing import Any, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, AliasChoices, model_validator
from modules.ai_imaging.eagle_eye_remote.secretary.validation.ui_controls import UI_CONTROL_MODELS

SourceScope = Literal["active_tab", "local", "server"]
SttRoute = Literal["native", "v2t"]


class HomeSearchEntities(BaseModel):
    """Shared bus/MCP schema. Extensions remain available for legacy adapters."""
    model_config = ConfigDict(extra="allow", strict=True)
    source: Literal["active_tab", "local", "server"] = "active_tab"
    patient_id: str = ""
    patient_ids: list[str] = Field(default_factory=list, max_length=100)
    patient_name: str = ""
    modality: str = ""
    body_part: str = Field(default="", max_length=100)
    age_min: int | None = Field(default=None, ge=0, le=150)
    age_max: int | None = Field(default=None, ge=0, le=150)
    date_from: str = ""
    date_to: str = ""
    limit: int = Field(default=25, ge=1, le=200)


class AdvancedHomeSearchEntities(HomeSearchEntities):
    model_config = ConfigDict(extra='forbid', strict=True)

    @model_validator(mode='after')
    def validate_filters(self):
        from datetime import datetime
        for value in (self.date_from,self.date_to):
            if value:
                if len(value)!=8 or not value.isdigit():
                    raise ValueError('Use YYYYMMDD dates')
                datetime.strptime(value,'%Y%m%d')
        if self.date_from and self.date_to and self.date_from>self.date_to:
            raise ValueError('Invalid date interval')
        if self.age_min is not None and self.age_max is not None and self.age_min>self.age_max:
            raise ValueError('Invalid age interval')
        return self


class HomeSortEntities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    column: Literal['date', 'images_count', 'patient_id', 'patient_name', 'modality'] = 'date'
    order: Literal['asc', 'desc'] = 'desc'


class HomeSelectionEntities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    list_id: str | None = Field(default=None, min_length=1, max_length=64)
    row_indices: list[Annotated[int, Field(strict=True, ge=1, le=10000)]] = Field(default_factory=list, max_length=100)
    study_uids: list[str] = Field(default_factory=list, max_length=100)
    patient_ids: list[str] = Field(default_factory=list, max_length=100)


class HomeSelectionHandle(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    selection_id: str = Field(min_length=1, max_length=64)


class MediaWriteEntities(HomeSelectionHandle):
    mode: Literal['burn','folder']
    drive_id: str | None = Field(default=None, max_length=256)
    output_folder: str | None = Field(default=None, max_length=1000)
    disc_label: str = Field(default='DICOM_IMAGES', min_length=1, max_length=32)
    anonymize: bool = False
    include_report: bool = False
    include_viewer: bool = True
    include_images: bool = False
    include_attachments: bool = False
    dicom_format: Literal['original','uncompressed','lossless','jpeg2000'] = 'original'
    write_speed_sectors: int | None = Field(default=None, ge=1, le=100000)
    finalize_disc: bool = True
    verify_after_burn: bool = True

    @model_validator(mode='after')
    def check_target(self):
        if self.mode=='folder' and not self.output_folder:
            raise ValueError('Folder output requires a target')
        if self.mode=='burn' and (not self.drive_id or self.output_folder):
            raise ValueError('Burn requires an explicit drive and no folder')
        return self


class HomeOpenEntities(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    patient_id: str = Field(default="", validation_alias=AliasChoices("patient_id", "id"))
    row_index: int | None = Field(default=None, ge=1, le=10000)
    list_id: str = Field(default="", max_length=128)
    required_voice_presence: Literal['present', 'absent'] | None = None

    @model_validator(mode='after')
    def check_selector(self):
        if self.row_index is not None:
            if self.patient_id or self.study_uid or not self.list_id:
                raise ValueError('Ordinal opening requires list_id and no patient identity selector')
        elif not self.patient_id or self.list_id:
            raise ValueError('Opening requires patient_id or row_index with list_id')
        if self.required_voice_presence is not None and self.row_index is None:
            raise ValueError('Voice-conditioned opening requires a bound row')
        return self
    patient_name: str = ""
    study_uid: str = ""
    report_status: str = "pending"


ACTION_ENTITY_MODELS = {
    "select_patients": HomeSelectionEntities,
    "selection_status": HomeSelectionHandle,
    "download_selection": HomeSelectionHandle,
    "download_selection_status": HomeSelectionHandle,
    "film_selection": HomeSelectionHandle,
    "sort_patients": HomeSortEntities,
    "list_patients": HomeSearchEntities,
    "search_patients": HomeSearchEntities,
    "advanced_search_patients": AdvancedHomeSearchEntities,
    "read_patients": HomeSearchEntities,
    "open_patient": HomeOpenEntities,
}


class SettingsEmptyEntities(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


from modules.ai_imaging.eagle_eye_remote.secretary.validation.settings_controls import SETTINGS_CONTROL_MODELS
ACTION_ENTITY_MODELS.update(SETTINGS_CONTROL_MODELS)


class SettingsOpenEntities(SettingsEmptyEntities):
    section: Literal['server', 'viewer', 'tools', 'image_filter', 'storage',
                     'echomind', 'eagle_eye', 'agent', 'installation', 'education'] = 'viewer'


class SettingsThemeEntities(SettingsEmptyEntities):
    theme: str = Field(min_length=1, max_length=40)


class SettingsStatusEntities(SettingsEmptyEntities):
    operation_id: str = Field(min_length=1, max_length=128)


class SettingsCleanupEntities(SettingsEmptyEntities):
    category: Literal['cache', 'printing', 'patients'] = 'cache'
    strategy: Literal['all', 'delete_oldest_count', 'older_than_days'] | None = None
    value: int | None = Field(default=None, ge=1, le=100000)

    @model_validator(mode='after')
    def check_scope(self):
        if self.category == 'patients':
            if self.strategy is None or (self.strategy != 'all' and self.value is None):
                raise ValueError('Patient cleanup requires an explicit strategy and bounded value')
            if self.strategy == 'all' and self.value is not None:
                raise ValueError('All-patient cleanup does not accept a count')
        elif self.strategy is not None or self.value is not None:
            raise ValueError('Retention rules apply only to patient cleanup')
        return self


class SettingsQualityEntities(SettingsEmptyEntities):
    section: Literal['viewer', 'tools', 'image_filter'] = 'image_filter'


ACTION_ENTITY_MODELS.update({
    'open_settings': SettingsOpenEntities,
    'get_settings_capabilities': SettingsEmptyEntities,
    'get_theme': SettingsEmptyEntities,
    'set_theme': SettingsThemeEntities,
    'diagnose_resources': SettingsEmptyEntities,
    'settings_operation_status': SettingsStatusEntities,
    'request_storage_cleanup': SettingsCleanupEntities,
    'get_storage_cleanup_status': SettingsEmptyEntities,
    'configure_personal_ai': SettingsEmptyEntities,
    'configure_image_quality': SettingsQualityEntities,
})


class SupportCollectEntities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    include_windows_events: bool = False


class PatientCommentEntities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    study_uid: str = Field(min_length=1, max_length=128)
    comment: str = Field(min_length=1, max_length=4000)


class TutorialEntities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    tutorial_id: Literal['open_patient', 'search_patients', 'report_issue']


class SupportIssueOpenEntities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    description: str = Field(default='', max_length=4000)


class PatientCommentDraftEntities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    draft_id: str = Field(min_length=1, max_length=64)


class PatientVoicePrepareEntities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    study_uid: str = Field(min_length=1, max_length=128)


class PatientVoiceHandleEntities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    recording_id: str = Field(min_length=1, max_length=64)


ACTION_ENTITY_MODELS.update({
    'write_selection_media': MediaWriteEntities,
    'prepare_selection_media': HomeSelectionHandle,
    'media_drives': SettingsEmptyEntities,
    'media_status': SettingsStatusEntities,
    'cancel_media': SettingsStatusEntities,
    'collect_support_diagnostics': SupportCollectEntities,
    'open_support_issue': SupportIssueOpenEntities,
    'support_issue_status': SettingsEmptyEntities,
    'prepare_help_ticket': SupportIssueOpenEntities,
    'submit_help_ticket': SettingsEmptyEntities,
    'help_ticket_status': SettingsEmptyEntities,
    'get_loaded_study_summary': SettingsEmptyEntities,
    'get_tutorial_catalog': SettingsEmptyEntities,
    'show_tutorial': TutorialEntities,
    'support_operation_status': SettingsStatusEntities,
    'get_visible_app_errors': SettingsEmptyEntities,
    'get_recent_function_results': SettingsEmptyEntities,
    'get_control_capabilities': SettingsEmptyEntities,
    'prepare_patient_comment': PatientCommentEntities,
    'sync_patient_comment': PatientCommentDraftEntities,
    'patient_comment_status': SettingsStatusEntities,
    'prepare_patient_voice': PatientVoicePrepareEntities,
    **{name:PatientVoiceHandleEntities for name in (
        'start_patient_voice', 'pause_patient_voice', 'resume_patient_voice',
        'stop_patient_voice', 'patient_voice_status', 'send_patient_voice')},
})


def action_entity_schema(action: str) -> dict:
    model = ACTION_ENTITY_MODELS.get(action)
    return model.model_json_schema() if model else {"type": "object"}


def validate_action_entities(action: str, entities: dict) -> dict:
    model = ACTION_ENTITY_MODELS.get(action)
    if model:
        return model.model_validate(entities).model_dump(exclude_unset=True)
    return entities


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    text: str = ""
    language: str = "auto"
    session_id: str | None = None
    source_scope: SourceScope = "active_tab"
    stt_route: SttRoute = "native"
    stt_fallback: bool = True
    context: dict[str, Any] = Field(default_factory=dict)
    extras: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_typeddict(cls, td: dict | None) -> "CommandRequest | None":
        if td is None:
            return None
        return cls.model_validate(td)

    def to_typeddict(self) -> dict:
        return self.model_dump(exclude_unset=False)


class CommandPlan(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str
    entities: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    needs_confirmation: bool = False
    reason: str = ""
    notes: str = ""
    canonical_text: str = ""

    @classmethod
    def from_typeddict(cls, td: dict | None) -> "CommandPlan | None":
        if td is None:
            return None
        return cls.model_validate(td)

    def to_typeddict(self) -> dict:
        return self.model_dump(exclude_unset=False)


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    ok: bool
    action: str
    message: str = ""
    # Accepts dict / list / scalar payloads (see test_dispatch_raw_payload_wrapped_as_data).
    data: Any = None
    error_code: str | None = None
    elapsed_ms: float | None = None

    @classmethod
    def from_typeddict(cls, td: dict | None) -> "CommandResult | None":
        if td is None:
            return None
        return cls.model_validate(td)

    def to_typeddict(self) -> dict:
        return self.model_dump(exclude_unset=False)


__all__ = ["CommandRequest", "CommandPlan", "CommandResult", "SourceScope", "SttRoute"]


class ViewerPreferenceEntities(SettingsEmptyEntities):
    backend: Literal['pydicom_2d', 'pydicom_qt', 'vtk_simpleitk'] | None = None
    gpu_boost: bool | None = None

    @model_validator(mode='after')
    def check_changes(self):
        if self.backend is None and self.gpu_boost is None:
            raise ValueError('Specify a viewer preference')
        return self


ACTION_ENTITY_MODELS.update({
    'release_memory': SettingsEmptyEntities,
    'get_viewer_preferences': SettingsEmptyEntities,
    'set_viewer_preferences': ViewerPreferenceEntities,
})

ACTION_ENTITY_MODELS.update(UI_CONTROL_MODELS)
