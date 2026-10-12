"""Shared session source actions; no arbitrary path or session selector."""
from pydantic import BaseModel, ConfigDict, Field


class SessionFileList(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class SessionFileInspect(SessionFileList):
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    question: str = Field(default='Summarize this reference and its limitations.', min_length=1, max_length=2000)


class SessionFileStatus(SessionFileList):
    operation_id: str = Field(pattern=r'^[a-f0-9]{32}$')


SESSION_FILE_MODELS = {'list_session_files':SessionFileList,
                       'inspect_session_file':SessionFileInspect,
                       'session_file_status':SessionFileStatus}
