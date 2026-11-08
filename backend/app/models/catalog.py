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

    products: Mapped[list["Product"]] = relationship(back_populates="supplier")
    agreements: Mapped[list["SupplierAgreement"]] = relationship(back_populates="supplier")


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

    supplier: Mapped[Supplier] = relationship(back_populates="products")
