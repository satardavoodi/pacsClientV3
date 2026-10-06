"""Shared typed UI observation action parameters."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field


class EmptyUi(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class UiCatalog(EmptyUi):
    area:Literal['all','home','settings','patient_viewer','advanced_viewer','advanced_analysis','eagle_eye']='all'
    offset:int=Field(default=0,ge=0,le=10000)
    limit:int=Field(default=50,ge=1,le=100)


class UiStatus(EmptyUi):
    snapshot_id:str=Field(min_length=1,max_length=36)


UI_CONTROL_MODELS={'get_ui_control_catalog':UiCatalog,'inspect_ui_controls':EmptyUi,
                   'capture_ui_context':EmptyUi,'ui_context_status':UiStatus}
