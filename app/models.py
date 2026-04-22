from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class UserRole(str, enum.Enum):
    IT_HEAD     = "it_head"
    ADMIN       = "admin"
    SUPER_ADMIN = "super_admin"


class BudgetStatus(str, enum.Enum):
    DRAFT             = "draft"
    SUBMITTED         = "submitted"
    ADMIN_APPROVED    = "admin_approved"
    REJECTED_BY_ADMIN = "rejected_by_admin"
    FINAL_APPROVED    = "final_approved"
    REJECTED_BY_CEO   = "rejected_by_ceo"


class ExpenseSubType(str, enum.Enum):
    HARDWARE       = "Hardware"
    MANAGED        = "Managed Services"
    SUBSCRIPTION   = "Subscription renewal"
    TM_SERVICES    = "T&M Services"
    PROFESSIONAL   = "Professional Services"
    COMPLIANCE     = "Cost of being compliant"
    MISCELLANEOUS  = "Miscellaneous"


class OldNew(str, enum.Enum):
    OLD                 = "Old"
    OLD_BUT_INCREMENTAL = "Old But Incremental"
    NEW                 = "New"


class ApprovalAction(str, enum.Enum):
    APPROVED  = "approved"
    REJECTED  = "rejected"
    FORWARDED = "forwarded"


class User(Base):
    __tablename__ = "users"
    id         = Column(Integer, primary_key=True, index=True)
    full_name  = Column(String(100), nullable=False)
    email      = Column(String(150), unique=True, nullable=False, index=True)
    password   = Column(String(255), nullable=False)
    role       = Column(Enum(UserRole), nullable=False, default=UserRole.IT_HEAD)
    department = Column(String(100), nullable=True)
    spoc_name  = Column(String(100), nullable=True)
    cost_code  = Column(Integer, nullable=True)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    budget_lines   = relationship("BudgetLine", back_populates="submitted_by_user")
    approvals      = relationship("Approval", back_populates="action_by_user")
    uploaded_files = relationship("UploadedFile", back_populates="uploaded_by_user")


class UploadedFile(Base):
    __tablename__     = "uploaded_files"
    id                = Column(Integer, primary_key=True, index=True)
    original_name     = Column(String(255), nullable=False)
    stored_name       = Column(String(255), nullable=False)
    uploaded_by       = Column(Integer, ForeignKey("users.id"), nullable=False)
    upload_at         = Column(DateTime(timezone=True), server_default=func.now())
    rows_total        = Column(Integer, nullable=True)
    rows_imported     = Column(Integer, nullable=True)
    rows_failed       = Column(Integer, nullable=True, default=0)   # NEW
    status            = Column(String(50), default="pending")
    error_report_path = Column(String(500), nullable=True)           # NEW: path to error xlsx
    correlation_id    = Column(String(32), nullable=True)            # NEW: trace ID
    file_size_bytes   = Column(Integer, nullable=True)               # NEW

    uploaded_by_user = relationship("User", back_populates="uploaded_files")
    budget_lines     = relationship("BudgetLine", back_populates="import_file")


class BudgetLine(Base):
    __tablename__ = "budget_lines"
    id                    = Column(Integer, primary_key=True, index=True)
    budget_key_current    = Column(String(50), unique=True, nullable=False)
    budget_key_previous   = Column(Text, nullable=True)
    old_new               = Column(Enum(OldNew), nullable=False)
    business_name         = Column(String(100), nullable=False)
    cost_code             = Column(Integer, nullable=False, default=0)
    submitted_by          = Column(Integer, ForeignKey("users.id"), nullable=False)
    it_head_name          = Column(String(100), nullable=True)
    spoc_name             = Column(String(200), nullable=True)
    expense_sub_type      = Column(Enum(ExpenseSubType), nullable=False)
    expense_description   = Column(Text, nullable=True)
    description           = Column(Text, nullable=True)
    application_platform  = Column(String(200), nullable=True)
    vendor_name           = Column(String(200), nullable=True)
    resource_count        = Column(Integer, nullable=True)
    budget_amt_current_fy = Column(Float, nullable=False, default=0)
    projected_consumption = Column(Float, nullable=True)
    budget_amt_next_fy    = Column(Float, nullable=False, default=0)
    diff_a_minus_b        = Column(Float, nullable=True)
    diff_c_minus_b        = Column(Float, nullable=True)
    diff_c_minus_a        = Column(Float, nullable=True)
    detailed_reasoning    = Column(Text, nullable=True)
    import_file_id        = Column(Integer, ForeignKey("uploaded_files.id"), nullable=True)
    status                = Column(Enum(BudgetStatus), default=BudgetStatus.DRAFT, nullable=False)
    created_at            = Column(DateTime(timezone=True), server_default=func.now())
    updated_at            = Column(DateTime(timezone=True), onupdate=func.now())

    submitted_by_user = relationship("User", back_populates="budget_lines")
    approvals         = relationship("Approval", back_populates="budget_line")
    import_file       = relationship("UploadedFile", back_populates="budget_lines")


class Approval(Base):
    __tablename__ = "approvals"
    id             = Column(Integer, primary_key=True, index=True)
    budget_line_id = Column(Integer, ForeignKey("budget_lines.id"), nullable=False)
    action_by      = Column(Integer, ForeignKey("users.id"), nullable=False)
    action         = Column(Enum(ApprovalAction), nullable=False)
    comment        = Column(Text, nullable=True)
    action_at      = Column(DateTime(timezone=True), server_default=func.now())

    budget_line    = relationship("BudgetLine", back_populates="approvals")
    action_by_user = relationship("User", back_populates="approvals")


# ── NEW: Audit Log Table ──────────────────────────────────────
# Every important action (insert/update/delete/login/import)
# gets a row here. Immutable — never updated, only inserted.
class AuditLog(Base):
    __tablename__  = "audit_logs"
    id             = Column(Integer, primary_key=True, index=True)
    action_type    = Column(String(50),  nullable=False)   # INSERT, UPDATE, DELETE, LOGIN, IMPORT, APPROVE, REJECT
    table_name     = Column(String(100), nullable=True)    # which DB table was affected
    record_id      = Column(Integer,     nullable=True)    # PK of affected record
    user_id        = Column(Integer,     nullable=True)    # who did it
    user_email     = Column(String(150), nullable=True)    # denormalized for easy reading
    description    = Column(Text,        nullable=False)   # human-readable summary
    old_value      = Column(Text,        nullable=True)    # JSON of previous state
    new_value      = Column(Text,        nullable=True)    # JSON of new state
    correlation_id = Column(String(32),  nullable=True)    # request trace ID
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


class Dummy1(Base):
    __tablename__ = "dummy1"
    id          = Column(Integer, primary_key=True, index=True)
    title       = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    ref_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    meta_json   = Column(Text, nullable=True)


class Dummy2(Base):
    __tablename__ = "dummy2"
    id           = Column(Integer, primary_key=True, index=True)
    event_type   = Column(String(100), nullable=True)
    event_data   = Column(Text, nullable=True)
    triggered_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())