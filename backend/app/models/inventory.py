from datetime import date, timedelta

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.catalog import Product

MOVEMENT_TYPES = ("IN", "WASTE", "RETURN", "MARKDOWN", "ADJUST")
# Ly do huy (WASTE) va dieu chinh (ADJUST). Tach ly do de biet tu mat hong va dat du la hai van de khac nhau.
WASTE_REASONS = {
    "EXPIRED": "Hết hạn",
    "DAMAGED": "Vỡ, móp, rách bao bì",
    "SPOILED": "Hỏng do bảo quản (tủ mát, nhiệt độ)",
    "SUPPLIER_DEFECT": "Lỗi từ nhà cung cấp",
    "OTHER": "Lý do khác",
}
ADJUST_REASONS = {
    "COUNT": "Kiểm kê theo SKU",
    "DATE_CHECK": "Kiểm date theo lô",
    "SHRINK": "Hao hụt khi rút kệ/ghi hủy",
}
# ACTIVE: dang ban. PULLED: da go khoi ke (qua ngay ban cuoi), cho SM duyet ghi huy, khong con la ton ban duoc.
# Cac trang thai dong: SOLD / WASTED / RETURNED / ADJUSTED.
# RETURN_PENDING: da tach ra cho NCC lay (phieu tra dang mo), khong ban, khong tinh ton.
LOT_STATUSES = ("ACTIVE", "PULLED", "RETURN_PENDING", "SOLD", "WASTED", "RETURNED", "ADJUSTED")


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
    # So nhan vien thuc go khoi ke (co the khac so tren so) va ngay go
    pulled_qty: Mapped[int | None] = mapped_column(Integer)
    pulled_date: Mapped[date | None] = mapped_column(Date)

    product: Mapped[Product] = relationship()

    @property
    def sell_by(self) -> date:
        """Ngay ban cuoi = HSD - so ngay rut ke truoc han cua mat hang."""
        return self.expiry_date - timedelta(days=self.product.pull_days_before_expiry or 0)


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
    # WASTE: WASTE_REASONS; ADJUST: ADJUST_REASONS
    reason: Mapped[str | None] = mapped_column(String(20))


class InventorySnapshot(Base):
    """Gia tri ton cuoi ngay (gia von), de tinh ton trung binh dung cho tung ky."""

    __tablename__ = "inventory_snapshots"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer)


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
    # Ban nho giam gia khong phai nhu cau binh thuong: tach rieng de du bao khong bi thoi len
    discounted_qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    discount_pct: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    evening_qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
