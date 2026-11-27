
from pydantic import BaseModel, ConfigDict, Field


class SubjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=30)
    description: str | None = Field(default=None, max_length=500)


class SubjectUpdate(SubjectCreate):
    pass


class SubjectResponse(SubjectCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)
