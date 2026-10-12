"""Shared, headless schemas for local Education authoring commands."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


Label = Annotated[str, Field(max_length=100)]


class CourseFields(StrictModel):
    course_name: str = Field(default='', max_length=250)
    author_name: str = Field(default='', max_length=200)
    course_description: str = Field(default='', max_length=10000)
    modality: str = Field(default='MRI', max_length=40)
    level: Literal['Basic', 'Intermediate', 'Advanced', 'Expert'] = 'Intermediate'
    body_regions: list[Label] = Field(default_factory=list, max_length=20)
    tags: list[Label] = Field(default_factory=list, max_length=30)
    visibility: Literal['Private', 'Public'] = 'Private'


class CourseSlide(StrictModel):
    slide_title: str = Field(default='', max_length=250)
    slide_notes: str = Field(default='', max_length=10000)
    text: str = Field(default='', max_length=20000)
    duration_seconds: int = Field(default=0, ge=0, le=7200)


class PrepareCourse(CourseFields):
    slides: list[CourseSlide] = Field(default_factory=list, max_length=60)


class CourseHandle(StrictModel):
    draft_id: str = Field(min_length=1, max_length=64)


class SaveCourse(CourseHandle):
    expected_revision: int = Field(ge=1)


class CourseSlidePatch(StrictModel):
    slide_order: int = Field(ge=1, le=60)
    slide_title: str | None = Field(default=None, max_length=250)
    slide_notes: str | None = Field(default=None, max_length=10000)
    text: str | None = Field(default=None, max_length=20000)
    duration_seconds: int | None = Field(default=None, ge=0, le=7200)


class UpdateCourse(SaveCourse):
    fields: CourseFields = Field(default_factory=CourseFields)
    slides: list[CourseSlidePatch] = Field(default_factory=list, max_length=60)


class LoadCourse(StrictModel):
    course_pk: int = Field(ge=1)


class CourseOperation(StrictModel):
    operation_id: str = Field(min_length=1, max_length=64)


COURSE_AUTHORING_MODELS = {
    'prepare_course_draft': PrepareCourse,
    'update_course_draft': UpdateCourse,
    'get_course_draft': CourseHandle,
    'load_course_draft': LoadCourse,
    'save_course_draft': SaveCourse,
    'course_authoring_status': CourseOperation,
    'open_course_editor': CourseHandle,
    'preview_course': CourseHandle,
}
