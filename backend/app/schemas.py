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
    is_shared: bool = False


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserRead(BaseModel):
    id: int
    email: str
    role: Literal["admin", "user"]
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None


class AdminUserItem(UserRead):
    dataset_count: int = 0


class AdminUserPage(BaseModel):
    items: list[AdminUserItem]
    total: int
    page: int
    page_size: int
    pages: int

class AdminUserStats(BaseModel):
    total_accounts: int
    active_accounts: int
    deactivated_accounts: int
    administrators: int
    standard_users: int
    registrations_7d: int
    registrations_30d: int


class RegistrationActivityPoint(BaseModel):
    date: str
    registrations: int


class RegistrationActivity(BaseModel):
    days: int
    items: list[RegistrationActivityPoint]


class RegistrationPeriodStats(BaseModel):
    from_date: date | None
    to_date: date | None
    registered_accounts: int
    active_registered_accounts: int
    deactivated_registered_accounts: int
    new_administrators: int
    new_standard_users: int


class RegistrationSeriesPoint(BaseModel):
    period: str
    registrations: int


class RegistrationSeries(BaseModel):
    from_date: date | None
    to_date: date | None
    granularity: str
    items: list[RegistrationSeriesPoint]


class AccountSettingsRead(BaseModel):
    account: UserRead
    session_expires_at: datetime


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class AccountActivityItem(BaseModel):
    id: int
    actor_user_id: int | None
    actor_email: str | None
    target_user_id: int | None
    target_email: str | None
    run_id: str | None
    event_type: str
    occurred_at: datetime
    metadata: dict


class AccountActivityPage(BaseModel):
    items: list[AccountActivityItem]
    total: int
    page: int
    page_size: int
    pages: int


class WorkspaceSharingUpdate(BaseModel):
    is_shared: bool


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
    available_to_users: bool = False
    departments: list[DepartmentRead] = Field(default_factory=list)


class HospitalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str
    network_id: int | None = None
    available_to_users: bool = False

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
    available_to_users: bool | None = None

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


class AgeDistributionConfig(BaseModel):
    children_0_17: int = Field(default=20, ge=0, le=100)
    young_adults_18_35: int = Field(default=20, ge=0, le=100)
    middle_aged_adults_36_59: int = Field(default=20, ge=0, le=100)
    older_adults_60_79: int = Field(default=20, ge=0, le=100)
    elderly_80_plus: int = Field(default=20, ge=0, le=100)

    @model_validator(mode="after")
    def validate_total(self) -> "AgeDistributionConfig":
        if sum(self.model_dump().values()) != 100:
            raise ValueError("Age distribution percentages must total exactly 100%.")
        return self


class GenderDistributionConfig(BaseModel):
    male: int = Field(default=34, ge=0, le=100)
    female: int = Field(default=33, ge=0, le=100)
    other: int = Field(default=33, ge=0, le=100)

    @model_validator(mode="after")
    def validate_total(self) -> "GenderDistributionConfig":
        if sum(self.model_dump().values()) != 100:
            raise ValueError("Gender distribution percentages must total exactly 100%.")
        return self


class PatientProfileConfig(BaseModel):
    minimum_age: int = Field(default=0, ge=0, le=120)
    maximum_age: int = Field(default=120, ge=0, le=120)
    age_distribution: AgeDistributionConfig = Field(default_factory=AgeDistributionConfig)
    gender_distribution: GenderDistributionConfig = Field(default_factory=GenderDistributionConfig)

    @model_validator(mode="after")
    def validate_age_range_and_distribution(self) -> "PatientProfileConfig":
        if self.maximum_age < self.minimum_age:
            raise ValueError("Maximum patient age must be on or above the minimum patient age.")
        groups = (
            ("children_0_17", 0, 17),
            ("young_adults_18_35", 18, 35),
            ("middle_aged_adults_36_59", 36, 59),
            ("older_adults_60_79", 60, 79),
            ("elderly_80_plus", 80, 120),
        )
        for field_name, group_min, group_max in groups:
            if getattr(self.age_distribution, field_name) and (group_max < self.minimum_age or group_min > self.maximum_age):
                raise ValueError(f"Age group {field_name} has a non-zero share but does not overlap the configured age limits.")
        return self


class AdmissionArrivalProfile(BaseModel):
    planned_pct: int = Field(default=50, ge=0, le=100)
    emergency_pct: int = Field(default=50, ge=0, le=100)
    time_of_day: Literal["uniform", "daytime", "evening", "overnight"] = "uniform"
    day_of_week: Literal["uniform", "weekdays", "weekends"] = "uniform"

    @model_validator(mode="after")
    def validate_type_total(self) -> "AdmissionArrivalProfile":
        if self.planned_pct + self.emergency_pct != 100:
            raise ValueError("Planned and emergency admission percentages must total exactly 100%.")
        return self


class DepartmentDemandWeight(BaseModel):
    department_id: int = Field(gt=0)
    weight: float = Field(gt=0, le=10)


class LengthOfStayProfile(BaseModel):
    distribution: Literal["fixed", "triangular"] = "triangular"
    minimum_days: float = Field(default=0.5, gt=0, le=366)
    mode_days: float = Field(default=1.0, gt=0, le=366)
    maximum_days: float = Field(default=2.0, gt=0, le=366)

    @model_validator(mode="after")
    def validate_stay_bounds(self) -> "LengthOfStayProfile":
        if not self.minimum_days <= self.mode_days <= self.maximum_days:
            raise ValueError("Length of stay must satisfy minimum_days <= mode_days <= maximum_days.")
        if self.distribution == "fixed" and not (self.minimum_days == self.mode_days == self.maximum_days):
            raise ValueError("Fixed length of stay requires minimum, mode, and maximum days to be equal.")
        return self


class DepartmentLengthOfStayProfile(LengthOfStayProfile):
    department_id: int = Field(gt=0)


class WaitingQueueConfig(BaseModel):
    priority_policy: Literal["emergency_first", "planned_first", "arrival_order"] = "emergency_first"
    maximum_wait_hours: float = Field(default=24, ge=0, le=720)


class BedTurnaroundProfile(BaseModel):
    distribution: Literal["fixed", "triangular"] = "fixed"
    minimum_hours: float = Field(default=0.5, ge=0, le=168)
    mode_hours: float = Field(default=0.5, ge=0, le=168)
    maximum_hours: float = Field(default=0.5, ge=0, le=168)

    @model_validator(mode="after")
    def validate_turnaround_bounds(self) -> "BedTurnaroundProfile":
        if not self.minimum_hours <= self.mode_hours <= self.maximum_hours:
            raise ValueError("Turnaround duration must satisfy minimum_hours <= mode_hours <= maximum_hours.")
        if self.distribution == "fixed" and not (self.minimum_hours == self.mode_hours == self.maximum_hours):
            raise ValueError("Fixed turnaround requires minimum, mode, and maximum hours to be equal.")
        return self


class DepartmentBedTurnaroundProfile(BedTurnaroundProfile):
    department_id: int = Field(gt=0)


class GenerationConfig(BaseModel):
    start_date: date
    end_date: date
    target_admissions: int = Field(ge=0, le=5000)
    target_occupancy_pct: int = Field(ge=0, le=100)
    seed: int = Field(ge=0, le=2_147_483_647)
    scenario: Literal[
        "normal_operations",
        "high_patient_inflow",
        "seasonal_disease_surge",
        "emergency_surge",
        "low_occupancy",
    ] = "normal_operations"
    patient_profile: PatientProfileConfig = Field(default_factory=PatientProfileConfig)
    arrival_profile: AdmissionArrivalProfile = Field(default_factory=AdmissionArrivalProfile)
    department_demand_weights: list[DepartmentDemandWeight] = Field(default_factory=list)
    length_of_stay_profile: LengthOfStayProfile = Field(default_factory=LengthOfStayProfile)
    department_length_of_stay_profiles: list[DepartmentLengthOfStayProfile] = Field(default_factory=list)
    waiting_queue: WaitingQueueConfig = Field(default_factory=WaitingQueueConfig)
    bed_turnaround_profile: BedTurnaroundProfile = Field(default_factory=BedTurnaroundProfile)
    department_bed_turnaround_profiles: list[DepartmentBedTurnaroundProfile] = Field(default_factory=list)
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
        weight_ids = [entry.department_id for entry in self.department_demand_weights]
        if len(set(weight_ids)) != len(weight_ids):
            raise ValueError("Department demand weights must not contain duplicate department IDs.")
        stay_profile_ids = [entry.department_id for entry in self.department_length_of_stay_profiles]
        if len(set(stay_profile_ids)) != len(stay_profile_ids):
            raise ValueError("Department length-of-stay profiles must not contain duplicate department IDs.")
        turnaround_ids = [entry.department_id for entry in self.department_bed_turnaround_profiles]
        if len(set(turnaround_ids)) != len(turnaround_ids):
            raise ValueError("Department bed turnaround profiles must not contain duplicate department IDs.")
        if self.department_ids is not None and any(department_id not in self.department_ids for department_id in weight_ids):
            raise ValueError("Department demand weights must refer to selected departments.")
        if self.department_ids is not None and any(department_id not in self.department_ids for department_id in stay_profile_ids):
            raise ValueError("Department length-of-stay profiles must refer to selected departments.")
        if self.department_ids is not None and any(department_id not in self.department_ids for department_id in turnaround_ids):
            raise ValueError("Department bed turnaround profiles must refer to selected departments.")
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
    projected_admissions: int
    target_occupancy_pct: int
    scenario: Literal[
        "normal_operations",
        "high_patient_inflow",
        "seasonal_disease_surge",
        "emergency_surge",
        "low_occupancy",
    ]
    patient_profile: PatientProfileConfig
    arrival_profile: AdmissionArrivalProfile
    length_of_stay_profile: LengthOfStayProfile
    department_length_of_stay_profiles: list[DepartmentLengthOfStayProfile]
    projected_discharges: int
    projected_ongoing_admissions: int
    projected_assigned_admissions: int = 0
    projected_waiting_patients: int = 0
    projected_max_wait_exceeded: int = 0
    projected_unresolved_requests: int = 0
    projected_average_wait_minutes: float = 0
    projected_maximum_wait_minutes: float = 0
    projected_turnaround_events: int = 0
    projected_beds_cleaning_at_window_end: int = 0
    waiting_queue: WaitingQueueConfig = Field(default_factory=WaitingQueueConfig)
    bed_turnaround_profile: BedTurnaroundProfile = Field(default_factory=BedTurnaroundProfile)
    department_bed_turnaround_profiles: list[DepartmentBedTurnaroundProfile] = Field(default_factory=list)
    effective_admission_mix: dict[str, int]
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
    waiting_queue_count: int | None = None
    bed_turnaround_count: int | None = None
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
    run_id: UUID | None = None
    scenario: Literal["normal_operations", "high_patient_inflow", "seasonal_disease_surge", "emergency_surge", "low_occupancy"] | None = None

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
    scenario: str | None = None
    scenario_name: str | None = None
    patient_profile: dict | None = None
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
    lowest_occupancy_pct: float | None
    average_length_of_stay_hours: float | None
    admissions: int
    discharges: int
    transfers: int
    occupancy_snapshots: int


class AnalyticsOverviewRead(BaseModel):
    metadata: AnalyticsMetadata
    metrics: AnalyticsOverviewMetrics
    insights: list[dict] = Field(default_factory=list)


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
    lowest_occupancy_pct: float | None = None
    snapshots: int
    admissions: int = 0
    admission_share_pct: float | None = None
    incoming_transfers: int = 0
    outgoing_transfers: int = 0
    daily_occupancy: list[dict] = Field(default_factory=list)


class AnalyticsDepartmentsRead(BaseModel):
    metadata: AnalyticsMetadata
    items: list[DepartmentUtilizationRead]
    transfer_routes: list[dict] = Field(default_factory=list)


class AnalyticsRunOption(BaseModel):
    run_id: UUID
    hospital_id: int
    hospital_name: str
    started_at: datetime
    completed_at: datetime
    start_date: date | None
    end_date: date | None
    scenario: str | None
    scenario_name: str | None
    seed: int
    patient_profile: dict | None
    patients_count: int
    admissions_count: int
    departments: list[dict]


class AnalyticsRunOptionsRead(BaseModel):
    items: list[AnalyticsRunOption]


class AnalyticsComparisonRequest(BaseModel):
    run_ids: list[UUID] = Field(min_length=2, max_length=10)
    baseline_run_id: UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    department_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_comparison(self) -> "AnalyticsComparisonRequest":
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("Select each generation run only once.")
        if self.baseline_run_id is not None and self.baseline_run_id not in self.run_ids:
            raise ValueError("The baseline run must be included in the comparison.")
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Provide both comparison dates or omit both to use each run's full period.")
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValueError("End date must be on or after the start date.")
            if (self.end_date - self.start_date).days > 365:
                raise ValueError("Analytics date range cannot exceed 366 calendar days.")
        return self


class AnalyticsComparedDepartment(BaseModel):
    department_id: int
    department_name: str
    department_code: str
    admissions: int
    admission_share_pct: float | None
    average_occupancy_pct: float | None
    peak_occupancy_pct: float | None
    lowest_occupancy_pct: float | None = None
    incoming_transfers: int
    outgoing_transfers: int
    daily_occupancy: list[dict] = Field(default_factory=list)


class AnalyticsComparedRun(BaseModel):
    run_id: UUID
    hospital_id: int
    hospital_name: str
    workspace_id: int
    start_date: date | None
    end_date: date | None
    scenario: str | None
    scenario_name: str | None
    patient_profile: dict | None
    seed: int
    patients: int
    admissions: int
    discharges: int
    transfers: int
    average_occupancy_pct: float | None
    peak_occupancy_pct: float | None
    lowest_occupancy_pct: float | None
    average_length_of_stay_hours: float | None
    departments: list[AnalyticsComparedDepartment]
    transfer_routes: list[dict]
    occupancy_trend: list[DailyOccupancyRead]
    metrics_vs_baseline: dict[str, dict[str, float | None]]


class AnalyticsComparisonRead(BaseModel):
    baseline_run_id: UUID
    items: list[AnalyticsComparedRun]


class AnalyticsInsight(BaseModel):
    kind: str
    text: str
    source: Literal["calculated_rule"] = "calculated_rule"
    metrics: dict[str, int | float | str | None]


class AnalyticsInsightsRead(BaseModel):
    run_id: UUID
    items: list[AnalyticsInsight]


class DatasetRecordCounts(BaseModel):
    patients: int = 0
    admissions: int = 0
    discharges: int = 0
    bed_assignments: int = 0
    bed_transfers: int = 0
    occupancy_snapshots: int = 0
    waiting_queue: int | None = None
    bed_turnaround: int | None = None


class DatasetValidationSummary(BaseModel):
    validation_id: UUID
    validated_at: datetime
    score: float
    status: Literal["passed", "passed_with_warnings", "failed"]
    checks_performed: int
    checks_passed: int
    checks_failed: int


class DatasetDepartmentRead(BaseModel):
    department_id: int
    code: str
    name: str


class DatasetAnalyticsSummary(BaseModel):
    latest_snapshot_date: date | None
    latest_occupancy_pct: float | None
    average_occupancy_pct: float | None
    peak_occupancy_pct: float | None
    occupied_beds_latest: int | None
    available_beds_latest: int | None
    recorded_days: int
    waiting_requests: int | None = None
    assigned_immediately: int | None = None
    patients_who_waited: int | None = None
    unresolved_requests: int | None = None
    average_wait_seconds: float | None = None
    maximum_wait_seconds: int | None = None
    turnaround_events: int | None = None
    average_turnaround_seconds: float | None = None
    turnaround_bed_hours: float | None = None


class DatasetListItem(BaseModel):
    run_id: UUID
    workspace_id: int
    hospital_id: int
    hospital_name: str
    started_at: datetime
    completed_at: datetime | None
    status: Literal["generating", "completed", "failed"]
    scenario_name: str | None
    seed: int
    configured_start_date: date | None
    configured_end_date: date | None
    target_occupancy_pct: int | None
    generator_version: str | None
    record_counts: DatasetRecordCounts
    latest_validation: DatasetValidationSummary | None


class DatasetLibraryRead(BaseModel):
    items: list[DatasetListItem]
    total: int
    page: int
    page_size: int
    pages: int


class DatasetRunDetailRead(DatasetListItem):
    generation_config: dict
    selected_departments: list[DatasetDepartmentRead]
    validation_reports: list[DatasetValidationSummary]
    analytics_summary: DatasetAnalyticsSummary


class DatasetPreviewColumn(BaseModel):
    key: str
    label: str


class DatasetPreviewRead(BaseModel):
    run_id: UUID
    entity: Literal["patients", "admissions", "discharges", "bed_assignments", "bed_transfers", "occupancy_snapshots", "waiting_queue", "bed_turnaround"]
    columns: list[DatasetPreviewColumn]
    items: list[dict]
    total: int
    page: int
    page_size: int
    pages: int
