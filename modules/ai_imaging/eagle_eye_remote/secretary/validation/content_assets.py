"""Shared end-user content commands; no caller-defined storage paths or providers."""
from typing import Literal, Annotated
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class WebRead(Strict):
    url: str = Field(min_length=8, max_length=2048)


class WebSearch(Strict):
    query: str = Field(min_length=1, max_length=2000)


class GenerateImage(Strict):
    description: str = Field(min_length=1, max_length=4000)


class AssetOperation(Strict):
    operation_id: str = Field(min_length=1, max_length=64)


class CourseSnapshot(Strict):
    course_pk: int = Field(ge=1)


class CourseAsset(CourseSnapshot):
    expected_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    slide_pk: int | None = Field(default=None, ge=1)
    content_pk: int | None = Field(default=None, ge=1)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    purpose: Literal['image', 'slide_thumbnail', 'course_cover', 'pdf']
    name: str = Field(default='', max_length=250)


class SlideEdit(Strict):
    slide_pk: int | None = Field(default=None, ge=1)
    slide_title: str = Field(min_length=1, max_length=250)
    slide_notes: str | None = Field(default=None, max_length=10000)
    text: str | None = Field(default=None, max_length=20000)
    layout: Literal['text','right','left','above','below','media'] | None = None
    rich_text: str | None = Field(default=None, max_length=30000)
    background: str | None = Field(default=None, pattern=r'^#[a-fA-F0-9]{6}$')
    foreground: str | None = Field(default=None, pattern=r'^#[a-fA-F0-9]{6}$')


class OrganizeCourse(CourseSnapshot):
    expected_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    author_name: str | None = Field(default=None,max_length=250)
    course_name: str | None = Field(default=None,min_length=1,max_length=250)
    slides: list[SlideEdit] = Field(min_length=1, max_length=60)


class FindDicom(Strict):
    patient_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(min_length=1, max_length=10)


class ImportDicom(CourseSnapshot):
    expected_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    slide_pk: int = Field(ge=1)
    selection_id: str = Field(min_length=1, max_length=64)
    study_uids: list[Annotated[str, Field(pattern=r'^[0-9]+(?:\.[0-9]+)+$')]] = Field(min_length=1, max_length=5)


WEB_MODELS = {'server_web_read': WebRead, 'server_web_search': WebSearch,
              'server_web_download': WebRead, 'server_generate_image': GenerateImage}
CONTENT_ASSET_MODELS = {**WEB_MODELS, 'content_asset_status': AssetOperation,
                        'inspect_course_content': CourseSnapshot, 'attach_course_asset': CourseAsset,
                        'organize_course_content':OrganizeCourse,
                        'find_course_dicom':FindDicom,'import_course_dicom':ImportDicom}

ASSET_RESULT_BINDINGS = {
    'server_web_download':('sha256',),'server_generate_image':('sha256',),
    'inspect_course_content':('expected_digest',),'attach_course_asset':('expected_digest',),
    'organize_course_content':('expected_digest',),'import_course_dicom':('expected_digest',),
    'find_course_dicom':('selection_id',)}


def workflow_asset_entities(action, entities, produced):
    """Typed hashes may reference only actual preceding verified content receipts."""
    if not isinstance(entities,dict):
        return entities
    values=dict(entities)
    if action in CONTENT_ASSET_MODELS:
        for field in ('sha256','expected_digest','selection_id'):
            if values.get(field)=='$'+field:
                if field not in produced:
                    raise ValueError('Content reference has no preceding producer')
                values[field]='0'*64 if field!='selection_id' else 'verified-selection'
    return values


class ServerAssetRequest(Strict):
    action: Literal['server_web_read', 'server_web_search', 'server_web_download', 'server_generate_image']
    session_id: str = Field(min_length=36,max_length=36)
    url: str | None = None
    query: str | None = None
    description: str | None = None

    @field_validator('session_id')
    @classmethod
    def canonical_uuid(cls, value):
        if str(UUID(value)) != value:
            raise ValueError('Canonical session UUID required')
        return value

    def entities(self):
        values = self.model_dump(exclude={'action', 'session_id'}, exclude_none=True)
        return WEB_MODELS[self.action].model_validate(values).model_dump()
