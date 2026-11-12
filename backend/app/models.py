"""Core workspace, hospital, department, and bed tables."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    hospitals: Mapped[list["Hospital"]] = relationship(back_populates="workspace")
    networks: Mapped[list["HospitalNetwork"]] = relationship(back_populates="workspace")


class HospitalNetwork(Base):
    __tablename__ = "hospital_networks"
    __table_args__ = (UniqueConstraint("id", "workspace_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    workspace: Mapped[Workspace] = relationship(back_populates="networks")
    hospitals: Mapped[list["Hospital"]] = relationship(back_populates="network")


class Hospital(Base):
    __tablename__ = "hospitals"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_hospital_workspace_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    network_id: Mapped[int | None] = mapped_column(ForeignKey("hospital_networks.id", ondelete="RESTRICT"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(40, collation="NOCASE"), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    workspace: Mapped[Workspace] = relationship(back_populates="hospitals")
    network: Mapped[HospitalNetwork | None] = relationship(back_populates="hospitals")
    departments: Mapped[list["Department"]] = relationship(back_populates="hospital", order_by="Department.name")
    beds: Mapped[list["Bed"]] = relationship(back_populates="hospital")


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("hospital_id", "code", name="uq_department_hospital_code"),
        CheckConstraint("bed_capacity IS NULL OR bed_capacity > 0", name="ck_department_positive_capacity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40, collation="NOCASE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    bed_capacity: Mapped[int | None] = mapped_column(nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hospital: Mapped[Hospital] = relationship(back_populates="departments")
    beds: Mapped[list["Bed"]] = relationship(back_populates="department", order_by="Bed.code")


class Bed(Base):
    __tablename__ = "beds"
    __table_args__ = (
        UniqueConstraint("hospital_id", "code", name="uq_bed_hospital_code"),
        CheckConstraint("status IN ('planned', 'operational', 'out_of_service', 'retired')", name="ck_bed_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40, collation="NOCASE"), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="general")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="operational")
    hospital: Mapped[Hospital] = relationship(back_populates="beds")
    department: Mapped[Department] = relationship(back_populates="beds")


class GenerationRun(Base):
    __tablename__ = "generation_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_generation_run_idempotency"),
        CheckConstraint("status IN ('generating', 'completed', 'failed')", name="ck_generation_run_status"),
        Index("ix_generation_run_workspace_started", "workspace_id", "started_at"),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(36), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="generating")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    patients_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    admissions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discharges_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transfers_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshots_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    patients: Mapped[list["SyntheticPatient"]] = relationship(back_populates="run")
    admissions: Mapped[list["Admission"]] = relationship(back_populates="run")
    occupancy_snapshots: Mapped[list["OccupancySnapshot"]] = relationship(back_populates="run")


class SyntheticPatient(Base):
    __tablename__ = "synthetic_patients"
    __table_args__ = (
        UniqueConstraint("run_id", "synthetic_patient_id", name="uq_synthetic_patient_run_identifier"),
        CheckConstraint("age_band IN ('0-17', '18-34', '35-49', '50-64', '65-79', '80+')", name="ck_synthetic_patient_age_band"),
        Index("ix_synthetic_patient_hospital", "hospital_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("generation_runs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=False, index=True)
    synthetic_patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    age_band: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    run: Mapped[GenerationRun] = relationship(back_populates="patients")
    admissions: Mapped[list["Admission"]] = relationship(back_populates="patient")


class Admission(Base):
    __tablename__ = "admissions"
    __table_args__ = (
        UniqueConstraint("run_id", "patient_id", name="uq_admission_run_patient"),
        CheckConstraint("status IN ('admitted', 'discharged')", name="ck_admission_status"),
        Index("ix_admission_hospital_time", "hospital_id", "admitted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("generation_runs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=False, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("synthetic_patients.id", ondelete="CASCADE"), nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    initial_bed_id: Mapped[int] = mapped_column(ForeignKey("beds.id", ondelete="RESTRICT"), nullable=False)
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="discharged")
    run: Mapped[GenerationRun] = relationship(back_populates="admissions")
    patient: Mapped[SyntheticPatient] = relationship(back_populates="admissions")
    discharge: Mapped["Discharge | None"] = relationship(back_populates="admission", uselist=False)
    assignments: Mapped[list["BedAssignment"]] = relationship(back_populates="admission")
    transfers: Mapped[list["BedTransfer"]] = relationship(back_populates="admission")


class Discharge(Base):
    __tablename__ = "discharges"
    __table_args__ = (UniqueConstraint("admission_id", name="uq_discharge_admission"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("generation_runs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=False, index=True)
    admission_id: Mapped[int] = mapped_column(ForeignKey("admissions.id", ondelete="CASCADE"), nullable=False)
    discharged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    admission: Mapped[Admission] = relationship(back_populates="discharge")


class BedAssignment(Base):
    __tablename__ = "bed_assignments"
    __table_args__ = (
        CheckConstraint("end_at IS NULL OR end_at > start_at", name="ck_bed_assignment_positive_interval"),
        Index("ix_bed_assignment_bed_interval", "bed_id", "start_at", "end_at"),
        Index("ix_bed_assignment_admission_interval", "admission_id", "start_at", "end_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("generation_runs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=False, index=True)
    admission_id: Mapped[int] = mapped_column(ForeignKey("admissions.id", ondelete="CASCADE"), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    bed_id: Mapped[int] = mapped_column(ForeignKey("beds.id", ondelete="RESTRICT"), nullable=False, index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admission: Mapped[Admission] = relationship(back_populates="assignments")


class BedTransfer(Base):
    __tablename__ = "bed_transfers"
    __table_args__ = (
        UniqueConstraint("admission_id", "sequence_number", name="uq_transfer_admission_sequence"),
        CheckConstraint("sequence_number > 0", name="ck_transfer_positive_sequence"),
        CheckConstraint("source_bed_id != destination_bed_id", name="ck_transfer_different_beds"),
        Index("ix_bed_transfer_hospital_time", "hospital_id", "transferred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("generation_runs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=False, index=True)
    admission_id: Mapped[int] = mapped_column(ForeignKey("admissions.id", ondelete="CASCADE"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    destination_department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    source_bed_id: Mapped[int] = mapped_column(ForeignKey("beds.id", ondelete="RESTRICT"), nullable=False)
    destination_bed_id: Mapped[int] = mapped_column(ForeignKey("beds.id", ondelete="RESTRICT"), nullable=False)
    transferred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    admission: Mapped[Admission] = relationship(back_populates="transfers")


class OccupancySnapshot(Base):
    __tablename__ = "occupancy_snapshots"
    __table_args__ = (
        UniqueConstraint("run_id", "department_id", "snapshot_at", name="uq_snapshot_run_department_time"),
        CheckConstraint("operational_beds >= 0 AND occupied_beds >= 0", name="ck_snapshot_nonnegative_counts"),
        CheckConstraint("occupied_beds <= operational_beds", name="ck_snapshot_capacity"),
        CheckConstraint("available_beds = operational_beds - occupied_beds", name="ck_snapshot_availability"),
        CheckConstraint("occupancy_pct IS NULL OR (occupancy_pct >= 0 AND occupancy_pct <= 100)", name="ck_snapshot_occupancy_range"),
        Index("ix_snapshot_hospital_time", "hospital_id", "snapshot_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("generation_runs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="RESTRICT"), nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    operational_beds: Mapped[int] = mapped_column(Integer, nullable=False)
    occupied_beds: Mapped[int] = mapped_column(Integer, nullable=False)
    available_beds: Mapped[int] = mapped_column(Integer, nullable=False)
    occupancy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    run: Mapped[GenerationRun] = relationship(back_populates="occupancy_snapshots")
