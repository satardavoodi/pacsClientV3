"""Headless, shared contracts for bounded workstation settings controls."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class SettingsSnapshot(StrictSettings):
    section: Literal['server', 'modality_grid', 'tools', 'image_filter']


class VerifyServer(StrictSettings):
    server_name: str = Field(min_length=1, max_length=80)
    ports: list[int] = Field(min_length=1, max_length=4)

    @model_validator(mode='after')
    def check_ports(self):
        if any(type(p) is not int or not 1 <= p <= 65535 for p in self.ports):
            raise ValueError('Invalid DICOM port')
        if len(set(self.ports)) != len(self.ports):
            raise ValueError('Duplicate ports')
        return self


class CloneServer(StrictSettings):
    source_name: str = Field(min_length=1, max_length=80)
    new_name: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9][A-Za-z0-9 _-]*$')


class RemoveModalities(StrictSettings):
    modalities: list[str] = Field(min_length=1, max_length=16)

    @model_validator(mode='after')
    def check_names(self):
        if any(not m.isascii() or not m.isalnum() or not 1 <= len(m) <= 8 or m != m.upper() or m == 'DEFAULT' for m in self.modalities):
            raise ValueError('Invalid modality name')
        return self


class ToolStyle(StrictSettings):
    tool: Literal['reference_line', 'ruler', 'arrow', 'angle', 'polygon', 'rectangle']
    color: str | None = Field(default=None, pattern=r'^#[0-9A-Fa-f]{6}$')
    line_width: float | None = Field(default=None, ge=.5, le=20)

    @model_validator(mode='after')
    def check_change(self):
        if self.color is None and self.line_width is None:
            raise ValueError('Specify color or line width')
        return self


class FilterParameter(StrictSettings):
    modality: Literal['CT', 'MR']
    parameter: str = Field(min_length=1, max_length=80)
    value: bool | int | float

    @model_validator(mode='after')
    def check_parameter(self):
        groups = {'noise_reduction', 'gaussian_smoothing', 'multiscale_sharpening',
                  'laplacian_sharpening', 'adaptive_sharpening', 'gaussian_high_pass',
                  'gaussian_low_pass', 'gaussian_band_pass'}
        parts = self.parameter.split('.')
        leaf = parts[-1]
        if self.parameter == 'min_slices':
            valid = type(self.value) is int and 1 <= self.value <= 200
        elif self.parameter == 'enabled' or (len(parts) == 2 and parts[0] in groups and leaf == 'enabled'):
            valid = type(self.value) is bool
        elif len(parts) == 2 and parts[0] in groups:
            ranges = {'noise_reduction':(.05,3), 'gaussian_smoothing':(.1,5),
                      'laplacian_sharpening':(0,1), 'adaptive_sharpening':(0,2),
                      'gaussian_high_pass':(.1,5), 'gaussian_low_pass':(.1,5), 'gaussian_band_pass':(.1,5)}
            allowed = {'sigma','mild_sigma','alpha','mild_alpha','base_amount','mild_base_amount',
                       'edge_boost','mild_edge_boost','low_sigma','high_sigma','mild_low_sigma','mild_high_sigma'}
            bounds = ranges.get(parts[0])
            valid = bounds is not None and leaf in allowed and type(self.value) in (int,float) and bounds[0] <= self.value <= bounds[1]
        else:
            valid = False
        if not valid:
            raise ValueError('Unsupported filter parameter or value')
        return self


class VoicePreferences(StrictSettings):
    provider: Literal['auto','v2t','aipacs_1','aipacs_2','aipacs_3','openai','custom'] | None = None
    timeout_seconds: int | None = Field(default=None,ge=5,le=600)

    @model_validator(mode='after')
    def check_change(self):
        if self.provider is None and self.timeout_seconds is None:
            raise ValueError('Specify a voice provider or timeout')
        return self


class ProxyPreferences(StrictSettings):
    connection_type: Literal['direct','socks5']
    proxy_port: Literal[2080,2081,2082]


class PersonalPreferences(StrictSettings):
    text_model: str | None = Field(default=None,min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._:/-]+$')
    report_model: str | None = Field(default=None,min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._:/-]+$')
    vision_model: str | None = Field(default=None,min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._:/-]+$')
    secretary_model: str | None = Field(default=None,min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._:/-]+$')
    eagle_eye_model: str | None = Field(default=None,min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._:/-]+$')
    eagle_eye_screening_model: str | None = Field(default=None,min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._:/-]+$')
    transcription_model: str | None = Field(default=None,min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._:/-]+$')
    reasoning_effort: Literal['','none','minimal','low','medium','high','xhigh','max','ultra'] | None = None
    temperature: float | None = Field(default=None,ge=0,le=2)
    max_output_tokens: int | None = Field(default=None,ge=1,le=100000)
    timeout_seconds: int | None = Field(default=None,ge=5,le=600)

    @model_validator(mode='after')
    def check_change(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError('Specify a personal AI preference')
        return self


class EagleConnection(StrictSettings):
    url: str = Field(min_length=1,max_length=512)

    @model_validator(mode='after')
    def check_url(self):
        from urllib.parse import urlsplit
        parsed = urlsplit(self.url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use an authenticated HTTPS Eagle Eye address without credentials')
        parsed.port
        return self


SETTINGS_CONTROL_MODELS = {
    'get_settings_snapshot': SettingsSnapshot,
    'verify_settings_server': VerifyServer,
    'clone_settings_server': CloneServer,
    'remove_settings_modalities': RemoveModalities,
    'set_settings_tool_style': ToolStyle,
    'set_settings_filter_parameter': FilterParameter,
    'get_ai_settings': StrictSettings,
    'set_voice_to_text_preferences': VoicePreferences,
    'set_ai_proxy_preferences': ProxyPreferences,
    'set_personal_ai_preferences': PersonalPreferences,
    'verify_eagle_eye_connection': StrictSettings,
    'set_eagle_eye_connection': EagleConnection,
}
SETTINGS_CONTROL_WRITES = frozenset(SETTINGS_CONTROL_MODELS) - {'get_settings_snapshot', 'verify_settings_server', 'get_ai_settings', 'verify_eagle_eye_connection'}
