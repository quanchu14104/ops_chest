"""Seam ghi de danh muc luc seed (CATALOG_OVERRIDES_PATH) va truong received_at cua danh sach PO."""
import json

from app.sim.catalog import ALL_DAYS, ProductSpec, SupplierSpec
from app.sim.frn_catalog import apply_catalog_overrides


def _catalog():
    sups = [SupplierSpec("NCC01", "Công ty Thực phẩm Tươi An Phú", "dathang1@tuoi1.test", 1, ALL_DAYS, 300_000,
                         accepts_return=True, return_min_days=1, return_credit_pct=0.5),
            SupplierSpec("NCC02", "Thực phẩm Tươi Bình Minh", "dathang2@tuoi2.test", 1, ALL_DAYS, 300_000)]
    prods = [ProductSpec(sku=sku, name=f"Mặt hàng {i} · nhóm 6.4", category="Nhóm tươi 6", group="frn",
                         freshness_class="FRESH", shelf_life_days=2, unit_cost=cost, unit_price=price, pack_size=1,
                         base_rate=3.0, dispersion_k=1.0, is_traffic_driver=False, supplier_code="NCC01", frn_id=i)
             for i, (sku, cost, price) in enumerate([("F0004", 22_300, 32_000), ("F0005", 9_900, 14_000)], start=4)]
    return sups, prods


def test_overrides_rename_reprice_and_keep_cost_ratio(tmp_path):
    path = tmp_path / "ops_catalog_overrides.json"
    path.write_text(json.dumps({
        "format": "ops-catalog-overrides", "version": 1,
        "products": {"F0004": {"name": "MEATDELI Thịt Nạc vai heo (S)", "unit_price": 168_900}},
        "suppliers": {"NCC01": {"name": "Nhà cung cấp Thanh Lam Mart – Thịt (demo)", "email": "dathang@khotong-demo.test"}},
    }, ensure_ascii=False), encoding="utf-8")
    sups, prods = _catalog()
    old_ratio = prods[0].unit_cost / prods[0].unit_price

    apply_catalog_overrides(sups, prods, str(path))

    p = prods[0]
    assert p.name == "MEATDELI Thịt Nạc vai heo (S)"
    assert p.unit_price == 168_900
    assert abs(p.unit_cost / p.unit_price - old_ratio) < 1e-5
    assert p.category == "Nhóm tươi 6"  # frn_category_policy tach ma nhom tu chuoi nay
    assert (p.shelf_life_days, p.supplier_code, p.base_rate) == (2, "NCC01", 3.0)
    assert (prods[1].name, prods[1].unit_price, prods[1].unit_cost) == ("Mặt hàng 5 · nhóm 6.4", 14_000, 9_900)

    s = sups[0]
    assert (s.name, s.email) == ("Nhà cung cấp Thanh Lam Mart – Thịt (demo)", "dathang@khotong-demo.test")
    # Engine khong doi: lead time, lich giao, don toi thieu, thoa thuan tra hang giu nguyen
    assert (s.lead_time_days, s.order_weekdays, s.min_order_value) == (1, ALL_DAYS, 300_000)
    assert (s.accepts_return, s.return_min_days, s.return_credit_pct) == (True, 1, 0.5)
    assert (sups[1].name, sups[1].email) == ("Thực phẩm Tươi Bình Minh", "dathang2@tuoi2.test")


def test_overrides_off_by_default_is_noop():
    from app.config import Settings

    assert Settings(_env_file=None).catalog_overrides_path is None
    for path in (None, ""):
        sups, prods = _catalog()
        before = ([vars(s).copy() for s in sups], [vars(p).copy() for p in prods])
        apply_catalog_overrides(sups, prods, path)
        assert ([vars(s) for s in sups], [vars(p) for p in prods]) == before


def test_purchase_order_list_has_received_at(client, manager):
    pos = client.get("/api/purchase-orders?limit=300", headers=manager).json()
    assert pos and all("received_at" in po for po in pos)
    assert all(po["received_at"] for po in pos if po["status"] == "RECEIVED")
    assert all(po["received_at"] is None for po in pos if po["status"] == "SENT")
