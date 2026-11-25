import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import EmptyState, { Skeleton } from "../components/ui/EmptyState";
import PageHeader from "../components/ui/PageHeader";
import Segmented from "../components/ui/Segmented";
import { CardTitle, Chips, Switch } from "../components/ui/controls";
import { ABC_LABEL, WEEKDAYS, abcLabel, money, num, pct } from "../format";

type Prod = { sku: string; name: string; category: string; status: string; freshness_class: string; shelf_life_days: number; unit_cost: number; unit_price: number; supplier: string; is_traffic_driver: boolean; abc_xyz: string | null; on_hand: number; is_new?: boolean };
type Sup = { code: string; name: string; email: string; phone: string; lead_time_days: number; order_weekdays: number[]; min_order_value: number; agreement: { accepts_near_expiry_return: boolean; return_min_days_before_expiry: number; return_credit_pct: number; discount_pct: number; notes: string } | null };

const FRESH: Record<string, string> = { FRESH: "Tươi ≤3 ngày", SHORT: "Ngắn ≤30 ngày", LONG: "Dài" };

type Tab = "products" | "suppliers";

export default function Catalog() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("products");
  const [abc, setAbc] = useState("");
  const [supplier, setSupplier] = useState("");
  // ?filter=oos (từ bản tin "N mặt hàng đang hết hàng") bật sẵn lọc hàng hết
  const oos = params.get("filter") === "oos";
  const setOos = (on: boolean) => setParams(on ? { filter: "oos" } : {}, { replace: true });
  const prods = useQuery({ queryKey: ["products"], queryFn: () => api<Prod[]>("/products?limit=500") });
  const sups = useQuery({ queryKey: ["suppliers"], queryFn: () => api<Sup[]>("/suppliers") });
  const supplierNames = useMemo(() => [...new Set((prods.data ?? []).map((p) => p.supplier))].sort(), [prods.data]);
  const ql = query.trim().toLowerCase();
  const rows = (prods.data ?? []).filter((p) =>
    (!ql || p.name.toLowerCase().includes(ql) || p.sku.toLowerCase().includes(ql) || p.category.toLowerCase().includes(ql))
    && (!abc || (abc === "NEW" ? !!p.is_new : (p.abc_xyz ?? "").startsWith(abc)))
    && (!supplier || p.supplier === supplier)
    && (!oos || (p.status === "ACTIVE" && p.on_hand <= 0)));
  const filtered = !!(ql || abc || supplier || oos);
  return (
    <>
      <PageHeader title="Hàng hóa & nhà cung cấp" desc="Danh mục, vòng đời, mức bán và điều khoản hợp đồng nguyên tắc với NCC."
        actions={<Segmented<Tab> label="Danh mục" value={tab} onChange={setTab} options={[
          { value: "products", label: "Sản phẩm", count: prods.data?.length },
          { value: "suppliers", label: "Nhà cung cấp", count: sups.data?.length },
        ]} />} />
      {tab === "products" ? (
        <div className="card">
          <div className="row filters mb-3">
            <input type="search" className="grow" style={{ maxWidth: 320 }} placeholder="Tìm theo tên, SKU, nhóm…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Tìm hàng hóa" />
            <Chips label="Lọc theo mức bán" value={abc} onChange={setAbc} allowNone
              options={[...Object.entries(ABC_LABEL).map(([value, label]) => ({ value, label })), { value: "NEW", label: "Hàng mới" }]} />
            <select value={supplier} onChange={(e) => setSupplier(e.target.value)} aria-label="Lọc theo nhà cung cấp" style={{ maxWidth: 260 }}>
              <option value="">Mọi nhà cung cấp</option>
              {supplierNames.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            <Switch checked={oos} onChange={setOos} label="Đang hết hàng" />
            <span className="spacer" />
            {prods.data && <span className="small muted">{filtered ? `${rows.length} / ${prods.data.length} mặt hàng` : `${prods.data.length} mặt hàng`}</span>}
          </div>
          {prods.isLoading && <Skeleton rows={8} />}
          {prods.data && rows.length === 0 && <EmptyState title="Không có mặt hàng nào khớp bộ lọc" />}
          <div className="table-wrap sticky-head">
            <table>
              <thead><tr><th>SKU</th><th>Tên hàng</th><th>Nhóm</th><th>Vòng đời</th><th>Mức bán</th><th className="num">Giá vốn</th><th className="num">Giá bán</th><th className="num">Tồn</th><th>NCC</th></tr></thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.sku} className={p.status === "ACTIVE" ? undefined : "row-excluded"}>
                    <td>{p.sku}</td>
                    <td>
                      {p.name}
                      <span className="badges">
                        {p.is_traffic_driver && <span className="badge accent" title="Hàng kéo khách: không đề xuất ngừng nhập">kéo khách</span>}
                        {p.status !== "ACTIVE" && <span className="badge">ngừng nhập</span>}
                        {p.status === "ACTIVE" && p.on_hand <= 0 && <span className="badge bad">hết hàng</span>}
                      </span>
                    </td>
                    <td className="small">{p.category}</td>
                    <td className="small">{FRESH[p.freshness_class]} · {p.shelf_life_days}n</td>
                    <td>{p.is_new ? <span className="badge accent" title="Bán chưa đủ 8 tuần: chưa xếp mức bán, không xét ngừng nhập">hàng mới</span>
                      : <span className={`badge ${p.abc_xyz?.[0] === "A" ? "accent" : ""}`} title={abcLabel(p.abc_xyz, true) ?? undefined}>{abcLabel(p.abc_xyz) ?? "—"}</span>}</td>
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
          <CardTitle title="Điều khoản NCC" info="Cửa hàng độc lập ký hợp đồng nguyên tắc với từng NCC. Ops Chest không soạn hợp đồng; các điều khoản dưới đây là dữ liệu để tính số lượng đặt (lead time, đơn tối thiểu) và xử lý hàng cận date (đổi trả)." />
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
