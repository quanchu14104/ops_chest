"""Danh muc hang & nha cung cap GIA LAP (ten thuong hieu hu cau)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class SupplierSpec:
    code: str
    name: str
    email: str
    lead_time_days: int
    order_weekdays: list[int]
    min_order_value: int
    accepts_return: bool = False
    return_min_days: int = 0
    return_credit_pct: float = 0.0
    discount_pct: float = 0.0
    phone: str = ""
    delivery_weekdays: list[int] | None = None  # None = giao moi ngay
    return_mode: str = "CREDIT"  # CREDIT / EXCHANGE (doi date)
    closures: list[tuple] = field(default_factory=list)  # [(start, end, ly do)]

    def is_closed(self, d) -> bool:
        return any(a <= d <= b for a, b, _ in self.closures)


@dataclass
class ProductSpec:
    sku: str
    name: str
    category: str
    group: str  # nhom hanh vi nhu cau (thu trong tuan, mua vu, Tet, thoi tiet)
    freshness_class: str
    shelf_life_days: int
    unit_cost: int
    unit_price: int
    pack_size: int
    base_rate: float  # luong ban trung binh/ngay
    dispersion_k: float  # cang nho cang that thuong
    is_traffic_driver: bool
    supplier_code: str
    substitutes: list[str] = field(default_factory=list)
    max_stock_qty: int | None = None  # suc chua ke/tu
    min_display_qty: int = 0  # ton trung bay toi thieu (hang ben)


ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
# So ngay rut khoi ke truoc HSD (ngay ban cuoi = HSD - so nay). Bo backtest van ban den HSD (xem docs).
PULL_DAYS = {"FRESH": 0, "SHORT": 1, "LONG": 7}

SUPPLIERS = [
    SupplierSpec("NCC01", "Bếp Trung Tâm Hạnh Phúc", "dathang@bephanhphuc.test", 1, ALL_DAYS, 300_000),
    SupplierSpec("NCC02", "Lò Bánh Sài Gòn Xanh", "order@lobanhsgx.test", 1, ALL_DAYS, 200_000),
    SupplierSpec("NCC03", "Công ty Sữa Đồng Cỏ Xanh", "sales@suadongco.test", 1, [0, 2, 4], 500_000,
                 True, 3, 0.7, 0.02),
    SupplierSpec("NCC04", "Bánh Ngọt Mây Hồng", "kinhdoanh@banhmayhong.test", 2, [1, 4], 300_000, True, 2, 0.5),
    SupplierSpec("NCC05", "Đại lý Nước Giải Khát Thành Đạt", "dathang@ngkthanhdat.test", 2, [0, 3], 1_500_000,
                 True, 30, 0.8, 0.03),
    SupplierSpec("NCC06", "NPP Bia Rạng Đông", "sales@biarangdong.test", 2, [2], 1_000_000),
    SupplierSpec("NCC07", "Đại lý Thực phẩm Khô An Phát", "order@anphatfood.test", 3, [1], 1_000_000,
                 True, 30, 0.6, 0.02),
    SupplierSpec("NCC08", "Kem Tuyết Sơn", "dathang@kemtuyetson.test", 1, [0, 3], 500_000),
    SupplierSpec("NCC09", "NPP Hóa Mỹ Phẩm Phương Nam", "sales@hmpphuongnam.test", 3, [4], 800_000,
                 True, 60, 0.9),
    SupplierSpec("NCC10", "Trang Trại Trứng Gà Vàng", "order@trunggavang.test", 1, [0, 3], 200_000),
]
for i, s in enumerate(SUPPLIERS):
    s.phone = f"0909 {100 + i:03d} {200 + i * 7:03d}"


def _tet_closures() -> None:
    """Dai ly nghi Tet: bep/lo banh nghi lau nhat, nuoc giai khat/thuc pham kho nghi ngan hon."""
    from datetime import timedelta

    from app.engines.calendar import TET_DATES

    days = {"NCC01": (-1, 6), "NCC02": (-1, 6), "NCC04": (-2, 6), "NCC05": (-1, 4), "NCC06": (-1, 4),
            "NCC07": (-2, 5), "NCC09": (-2, 6), "NCC10": (-1, 3)}
    for s in SUPPLIERS:
        if s.code in days:
            a, b = days[s.code]
            s.closures = [(tet + timedelta(days=a), tet + timedelta(days=b), f"Nghỉ Tết {tet.year}")
                          for tet in TET_DATES.values()]


_tet_closures()
# Khung gio ban ma cua hang khai bao cho tung nhom (seed vao category_policies). Engine dat gio giam gia ngay sau
# khung dinh: com hop sau trua (14h), banh mi sau sang (11h). Nhom khac giu gio vang 18h.
ENGINE_DAYPARTS = {
    "Cơm hộp & cơm nắm": (0.15, 0.5, 0.15, 0.2),
    "Bánh mì, sandwich & bánh bao": (0.5, 0.2, 0.1, 0.2),
    "Salad, trái cây & xôi": (0.3, 0.35, 0.15, 0.2),
}


def category_policy(category: str) -> dict:
    """Cau hinh nhom hang cho demo/backtest: duoc giam gia, tran 50% (can doi chieu quy dinh), gio giam gia."""
    from app.engines.disposition import DEFAULT_DAYPART_SHARES, peak_end_hour, share_after

    shares = ENGINE_DAYPARTS.get(category, DEFAULT_DAYPART_SHARES)
    hour = peak_end_hour(shares) if category in ENGINE_DAYPARTS else 18
    return {"markdown_allowed": True, "max_markdown_pct": 0.5, "daypart_shares": list(shares), "markdown_hour": hour,
            "remaining_share": share_after(shares, hour)}


# Dai ly sua doi date (doi hang moi) thay vi hoan tien
SUPPLIERS[2].return_mode = "EXCHANGE"
# Nuoc giai khat va hoa my pham chi giao vao mot so ngay trong tuan
SUPPLIERS[4].delivery_weekdays = [1, 2, 4, 5]
SUPPLIERS[8].delivery_weekdays = [0, 1, 2, 3, 4]
# Suc chua tu dong (don vi) theo nhom, ton trung bay toi thieu cho hang ben
CAPACITY = {"ice_cream": 36}
MIN_DISPLAY = {"household": 2, "dry_goods": 2}

GROUP_K = {
    "office_food": 12, "bakery": 6, "dairy": 15, "eggs": 10, "water": 25, "soft_drink": 20,
    "tea_energy": 15, "coffee": 12, "beer": 6, "noodle": 15, "snack": 6, "candy": 5,
    "dry_goods": 3, "ice_cream": 6, "household": 2.5,
}

COST_RATIO = {
    "office_food": 0.62, "bakery": 0.6, "dairy": 0.72, "eggs": 0.8, "water": 0.65, "soft_drink": 0.72,
    "tea_energy": 0.7, "coffee": 0.68, "beer": 0.8, "noodle": 0.75, "snack": 0.7, "candy": 0.65,
    "dry_goods": 0.82, "ice_cream": 0.65, "household": 0.7,
}


def _items():
    """(prefix, category, group, supplier, class, shelf, pack, [(name, price, rate, traffic)])"""
    out = []

    out.append(("COM", "Cơm hộp & cơm nắm", "office_food", "NCC01", "FRESH", 1, 1, [
        ("Cơm gà xối mỡ", 39000, 6, False), ("Cơm sườn nướng", 42000, 7, True),
        ("Cơm thịt kho trứng", 38000, 5, False), ("Cơm chiên Dương Châu", 35000, 4, False),
        ("Cơm bò lúc lắc", 45000, 3, False), ("Cơm cá kho tộ", 40000, 2.5, False),
        ("Cơm gà teriyaki", 42000, 3, False), ("Cơm chay thập cẩm", 35000, 1.2, False),
    ]))
    out.append(("CMN", "Cơm hộp & cơm nắm", "office_food", "NCC01", "FRESH", 2, 1, [
        ("Cơm nắm cá hồi", 18000, 5, False), ("Cơm nắm gà mayo", 16000, 4, False),
        ("Cơm nắm rong biển", 14000, 3, False), ("Cơm nắm ngũ cốc", 15000, 1.5, False),
        ("Cơm nắm thịt kho", 16000, 2, False), ("Cơm nắm tôm", 18000, 1, False),
    ]))
    out.append(("SAL", "Salad, trái cây & xôi", "office_food", "NCC01", "FRESH", 1, 1, [
        ("Salad gà", 35000, 1.5, False), ("Salad cá ngừ", 35000, 1.2, False),
        ("Trái cây cắt hộp dưa hấu", 20000, 2.5, False), ("Trái cây cắt hộp thơm", 20000, 1.8, False),
        ("Trái cây hỗn hợp hộp", 28000, 2, False), ("Xôi gà", 25000, 3, False),
    ]))
    out.append(("BMI", "Bánh mì, sandwich & bánh bao", "office_food", "NCC02", "FRESH", 1, 1, [
        ("Bánh mì thịt nguội", 20000, 8, True), ("Bánh mì chả lụa", 18000, 6, False),
        ("Bánh mì gà xé", 22000, 4, False), ("Bánh mì xíu mại", 20000, 3, False),
        ("Bánh mì ốp la", 15000, 3, False), ("Bánh mì pate", 15000, 2, False),
        ("Bánh mì bò kho", 25000, 1.5, False), ("Bánh mì chay", 15000, 0.8, False),
    ]))
    out.append(("SDW", "Bánh mì, sandwich & bánh bao", "office_food", "NCC02", "FRESH", 2, 1, [
        ("Sandwich trứng", 22000, 3, False), ("Sandwich cá ngừ", 25000, 2.5, False),
        ("Sandwich gà", 25000, 2, False), ("Sandwich jambon phô mai", 28000, 2, False),
        ("Sandwich mứt dâu", 15000, 1, False), ("Sandwich bơ đậu phộng", 15000, 0.8, False),
    ]))
    out.append(("BBA", "Bánh mì, sandwich & bánh bao", "office_food", "NCC02", "FRESH", 2, 1, [
        ("Bánh bao xá xíu", 15000, 4, False), ("Bánh bao trứng muối", 18000, 3, False),
        ("Bánh bao thịt trứng cút", 20000, 3, False), ("Bánh bao kim sa", 15000, 1.5, False),
        ("Bánh bao chay", 12000, 1, False), ("Bánh bao khoai môn", 12000, 0.8, False),
    ]))
    milk = []
    for size, price, rate in (("180ml", 8000, 8), ("450ml", 18000, 3), ("950ml", 35000, 2)):
        for typ, mult in (("có đường", 1.0), ("ít đường", 0.6), ("không đường", 0.7)):
            milk.append((f"Sữa tươi thanh trùng Đồng Cỏ {typ} {size}", price, rate * mult, False))
    out.append(("SUA", "Sữa tươi & sữa chua", "dairy", "NCC03", "SHORT", 7, 1, milk))
    out.append(("SCA", "Sữa tươi & sữa chua", "dairy", "NCC03", "SHORT", 21, 4, [
        ("Sữa chua ăn có đường", 7000, 6, False), ("Sữa chua ăn không đường", 7000, 4, False),
        ("Sữa chua nha đam", 8000, 3, False), ("Sữa chua dâu", 8000, 2.5, False),
        ("Sữa chua trái cây", 8000, 2, False), ("Sữa chua Hy Lạp ít đường", 15000, 1, False),
    ]))
    yog = []
    for flavor, rate in (("cam", 3), ("dâu", 2.5), ("việt quất", 1.5), ("nguyên vị", 2)):
        yog.append((f"Sữa chua uống vị {flavor} 80ml", 6000, rate, False))
        yog.append((f"Sữa chua uống vị {flavor} 180ml", 12000, rate * 0.5, False))
    out.append(("SCU", "Sữa tươi & sữa chua", "dairy", "NCC03", "SHORT", 28, 4, yog))
    out.append(("BNG", "Bánh ngọt", "bakery", "NCC04", "SHORT", 7, 1, [
        ("Bánh bông lan trứng muối", 25000, 2, False), ("Bánh bông lan cuộn dâu", 15000, 2.5, False),
        ("Bánh bông lan cuộn sô-cô-la", 15000, 2, False), ("Bánh su kem hộp", 22000, 1.5, False),
        ("Bánh mì hoa cúc", 45000, 1, False), ("Bánh mì sandwich lát", 22000, 3, False),
        ("Bánh mì ngọt nhân kem", 10000, 4, False), ("Bánh mì nho", 10000, 2, False),
        ("Bánh croissant bơ", 18000, 1.5, False), ("Bánh donut đường", 12000, 2, False),
        ("Bánh flan hộp 2 cái", 15000, 1.5, False), ("Bánh chuối nướng", 20000, 0.6, False),
    ]))
    out.append(("TRG", "Trứng", "eggs", "NCC10", "SHORT", 21, 1, [
        ("Trứng gà hộp 10 quả", 32000, 3, False), ("Trứng gà hộp 6 quả", 20000, 2, False),
        ("Trứng vịt hộp 10 quả", 38000, 1, False), ("Trứng cút hộp 30 quả", 25000, 0.8, False),
    ]))
    water = []
    for brand, mult in (("Suối Mát", 1.0), ("Trong Lành", 0.6), ("An Khê", 0.3)):
        water.append((f"Nước suối {brand} 500ml", 6000, 20 * mult, brand != "An Khê"))
        water.append((f"Nước suối {brand} 350ml", 5000, 6 * mult, False))
        water.append((f"Nước suối {brand} 1.5L", 13000, 4 * mult, False))
    out.append(("NSU", "Nước suối", "water", "NCC05", "LONG", 365, 24, water))
    soft = []
    for flavor, rate in (("cola", 12), ("cam", 5), ("chanh", 6), ("xá xị", 4), ("soda kem", 3),
                         ("cola không đường", 3)):
        soft.append((f"Nước ngọt có ga vị {flavor} lon 330ml", 11000, rate, flavor == "cola"))
        soft.append((f"Nước ngọt có ga vị {flavor} chai 390ml", 10000, rate * 0.6, False))
        soft.append((f"Nước ngọt có ga vị {flavor} chai 1.5L", 22000, rate * 0.25, False))
    out.append(("NGT", "Nước ngọt có ga", "soft_drink", "NCC05", "LONG", 270, 24, soft))
    tea = []
    for name, rate in (("Trà xanh không độ", 8), ("Trà chanh mật ong", 5), ("Trà ô long", 4),
                       ("Trà sữa đóng chai", 3), ("Trà đào", 3), ("Trà bí đao", 4), ("Hồng trà", 2),
                       ("Trà gạo rang", 1)):
        tea.append((f"{name} chai 455ml", 10000, rate, False))
        tea.append((f"{name} chai 1L", 18000, rate * 0.3, False))
    tea += [("Nước tăng lực Bò Vàng lon", 12000, 6, False), ("Nước tăng lực Sấm Sét chai", 11000, 4, False),
            ("Nước tăng lực vị dâu lon", 12000, 2, False), ("Nước tăng lực không đường lon", 13000, 1, False),
            ("Nước điện giải chai 500ml", 12000, 3, False), ("Nước điện giải vị chanh 500ml", 12000, 1.5, False)]
    out.append(("TRA", "Trà & nước tăng lực", "tea_energy", "NCC05", "LONG", 270, 24, tea))
    out.append(("CAF", "Cà phê đóng sẵn", "coffee", "NCC05", "LONG", 180, 24, [
        ("Cà phê sữa lon", 12000, 5, False), ("Cà phê đen lon", 12000, 3, False),
        ("Cà phê sữa chai", 14000, 3, False), ("Latte chai", 18000, 2, False),
        ("Cold brew chai", 25000, 0.8, False), ("Cà phê muối chai", 20000, 1.5, False),
        ("Bạc xỉu chai", 16000, 2, False), ("Cà phê hòa tan hộp 10 gói", 55000, 0.6, False),
    ]))
    beer = []
    for brand, rate, price in (("Sông Hàn", 6, 17000), ("Phố Cổ", 5, 16000), ("Mekong", 4, 15000),
                               ("Đồng Nai Gold", 3, 20000), ("Tây Nguyên", 2, 16000), ("Hải Đăng", 1.5, 18000)):
        beer.append((f"Bia {brand} lon 330ml", price, rate, False))
        beer.append((f"Bia {brand} lon 500ml", int(price * 1.4), rate * 0.4, False))
    out.append(("BIA", "Bia", "beer", "NCC06", "LONG", 180, 24, beer))
    noodle = []
    for flavor, rate in (("tôm chua cay", 5), ("bò hầm", 3), ("gà", 2), ("sườn heo", 2), ("kim chi", 1.5),
                         ("lẩu Thái", 2), ("hải sản", 1), ("chay rau nấm", 0.8), ("hoành thánh", 0.8),
                         ("cay Hàn Quốc", 1.5)):
        noodle.append((f"Mì gói vị {flavor}", 5000, rate, flavor == "tôm chua cay"))
        noodle.append((f"Mì ly vị {flavor}", 12000, rate * 0.8, flavor == "tôm chua cay"))
    out.append(("MIG", "Mì gói & mì ly", "noodle", "NCC07", "LONG", 180, 24, noodle))
    snack = []
    for flavor in ("khoai tây tự nhiên", "khoai tây phô mai", "bắp", "rong biển", "tôm", "khoai tây cay",
                   "bánh gạo", "đậu phộng"):
        snack.append((f"Snack {flavor} gói nhỏ", 6000, 2, False))
        snack.append((f"Snack {flavor} gói vừa", 12000, 1.5, False))
        snack.append((f"Snack {flavor} gói lớn", 25000, 0.6, False))
    out.append(("SNK", "Snack", "snack", "NCC07", "LONG", 150, 10, snack))
    out.append(("KEO", "Bánh quy, kẹo & đồ ăn vặt", "candy", "NCC07", "LONG", 270, 12, [
        ("Bánh quy bơ hộp", 35000, 0.8, False), ("Bánh quy sô-cô-la chip", 25000, 1, False),
        ("Bánh xốp kem", 12000, 1.5, False), ("Bánh que", 10000, 1.2, False),
        ("Bánh gạo nướng", 15000, 1, False), ("Bánh trứng cuộn", 20000, 0.7, False),
        ("Bánh bông lan kem sô-cô-la hộp 6", 32000, 0.8, False), ("Kẹo cao su bạc hà", 8000, 2, False),
        ("Kẹo cao su dâu", 8000, 1, False), ("Kẹo dẻo trái cây", 12000, 1.2, False),
        ("Kẹo mút", 3000, 1.5, False), ("Kẹo bạc hà hộp", 15000, 0.8, False),
        ("Sô-cô-la thanh sữa", 20000, 1, False), ("Sô-cô-la thanh đen", 22000, 0.5, False),
        ("Hạt điều rang muối", 45000, 0.4, False), ("Hạt hướng dương", 15000, 0.8, False),
        ("Đậu phộng da cá", 12000, 1, False), ("Rong biển sấy giòn", 15000, 0.8, False),
        ("Bò khô gói", 35000, 0.6, False), ("Mực xé tẩm gia vị", 40000, 0.5, False),
    ]))
    out.append(("DOK", "Đồ khô & gia vị", "dry_goods", "NCC07", "LONG", 365, 6, [
        ("Nước mắm chai 500ml", 35000, 0.6, False), ("Dầu ăn chai 1L", 52000, 0.5, False),
        ("Đường trắng 1kg", 28000, 0.4, False), ("Muối i-ốt 500g", 8000, 0.3, False),
        ("Bột ngọt 400g", 30000, 0.3, False), ("Hạt nêm 400g", 38000, 0.4, False),
        ("Tương ớt chai", 15000, 0.6, False), ("Nước tương chai", 18000, 0.5, False),
        ("Gạo thơm túi 5kg", 120000, 0.3, False), ("Sữa đặc lon", 25000, 0.8, False),
        ("Cá hộp sốt cà", 22000, 0.7, False), ("Thịt heo hộp", 32000, 0.4, False),
    ]))
    out.append(("KEM", "Kem", "ice_cream", "NCC08", "LONG", 180, 12, [
        ("Kem ốc quế vani", 15000, 3, False), ("Kem ốc quế sô-cô-la", 15000, 3, False),
        ("Kem ốc quế dâu", 15000, 1.5, False), ("Kem que đậu xanh", 8000, 2, False),
        ("Kem que sữa dừa", 8000, 2, False), ("Kem que sô-cô-la", 10000, 1.5, False),
        ("Kem hộp vani 450ml", 55000, 0.5, False), ("Kem hộp sô-cô-la 450ml", 55000, 0.4, False),
        ("Kem hộp khoai môn 450ml", 55000, 0.3, False), ("Kem cây trà xanh", 12000, 1, False),
        ("Kem mochi", 20000, 1, False), ("Kem sandwich", 15000, 0.8, False),
        ("Kem que dưa lưới", 12000, 1.2, False), ("Kem que sầu riêng", 15000, 0.5, False),
    ]))
    out.append(("HMP", "Hóa mỹ phẩm & tiện ích", "household", "NCC09", "LONG", 720, 6, [
        ("Khăn giấy rút", 15000, 1.5, False), ("Khăn giấy ướt", 25000, 1, False),
        ("Giấy vệ sinh 2 cuộn", 12000, 1.2, False), ("Kem đánh răng 100g", 30000, 0.5, False),
        ("Bàn chải đánh răng", 20000, 0.4, False), ("Dầu gội gói", 3000, 1.5, False),
        ("Dầu gội chai nhỏ", 35000, 0.3, False), ("Sữa tắm chai nhỏ", 40000, 0.3, False),
        ("Xà bông cục", 15000, 0.3, False), ("Nước rửa tay chai", 45000, 0.2, False),
        ("Dao cạo", 15000, 0.4, False), ("Bông tẩy trang", 25000, 0.3, False),
        ("Băng vệ sinh ngày", 25000, 0.6, False), ("Băng vệ sinh đêm", 30000, 0.4, False),
        ("Pin AA vỉ 2", 20000, 0.5, False), ("Pin AAA vỉ 2", 20000, 0.4, False),
        ("Bật lửa", 5000, 1, False), ("Khẩu trang hộp 10 cái", 20000, 0.6, False),
        ("Nước súc miệng chai nhỏ", 35000, 0.2, False), ("Lăn khử mùi", 55000, 0.2, False),
        ("Kem chống nắng tuýp nhỏ", 85000, 0.2, False), ("Bao cao su hộp 3", 30000, 0.5, False),
        ("Nước giặt túi nhỏ", 25000, 0.3, False), ("Nước rửa chén chai nhỏ", 20000, 0.4, False),
        ("Ô gấp", 75000, 0.3, False),
    ]))
    return out


def build_catalog(seed: int = 42) -> tuple[list[SupplierSpec], list[ProductSpec]]:
    rng = random.Random(seed)
    products: list[ProductSpec] = []
    counters: dict[str, int] = {}
    for prefix, category, group, sup, klass, shelf, pack, items in _items():
        for name, price, rate, traffic in items:
            counters[prefix] = counters.get(prefix, 0) + 1
            sku = f"{prefix}{counters[prefix]:03d}"
            cost = int(round(price * COST_RATIO[group] * rng.uniform(0.95, 1.05) / 100)) * 100
            k = GROUP_K[group] * rng.uniform(0.6, 1.4)
            if rate < 1:
                k = min(k, 1.5)
            elif rate < 2:
                k = min(k, 4)
            item_pack = pack
            if group in ("water", "soft_drink", "tea_energy", "coffee") and ("1.5L" in name or "1L" in name):
                item_pack = 12
            if group == "dairy" and name.startswith("Sữa tươi"):
                item_pack = 4 if name.endswith(" 180ml") else 1
            elif group == "dairy" and "uống" in name:
                item_pack = 4 if name.endswith(" 80ml") else 1
            products.append(ProductSpec(
                sku=sku, name=name, category=category, group=group, freshness_class=klass,
                shelf_life_days=shelf, unit_cost=cost, unit_price=price, pack_size=item_pack,
                base_rate=float(rate), dispersion_k=round(k, 2), is_traffic_driver=traffic,
                supplier_code=sup, max_stock_qty=CAPACITY.get(group),
                min_display_qty=MIN_DISPLAY.get(group, 3) if klass == "LONG" else 0,
            ))
    by_cat: dict[str, list[ProductSpec]] = {}
    for p in products:
        by_cat.setdefault(p.category, []).append(p)
    for p in products:
        peers = [q for q in by_cat[p.category] if q.sku != p.sku]
        peers.sort(key=lambda q: abs(q.unit_price - p.unit_price))
        p.substitutes = [q.sku for q in peers[:3]]
    return SUPPLIERS, products
