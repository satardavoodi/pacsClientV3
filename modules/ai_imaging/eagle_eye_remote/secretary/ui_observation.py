"""Strict, correlated, rendered UI images. No URLs, filesystem paths or DICOM."""
import base64
import hashlib
import io
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field,model_validator
from typing import Literal


class UiImage(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    version:Literal[1]
    snapshot_id:str
    context_digest:str=Field(pattern=r'^[0-9a-f]{64}$')
    sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    width:int=Field(ge=1,le=1024)
    height:int=Field(ge=1,le=768)
    scope:Literal['redacted_controls_only_no_clinical_images']
    image:str=Field(min_length=1,max_length=131072)

    @model_validator(mode='after')
    def pixels(self):
        if str(UUID(self.snapshot_id))!=self.snapshot_id:raise ValueError('Invalid UI snapshot identity')
        raw=base64.b64decode(self.image,validate=True)
        if len(raw)>98304 or hashlib.sha256(raw).hexdigest()!=self.sha256:
            raise ValueError('Invalid UI image integrity or size')
        from PIL import Image
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format!='PNG' or image.size!=(self.width,self.height):raise ValueError('Invalid UI image dimensions')
                image.verify()
        except (OSError,SyntaxError) as exc:raise ValueError('Invalid UI pixels') from exc
        return self


def receipt(image):
    return {key:getattr(image,key) for key in ('snapshot_id','context_digest','sha256','scope','width','height')}
