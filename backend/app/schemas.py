"""Validated API request and response schemas for Hospital Studio."""

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class GenerationConfig(BaseModel):
    start_date: date
    end_date: date
    target_admissions: int = Field(ge=0, le=5000)
    target_occupancy_pct: int = Field(ge=0, le=100)
    seed: int = Field(ge=0, le=2_147_483_647)
    department_ids: list[int] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_generation_window(self) -> "GenerationConfig":
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date.")
        if (self.end_date - self.start_date).days >= 366:
            raise ValueError("The generation date range cannot exceed 366 calendar days.")
        if self.target_admissions == 0 and self.target_occupancy_pct != 0:
            raise ValueError("Set target occupancy to 0 when generating 0 admissions.")
        if self.target_admissions > 0 and self.target_occupancy_pct == 0:
            raise ValueError("Target occupancy must be above 0 when generating admissions.")
        if self.department_ids is not None and len(set(self.department_ids)) != len(self.department_ids):
            raise ValueError("Department selections must not contain duplicates.")
        return self


class GenerationPreviewDepartment(BaseModel):
    department_id: int
    department_name: str
    operational_beds: int


class GenerationPreviewRead(BaseModel):
    hospital_id: int
    hospital_name: str
    workspace_id: int
    start_date: date
    end_date: date
    target_admissions: int
    target_occupancy_pct: int
    seed: int
    departments: list[GenerationPreviewDepartment]
    total_operational_beds: int
    planned_peak_occupied_beds: int
    occupancy_snapshots_planned: int
    preview_token: str


class GenerationCreate(GenerationConfig):
    idempotency_key: UUID
    preview_token: str = Field(min_length=64, max_length=64)


class GenerationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    run_id: UUID
    workspace_id: int
    hospital_id: int
    idempotency_key: UUID
    config: dict
    seed: int
    status: Literal["generating", "completed", "failed"]
    started_at: datetime
    completed_at: datetime | None
    patients_count: int
    admissions_count: int
    discharges_count: int
    transfers_count: int
    snapshots_count: int
    error_message: str | None


ValidationCategory = Literal[
    "completeness", "uniqueness", "referential_integrity", "temporal_validity",
    "bed_assignment_consistency", "capacity_consistency", "occupancy_accuracy",
]
ValidationSeverity = Literal["critical", "high", "medium", "low"]


class ValidationIssueRead(BaseModel):
    category: ValidationCategory
    severity: ValidationSeverity
    code: str
    message: str
    entity_type: str | None = None
    entity_id: str | int | None = None


class ValidationCategoryRead(BaseModel):
    category: ValidationCategory
    weight: float
    checks_performed: int
    checks_passed: int
    checks_failed: int
    issue_count: int
    score: float


class ValidationReportRead(BaseModel):
    validation_id: UUID
    run_id: UUID
    workspace_id: int
    hospital_id: int
    validated_at: datetime
    score: float
    checks_performed: int
    checks_passed: int
    checks_failed: int
    warning_count: int
    status: Literal["passed", "passed_with_warnings", "failed"]
    categories: list[ValidationCategoryRead]
    issues: list[ValidationIssueRead]


class AnalyticsFilters(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    department_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_date_order(self) -> "AnalyticsFilters":
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Provide both start_date and end_date, or omit both to use the selected run's reporting period.")
        if self.start_date is not None and self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError("End date must be on or after start date.")
            if (self.end_date - self.start_date).days > 365:
                raise ValueError("Analytics date range cannot exceed 366 calendar days.")
        return self


class AnalyticsMetadata(BaseModel):
    hospital_id: int
    hospital_name: str
    run_id: UUID | None
    run_started_at: datetime | None
    seed: int | None
    department_id: int | None
    department_name: str | None
    start_date: date | None
    end_date: date | None
    time_zone: Literal["UTC"] = "UTC"
    snapshot_cadence: str = "daily at 12:00 UTC"
    has_data: bool


class AnalyticsOverviewMetrics(BaseModel):
    operational_beds: int
    occupied_beds_latest: int | None
    available_beds_latest: int | None
    latest_occupancy_pct: float | None
    latest_occupancy_date: date | None
    departments_reporting_latest: int
    departments_expected: int
    average_occupancy_pct: float | None
    peak_occupancy_pct: float | None
    admissions: int
    discharges: int
    transfers: int
    occupancy_snapshots: int


class AnalyticsOverviewRead(BaseModel):
    metadata: AnalyticsMetadata
    metrics: AnalyticsOverviewMetrics


class DailyOccupancyRead(BaseModel):
    date: date
    operational_beds: int
    occupied_beds: int
    available_beds: int
    occupancy_pct: float | None
    departments_reporting: int
    snapshot_count: int


class AnalyticsOccupancyRead(BaseModel):
    metadata: AnalyticsMetadata
    items: list[DailyOccupancyRead]


class DailyPatientFlowRead(BaseModel):
    date: date
    admissions: int
    discharges: int
    transfers: int


class AnalyticsPatientFlowRead(BaseModel):
    metadata: AnalyticsMetadata
    items: list[DailyPatientFlowRead]


class DepartmentUtilizationRead(BaseModel):
    department_id: int
    department_name: str
    department_code: str
    operational_beds: int
    occupied_beds_latest: int | None
    available_beds_latest: int | None
    latest_occupancy_pct: float | None
    average_occupancy_pct: float | None
    peak_occupancy_pct: float | None
    snapshots: int


class AnalyticsDepartmentsRead(BaseModel):
    metadata: AnalyticsMetadata
    items: list[DepartmentUtilizationRead]
