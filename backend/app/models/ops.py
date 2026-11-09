from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.catalog import Product, Supplier

PROPOSAL_TYPES = ("PURCHASE_ORDER", "MARKDOWN", "RETURN", "DISPOSE", "DELIST", "DEMAND_HYPOTHESIS", "ORDER_ADJUST",
                  "STOCK_ADJUST")
PROPOSAL_STATUSES = ("PENDING", "APPROVED", "EXECUTED", "FAILED", "REJECTED", "EXPIRED", "SUPERSEDED")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    # manager: duoc duyet de xuat; staff: xem, chat, nhan hang
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(200))


class Proposal(Base):
    """De xuat do agent/job tao. Khong co tac dung phu cho den khi Store Manager duyet."""

    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    title: Mapped[str] = mapped_column(String(300))
    rationale: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    payload: Mapped[dict] = mapped_column(JSON)
    original_payload: Mapped[dict] = mapped_column(JSON)
    sm_edits: Mapped[list | None] = mapped_column(JSON)
    # Gia tri tien te uoc tinh (VND) de sap xep/hien thi
    est_value: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(50))  # agent / job / user:<name>
    chat_session_id: Mapped[int | None] = mapped_column(ForeignKey("chat_sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_by: Mapped[str | None] = mapped_column(String(50))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)
    execution_result: Mapped[dict | None] = mapped_column(JSON)
    # Khoa chong tao trung de xuat cho cung mot viec (vd: PO NCC X ngay Y)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)


class DemandHypothesis(Base):
    """Gia thuyet ve nhu cau cua Store Manager ("thu 7 co tran bong, bia ban gap ruoi"), da duoc duyet."""

    __tablename__ = "demand_hypotheses"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    sku: Mapped[str | None] = mapped_column(String(30), index=True)
    factor: Mapped[float] = mapped_column(Float)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)  # ACTIVE / EVALUATED / CANCELLED
    baseline_total: Mapped[float] = mapped_column(Float)  # du bao KHONG co gia thuyet, de cham dung/sai ve sau
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id"))
    created_by: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    result: Mapped[dict | None] = mapped_column(JSON)


class OrderAdjustment(Base):
    """He so dieu chinh so luong dat theo nhom hang, hoc tu cach SM hay sua va da duoc SM duyet."""

    __tablename__ = "order_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    factor: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reason: Mapped[str] = mapped_column(Text)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id"))
    created_by: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id"))
    status: Mapped[str] = mapped_column(String(20), default="SENT")  # SENT / RECEIVED / CANCELLED
    order_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date] = mapped_column(Date)
    total_value: Mapped[int] = mapped_column(Integer)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    pdf_path: Mapped[str | None] = mapped_column(String(300))

    supplier: Mapped[Supplier] = relationship()
    lines: Mapped[list["POLine"]] = relationship(back_populates="po", cascade="all, delete-orphan")


class POLine(Base):
    __tablename__ = "po_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[int] = mapped_column(Integer)
    received_qty: Mapped[int | None] = mapped_column(Integer)

    po: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    actor: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(50))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(50))
    detail: Mapped[dict | None] = mapped_column(JSON)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    username: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", order_by="ChatMessage.id", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user / assistant / tool
    content: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    tool_call_id: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(100))
    # Su kien hien thi (bieu do, the de xuat) de dung lai lich su chat tren UI
    ui_events: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
