"""Core workspace, hospital, department, and bed tables."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
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
