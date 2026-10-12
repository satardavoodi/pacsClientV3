"""Bounded conversation data; never an execution or permission envelope."""
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Conversation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str
    mode: Literal['act', 'ask', 'guide', 'help_ticket']
    title: str = Field(default='New conversation', min_length=1, max_length=80)
    topic: str = Field(default='', max_length=120)
    goal: str = Field(default='', max_length=300)
    summary: str = Field(default='', max_length=1000)

    @field_validator('id')
    @classmethod
    def identity(cls, value):
        if str(UUID(value)) != value:
            raise ValueError('Canonical conversation UUID required')
        return value

    @field_validator('title', 'topic', 'goal', 'summary')
    @classmethod
    def safe_text(cls, value):
        from .validation.credential_guard import contains_api_credential
        if contains_api_credential(value) or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid conversation metadata')
        return value
