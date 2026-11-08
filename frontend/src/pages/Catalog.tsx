import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { WEEKDAYS, money, num, pct } from "../format";

type Prod = { sku: string; name: string; category: string; status: string; freshness_class: string; shelf_life_days: number; unit_cost: number; unit_price: number; supplier: string; is_traffic_driver: boolean; abc_xyz: string | null; on_hand: number };
type Sup = { code: string; name: string; email: string; phone: string; lead_time_days: number; order_weekdays: number[]; min_order_value: number; agreement: { accepts_near_expiry_return: boolean; return_min_days_before_expiry: number; return_credit_pct: number; discount_pct: number; notes: string } | null };

const FRESH: Record<string, string> = { FRESH: "Tươi ≤3 ngày", SHORT: "Ngắn ≤30 ngày", LONG: "Dài" };

export default function Catalog() {
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<"products" | "suppliers">("products");
  const prods = useQuery({ queryKey: ["products"], queryFn: () => api<Prod[]>("/products?limit=500") });
  const sups = useQuery({ queryKey: ["suppliers"], queryFn: () => api<Sup[]>("/suppliers") });
  const ql = query.toLowerCase();
  const rows = (prods.data ?? []).filter((p) => !ql || p.name.toLowerCase().includes(ql) || p.sku.toLowerCase().includes(ql) || p.category.toLowerCase().includes(ql));
  return (
    <>
      <div className="page-head">
        <div><h1>Hàng hóa &amp; nhà cung cấp</h1><div className="muted">Danh mục, phân loại vòng đời, ABC-XYZ và điều khoản hợp đồng nguyên tắc với NCC.</div></div>
        <div className="seg">
          <button className={tab === "products" ? "on" : ""} onClick={() => setTab("products")}>Sản phẩm ({prods.data?.length ?? "…"})</button>
          <button className={tab === "suppliers" ? "on" : ""} onClick={() => setTab("suppliers")}>Nhà cung cấp</button>
        </div>
      </div>
      {tab === "products" ? (
        <div className="card">
          <input style={{ width: "100%", maxWidth: 360, marginBottom: 12 }} placeholder="Tìm theo tên, SKU, nhóm…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <div className="table-wrap">
            <table>
              <thead><tr><th>SKU</th><th>Tên hàng</th><th>Nhóm</th><th>Vòng đời</th><th>ABC-XYZ</th><th className="num">Giá vốn</th><th className="num">Giá bán</th><th className="num">Tồn</th><th>NCC</th></tr></thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.sku} style={{ opacity: p.status === "ACTIVE" ? 1 : 0.5 }}>
                    <td>{p.sku}</td>
                    <td>
                      {p.name}
                      {p.is_traffic_driver && <span className="badge accent" style={{ marginLeft: 6 }} title="Hàng kéo khách: không đề xuất ngừng nhập">kéo khách</span>}
                      {p.status !== "ACTIVE" && <span className="badge" style={{ marginLeft: 6 }}>ngừng nhập</span>}
                    </td>
                    <td className="small">{p.category}</td>
                    <td className="small">{FRESH[p.freshness_class]} · {p.shelf_life_days}n</td>
                    <td>{p.abc_xyz ?? "—"}</td>
                    <td className="num">{money(p.unit_cost)}</td>
                    <td className="num">{money(p.unit_price)}</td>
                    <td className="num">{num(p.on_hand)}</td>
                    <td className="small">{p.supplier}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="card">
          <p className="small secondary">
            Cửa hàng độc lập ký hợp đồng nguyên tắc với từng NCC. Ops Chest không soạn hợp đồng; các <b>điều khoản</b> dưới đây là dữ liệu để tính số lượng đặt (lead time, đơn tối thiểu) và xử lý hàng cận date (đổi trả).
          </p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Mã</th><th>Nhà cung cấp</th><th>Lịch đặt</th><th className="num">Giao sau</th><th className="num">Đơn tối thiểu</th><th>Đổi trả cận date</th><th>Liên hệ</th></tr></thead>
              <tbody>
                {sups.data?.map((s) => (
                  <tr key={s.code}>
                    <td>{s.code}</td>
                    <td>{s.name}</td>
                    <td>{s.order_weekdays.length === 7 ? "Hằng ngày" : s.order_weekdays.map((d) => WEEKDAYS[d]).join(", ")}</td>
                    <td className="num">{s.lead_time_days} ngày</td>
                    <td className="num">{money(s.min_order_value)}</td>
                    <td className="small">{s.agreement?.accepts_near_expiry_return ? `Có: còn ≥ ${s.agreement.return_min_days_before_expiry} ngày, hoàn ${pct(s.agreement.return_credit_pct, 0)}` : "Không"}</td>
                    <td className="small">{s.email}<br />{s.phone}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
