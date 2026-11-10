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
    # CREDIT: hoan tien / tru vao don sau; EXCHANGE: doi hang moi mot-mot (doi date), pho bien voi dai ly VN
    return_mode: Mapped[str] = mapped_column(String(10), default="CREDIT", server_default="CREDIT")
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


class CategoryPolicy(Base):
    """Cau hinh theo nhom hang: rang buoc giam gia va gio giam gia.

    Muc tran giam gia va nhom cam khuyen mai la CAU HINH; can doi chieu Nghi dinh 81/2018/ND-CP (va van ban
    sua doi) truoc khi dung that, he thong khong khang dinh noi dung phap ly.
    """

    __tablename__ = "category_policies"

    category: Mapped[str] = mapped_column(String(100), primary_key=True)
    markdown_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    max_markdown_pct: Mapped[float] = mapped_column(Float, default=0.5)
    # Ty trong ban theo khung gio {morning, noon, afternoon, evening}; gio bat dau giam gia (sau khung dinh)
    daypart_shares: Mapped[dict | None] = mapped_column(JSON)
    markdown_hour: Mapped[int] = mapped_column(Integer, default=18)
    note: Mapped[str | None] = mapped_column(Text)


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
    # Ngay bat dau ban: SKU duoi 8 tuan la "hang moi", khong bi xet ngung nhap
    listed_date: Mapped[date | None] = mapped_column(Date)
    # Lan dem gan nhat (kiem ke hoac kiem date), de lap lich dem theo ABC
    last_counted_date: Mapped[date | None] = mapped_column(Date)

    supplier: Mapped[Supplier] = relationship(back_populates="products")
