"""Danh muc cua cua hang OC dung tu MOT diem ban FreshRetailNet-50K.

Nhu cau la that (FRN). Moi thu FRN KHONG co duoc tao theo quy tac co dinh tu ma so, va la GIA DINH:
ten hang (FRN chi co ma so), gia ban, gia von, HSD, quy cach, nha cung cap. Ten de trung tinh ("Mat hang 412 ·
nhom 3"), khong gan ten loai hang cu the vi FRN khong cho biet ma nhom nao la rau, thit hay hai san.
"""
from __future__ import annotations

import zlib

from app.sim.catalog import ALL_DAYS, ProductSpec, SupplierSpec
from app.sim.frn import FrnStore

# Ten NCC hu cau, trung tinh (khong noi loai hang). Mot NCC cho moi nhom quan ly (management_group) cua FRN.
SUPPLIER_NAMES = [
    "Công ty Thực phẩm Tươi An Phú", "Thực phẩm Tươi Bình Minh", "Tươi Sạch Cát Tường", "Phân phối Tươi Đông Á",
    "Thực phẩm Hòa Bình", "Tươi Ngon Phương Nam", "Nông sản Tân Phát", "Thực phẩm Tươi Gia Khang",
]
HISTORY_DAYS_FOR_RATE = 60


def _h(*parts) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


def category_name(group_id: int) -> str:
    return f"Nhóm tươi {group_id}"


def product_name(product_id: int, group_id: int, cat1: int) -> str:
    return f"Mặt hàng {product_id} · nhóm {group_id}.{cat1}"


def build_frn_catalog(store: FrnStore, k: float) -> tuple[list[SupplierSpec], list[ProductSpec]]:
    groups = sorted({s.management_group_id for s in store.series.values()})
    suppliers: list[SupplierSpec] = []
    sup_of: dict[int, str] = {}
    for n, g in enumerate(groups):
        code = f"NCC{n + 1:02d}"
        accepts = n % 3 == 0  # vai NCC nhan tra hang can han de tinh nang tra NCC co dip the hien
        s = SupplierSpec(code, SUPPLIER_NAMES[n % len(SUPPLIER_NAMES)], f"dathang{n + 1}@tuoi{n + 1}.test",
                         lead_time_days=1, order_weekdays=ALL_DAYS, min_order_value=300_000,
                         accepts_return=accepts, return_min_days=1 if accepts else 0,
                         return_credit_pct=0.5 if accepts else 0.0,
                         return_mode="EXCHANGE" if n == 3 else "CREDIT")
        s.phone = f"0908 {300 + n:03d} {500 + n * 11:03d}"
        suppliers.append(s)
        sup_of[g] = code

    rates = {pid: sum(s.demand[:HISTORY_DAYS_FOR_RATE]) / HISTORY_DAYS_FOR_RATE * k for pid, s in store.series.items()}
    drivers = set(sorted(rates, key=lambda p: -rates[p])[:5])
    by_cat2: dict[int, list[int]] = {}
    for pid, s in store.series.items():
        by_cat2.setdefault(s.second_category_id, []).append(pid)

    products: list[ProductSpec] = []
    for pid in sorted(store.series):
        s = store.series[pid]
        h = _h("frn", pid)
        price = 12_000 + (h % 69) * 1_000  # 12.000 - 80.000 d
        cost_ratio = 0.62 + (h // 97 % 14) / 100  # 62% - 75%
        shelf = 1 + _h("hsd", s.first_category_id) % 3  # 1-3 ngay theo nhom cap 1
        subs = sorted((x for x in by_cat2[s.second_category_id] if x != pid), key=lambda x: -rates[x])[:2]
        products.append(ProductSpec(
            sku=f"F{pid:04d}", name=product_name(pid, s.management_group_id, s.first_category_id),
            category=category_name(s.management_group_id), group="frn", freshness_class="FRESH",
            shelf_life_days=shelf, unit_cost=int(round(price * cost_ratio, -2)), unit_price=price, pack_size=1,
            base_rate=rates[pid], dispersion_k=1.0, is_traffic_driver=pid in drivers,
            supplier_code=sup_of[s.management_group_id], substitutes=[f"F{x:04d}" for x in subs], frn_id=pid,
        ))
    return suppliers, products


def frn_category_policy(category: str) -> dict:
    """Cau hinh nhom hang: khung gio ban LAY TU FRN (cac diem huan luyen, chi ngay con hang du gio); gio giam gia
    ngay sau khung ban dinh. Tran giam gia 50% van la cau hinh demo (doi chieu Nghi dinh 81/2018/ND-CP)."""
    from app.engines.disposition import DEFAULT_DAYPART_SHARES, peak_end_hour, share_after
    from app.sim.frn import dayparts

    gid = category.rsplit(" ", 1)[-1]
    shares = dayparts().get("engine", {}).get(gid)
    shares = tuple(shares) if shares else DEFAULT_DAYPART_SHARES
    hour = peak_end_hour(shares)
    return {"markdown_allowed": True, "max_markdown_pct": 0.5, "daypart_shares": list(shares), "markdown_hour": hour,
            "remaining_share": share_after(shares, hour)}
