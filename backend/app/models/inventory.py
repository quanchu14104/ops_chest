from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.catalog import Product

MOVEMENT_TYPES = ("IN", "WASTE", "RETURN", "MARKDOWN", "ADJUST")


class Lot(Base):
    """Mot lo hang = mot lan nhan hang cua mot SKU, co HSD rieng. Xuat theo FEFO."""

    __tablename__ = "lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    qty_received: Mapped[int] = mapped_column(Integer)
    qty_remaining: Mapped[int] = mapped_column(Integer)
    received_date: Mapped[date] = mapped_column(Date)
    # Ngay cuoi cung con duoc ban
    expiry_date: Mapped[date] = mapped_column(Date, index=True)
    unit_cost: Mapped[int] = mapped_column(Integer)
    markdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    po_line_id: Mapped[int | None] = mapped_column(ForeignKey("po_lines.id"))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")

    product: Mapped[Product] = relationship()


class StockMovement(Base):
    """Bien dong kho khong phai ban hang (ban hang nam o DailySales)."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_mv_date_type", "date", "type"),
        Index("ix_mv_product_date", "product_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"))
    date: Mapped[date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(20))
    qty: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[int] = mapped_column(Integer)
    # IN/WASTE: gia von; RETURN: tien NCC hoan lai; MARKDOWN: tien giam gia da mat
    value: Mapped[int] = mapped_column(Integer)
    ref: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)


class DailySales(Base):
    __tablename__ = "daily_sales"
    __table_args__ = (Index("ix_sales_date", "date"),)

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    qty_sold: Mapped[int] = mapped_column(Integer)
    revenue: Mapped[int] = mapped_column(Integer)
    cogs: Mapped[int] = mapped_column(Integer)
    # Cua hang that khong biet luong khach muon mua ma het hang; du lieu gia lap thi co.
    lost_qty: Mapped[int | None] = mapped_column(Integer)
    stockout: Mapped[bool] = mapped_column(Boolean, default=False)
