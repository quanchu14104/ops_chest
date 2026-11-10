from datetime import date

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

FRESHNESS_CLASSES = ("FRESH", "SHORT", "LONG")  # <=3 ngay, <=30 ngay, dai


class Supplier(Base):
    """Dai ly / nha cung cap ma cua hang lam viec truc tiep."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    lead_time_days: Mapped[int] = mapped_column(Integer)
    # 0=Thu 2 ... 6=Chu nhat
    order_weekdays: Mapped[list[int]] = mapped_column(JSON)
    min_order_value: Mapped[int] = mapped_column(Integer, default=0)
    # Ngay NCC giao hang (0=Thu 2). None = giao moi ngay.
    delivery_weekdays: Mapped[list[int] | None] = mapped_column(JSON)

    products: Mapped[list["Product"]] = relationship(back_populates="supplier")
    agreements: Mapped[list["SupplierAgreement"]] = relationship(back_populates="supplier")
    closures: Mapped[list["SupplierClosure"]] = relationship(back_populates="supplier", order_by="SupplierClosure.start_date")

    def is_closed(self, d: date) -> bool:
        return any(c.start_date <= d <= c.end_date for c in self.closures)

    def schedule(self, order_day: date) -> tuple[date, int]:
        """(ngay hang ve, so ngay can phu) theo lich dat, lich giao va lich nghi."""
        from app.engines.replenishment import schedule

        return schedule(order_day, self.lead_time_days, self.order_weekdays, self.delivery_weekdays, self.is_closed)

    def agreement_on(self, d: date) -> "SupplierAgreement | None":
        """Thoa thuan co hieu luc vao ngay d; nhieu ban cung hieu luc thi lay ban ky sau cung."""
        valid = [a for a in self.agreements if a.valid_from <= d <= a.valid_to]
        return max(valid, key=lambda a: (a.valid_from, a.id), default=None)


class SupplierAgreement(Base):
    """Hop dong nguyen tac: luu DIEU KHOAN de engine tinh toan, khong phai van ban phap ly."""

    __tablename__ = "supplier_agreements"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    discount_pct: Mapped[float] = mapped_column(Float, default=0.0)
    accepts_near_expiry_return: Mapped[bool] = mapped_column(Boolean, default=False)
    # Chi duoc tra neu con >= N ngay truoc HSD
    return_min_days_before_expiry: Mapped[int] = mapped_column(Integer, default=0)
    return_credit_pct: Mapped[float] = mapped_column(Float, default=0.0)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    supplier: Mapped[Supplier] = relationship(back_populates="agreements")


class SupplierClosure(Base):
    """Ky nghi cua NCC (vd Tet): khong nhan dat, khong giao hang."""

    __tablename__ = "supplier_closures"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(200))

    supplier: Mapped[Supplier] = relationship(back_populates="closures")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), index=True)
    freshness_class: Mapped[str] = mapped_column(String(10))
    shelf_life_days: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[int] = mapped_column(Integer)  # VND
    unit_price: Mapped[int] = mapped_column(Integer)  # VND
    pack_size: Mapped[int] = mapped_column(Integer, default=1)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    is_traffic_driver: Mapped[bool] = mapped_column(Boolean, default=False)
    substitute_skus: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE / DELISTED
    # Rut khoi ke truoc HSD bao nhieu ngay (goi y FRESH 0, SHORT 1, LONG 7). Ngay ban cuoi = HSD - so nay.
    pull_days_before_expiry: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Suc chua ke/tu (don vi). None = khong gioi han. Engine khong de xuat vuot so nay.
    max_stock_qty: Mapped[int | None] = mapped_column(Integer)
    # Ton trung bay toi thieu cua hang ben: ke trong mot nua ban kem hon ke day
    min_display_qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    supplier: Mapped[Supplier] = relationship(back_populates="products")
