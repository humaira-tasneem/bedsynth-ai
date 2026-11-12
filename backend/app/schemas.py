"""Validated API request and response schemas for Hospital Studio."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_code(value: str) -> str:
    cleaned = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,39}", cleaned):
        raise ValueError("Use 1–40 letters, numbers, hyphens, or underscores; start with a letter or number.")
    return cleaned


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Workspace name cannot be blank.")
        return value


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class NetworkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Network name cannot be blank.")
        return value


class NetworkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    name: str
    is_archived: bool


class BedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    hospital_id: int
    department_id: int
    code: str
    category: str
    status: str


class DepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    hospital_id: int
    code: str
    name: str
    bed_capacity: int | None
    is_archived: bool
    beds: list[BedRead] = Field(default_factory=list)


class HospitalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    network_id: int | None
    name: str
    code: str
    is_archived: bool
    departments: list[DepartmentRead] = Field(default_factory=list)


class HospitalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str
    network_id: int | None = None

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Hospital name cannot be blank.")
        return value

    @field_validator("code")
    @classmethod
    def clean_code(cls, value: str) -> str:
        return normalize_code(value)


class HospitalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    code: str | None = None
    network_id: int | None = None
    is_archived: bool | None = None

    @field_validator("name")
    @classmethod
    def trim_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Hospital name cannot be blank.")
        return value

    @field_validator("code")
    @classmethod
    def clean_optional_code(cls, value: str | None) -> str | None:
        return normalize_code(value) if value is not None else None


class DepartmentCreate(BaseModel):
    code: str
    name: str = Field(min_length=1, max_length=120)
    bed_capacity: int = Field(gt=0, le=10000)

    @field_validator("code")
    @classmethod
    def clean_code(cls, value: str) -> str:
        return normalize_code(value)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Department name cannot be blank.")
        return value


class DepartmentUpdate(BaseModel):
    code: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    bed_capacity: int | None = Field(default=None, gt=0, le=10000)
    is_archived: bool | None = None

    @field_validator("code")
    @classmethod
    def clean_optional_code(cls, value: str | None) -> str | None:
        return normalize_code(value) if value is not None else None

    @field_validator("name")
    @classmethod
    def trim_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Department name cannot be blank.")
        return value


BedStatus = Literal["planned", "operational", "out_of_service", "retired"]


class BedCreate(BaseModel):
    code: str
    category: str = Field(default="general", min_length=1, max_length=60)
    status: Literal["planned", "operational", "out_of_service"] = "operational"

    @field_validator("code")
    @classmethod
    def clean_code(cls, value: str) -> str:
        return normalize_code(value)

    @field_validator("category")
    @classmethod
    def trim_category(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Bed category cannot be blank.")
        return value


class BedUpdate(BaseModel):
    code: str | None = None
    category: str | None = Field(default=None, min_length=1, max_length=60)
    status: BedStatus | None = None
    department_id: int | None = Field(default=None, gt=0)

    @field_validator("code")
    @classmethod
    def clean_optional_code(cls, value: str | None) -> str | None:
        return normalize_code(value) if value is not None else None

    @field_validator("category")
    @classmethod
    def trim_optional_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Bed category cannot be blank.")
        return value


class BedGenerationPreviewRequest(BaseModel):
    department_ids: list[int] | None = Field(default=None, min_length=1)


class BedGenerationPreviewDepartment(BaseModel):
    department_id: int
    department_name: str
    department_code: str
    capacity: int | None
    existing_beds: int
    beds_to_create: int
    first_bed_code: str | None = None
    last_bed_code: str | None = None
    note: str | None = None


class BedGenerationPreviewRead(BaseModel):
    hospital_id: int
    departments: list[BedGenerationPreviewDepartment]
    total_to_create: int
    preview_token: str


class BedGenerationRequest(BedGenerationPreviewRequest):
    preview_token: str = Field(min_length=64, max_length=64)
    confirmed: bool


class BedGenerationDepartmentResult(BaseModel):
    department_id: int
    department_name: str
    beds_created: int


class BedGenerationRead(BaseModel):
    hospital_id: int
    beds_created: int
    departments: list[BedGenerationDepartmentResult]
