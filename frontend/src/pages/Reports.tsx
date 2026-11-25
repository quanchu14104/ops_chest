import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type ChartSpec, type Proposal } from "../api";
import ChartView from "../components/ChartView";
import Segmented from "../components/ui/Segmented";
import { CardTitle, Chips, InfoTip } from "../components/ui/controls";
import PageHeader from "../components/ui/PageHeader";
import { Hypotheses, LearnedAdjustments } from "../components/StoreControls";
import { Skeleton } from "../components/ui/EmptyState";
import { abcLabel, dateVi, money, pct } from "../format";

type KpiCell = { label: string; value: string; hint: string };

type Cost = {
  start: string; end: string; kpi: Record<string, number>; shrink_value: number;
  top_waste_skus: { sku: string; name: string; waste_qty: number; waste_value: number }[];
  waste_by_reason: { reason: string; label: string; waste_qty: number; waste_value: number }[];
  supplier_scorecard: { supplier: string; orders: number; fill_rate: number | null; on_time_rate: number | null; short: number; short_dated: number; rejected: number }[];
};
type Cand = { sku: string; name: string; category: string; cell: string; margin_90d: number; waste_rate: number; reasons: string[] };

const METRICS: [string, string][] = [
  ["stock_flow", "Nhập/xuất (số lượng)"],
  ["stock_flow_value", "Nhập/xuất (giá vốn)"],
  ["sales", "Doanh thu & lợi nhuận"],
  ["sales_qty", "Bán & hụt do hết hàng"],
  ["waste_trend", "Hàng hủy theo thời gian"],
  ["waste_by_category", "Hàng hủy theo nhóm"],
  ["inventory_by_category", "Tồn kho theo nhóm"],
];

export default function Reports() {
  const qc = useQueryClient();
  const [metric, setMetric] = useState("stock_flow");
  const [group, setGroup] = useState("week");
  const [days, setDays] = useState(90);
  const [msg, setMsg] = useState<string | null>(null);
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<{ today: string }>("/meta") });
  // Ngay nghiep vu lay tu server (co the co dinh bang SIM_TODAY), khong dung dong ho trinh duyet
  const today = meta.data ? new Date(`${meta.data.today}T00:00:00Z`) : new Date();
  const end = new Date(today.getTime() - 864e5);
  const start = new Date(end.getTime() - (days - 1) * 864e5);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const chart = useQuery({
    enabled: !!meta.data,
    queryKey: ["chart", metric, group, days, meta.data?.today],
    queryFn: () => api<ChartSpec>(`/charts?metric=${metric}&group_by=${group}&start=${iso(start)}&end=${iso(end)}`),
  });
  const cost = useQuery({ enabled: !!meta.data, queryKey: ["cost", days, meta.data?.today], queryFn: () => api<Cost>(`/reports/cost?start=${iso(start)}&end=${iso(end)}`) });
  const acc = useQuery({
    queryKey: ["acceptance"],
    queryFn: () => api<{ decided: number; approval_rate: number | null; edited_rate: number | null; avg_qty_change_pct: number | null }>("/proposals/stats"),
  });
  const cands = useQuery({ queryKey: ["delist"], queryFn: () => api<Cand[]>(`/reports/delist`) });
  const delist = useMutation({
    mutationFn: (sku: string) => api<Proposal[]>("/proposals/create", { method: "POST", body: { type: "DELIST", sku } }),
    onSuccess: (r) => { setMsg(`Đã tạo đề xuất #${r[0].id}. Vào Hộp duyệt để quyết định.`); qc.invalidateQueries(); },
    onError: (e: Error) => setMsg(e.message),
  });
  const k = cost.data?.kpi;

  return (
    <>
      <PageHeader title="Phân tích" desc="Biểu đồ, chi phí, hàng hủy, điểm nhà cung cấp và ứng viên ngừng nhập."
        actions={<>
          <Chips label="Khoảng thời gian" value={String(days)} onChange={(v) => v && setDays(Number(v))}
            options={[30, 90, 180, 365].map((d) => ({ value: String(d), label: `${d} ngày` }))} />
          <Segmented label="Gom theo" value={group} onChange={setGroup}
            options={[{ value: "day", label: "Ngày" }, { value: "week", label: "Tuần" }, { value: "month", label: "Tháng" }]} />
        </>} />

      {!k && <div className="card mb-4"><Skeleton rows={3} height={18} /></div>}
      {k && (
        <div className="kpi-groups mb-4">
          {([
            ["Hiệu quả", [
              { label: "Lợi nhuận gộp", value: money(k.gross_profit), hint: "Doanh thu trừ giá vốn hàng bán, hàng hủy và hao hụt trong kỳ" },
              { label: "GMROI", value: k.gmroi == null ? "—" : k.gmroi.toLocaleString("vi-VN", { maximumFractionDigits: 2 }), hint: "Lãi gộp chia giá trị tồn kho bình quân: mỗi đồng tồn kho sinh ra bao nhiêu đồng lãi gộp. Hàng tươi quay vòng nhanh nên số này rất cao." },
              { label: "Lãi mất do hết hàng", value: money(k.lost_margin), hint: "Lãi gộp ước tính của phần nhu cầu không bán được vì kệ trống" },
              { label: "Tỷ lệ hết hàng", value: pct(k.oos_rate), hint: "Tỷ lệ ngày-mặt hàng có lúc hết hàng trên kệ" },
            ]],
            ["Hủy & hao hụt", [
              { label: "Giá vốn hàng hủy", value: money(k.waste_cost), hint: "Tổng giá vốn các lô đã ghi hủy trong kỳ" },
              { label: "Tỷ lệ hủy", value: pct(k.waste_rate), hint: "Giá vốn hàng hủy / giá vốn hàng nhập trong kỳ" },
              { label: "Hao hụt", value: money(cost.data?.shrink_value ?? 0), hint: "Chênh lệch âm phát hiện khi kiểm kê hoặc rút kệ" },
              { label: "Đã giảm giá", value: money(k.markdown_loss), hint: "Phần doanh thu bỏ ra để giảm giá hàng cận date" },
              { label: "NCC hoàn tiền", value: money(k.return_credit), hint: "Tiền nhà cung cấp hoàn khi lấy hàng trả" },
            ]],
            ["Tồn kho", [
              { label: "Số ngày tồn kho", value: `${k.inventory_days.toLocaleString("vi-VN", { maximumFractionDigits: 2 })} ngày`, hint: "Tồn kho bình quân chia giá vốn bán ra mỗi ngày: hàng nằm kho bao lâu mới bán hết" },
            ]],
          ] as [string, KpiCell[]][]).map(([title, cells]) => (
            <section key={title} className="kpi-group">
              <h2 className="section-title">{title}</h2>
              <div className="grid kpis">
                {cells.map((c) => (
                  <div className="card kpi" key={c.label}>
                    <div className="label has-hint" title={c.hint}>{c.label}</div>
                    <div className="value">{c.value}</div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <div className="card mb-4">
        <div className="row mb-3">
          <Segmented label="Biểu đồ" value={metric} onChange={setMetric} options={METRICS.map(([value, label]) => ({ value, label }))} />
        </div>
        {chart.data ? <ChartView spec={chart.data} height={300} /> : <Skeleton rows={6} />}
      </div>

      <div className="grid mb-4">
        <div className="card">
          <CardTitle title="Ứng viên ngừng nhập" info="Hàng bán chậm và không đều, hủy nhiều hoặc lỗ, không phải hàng kéo khách. Ngừng nhập là quyết định của Store Manager." />
          {msg && <div className="alert ok" style={{ marginBottom: 8 }}>{msg}</div>}
          {cands.data?.length === 0 && <p className="muted">Không có ứng viên.</p>}
          {cands.data?.map((c) => (
            <div key={c.sku} style={{ borderTop: "1px solid var(--grid)", padding: "8px 0" }}>
              <div className="row">
                <b title={`${c.sku} · ${c.category}`}>{c.name}</b> <span className="badge">{abcLabel(c.cell, true) ?? "Hàng mới"}</span>
                <InfoTip text={c.reasons.join(" · ")} />
                <span className="spacer" />
                <button className="sm danger" onClick={() => delist.mutate(c.sku)} disabled={delist.isPending}>Ngừng nhập</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {cost.data && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 title={`${dateVi(cost.data.start)} – ${dateVi(cost.data.end)}`}>Hủy nhiều nhất</h2>
          <table>
            <thead><tr><th>SKU</th><th>Tên hàng</th><th className="num">SL hủy</th><th className="num">Giá vốn hủy</th></tr></thead>
            <tbody>{cost.data.top_waste_skus.map((s) => <tr key={s.sku}><td>{s.sku}</td><td>{s.name}</td><td className="num">{s.waste_qty}</td><td className="num">{money(s.waste_value)}</td></tr>)}</tbody>
          </table>
          <p className="small muted">{(k as unknown as { note_inventory?: string })?.note_inventory}</p>
          <div className="mt-3"><CardTitle title="Hủy theo lý do" info="Hết hạn thường là đặt dư; vỡ, hỏng do bảo quản hay lỗi nhà cung cấp là vấn đề khác và cần cách xử lý khác." /></div>
          <table>
            <thead><tr><th>Lý do</th><th className="num">SL hủy</th><th className="num">Giá vốn hủy</th></tr></thead>
            <tbody>{cost.data.waste_by_reason.map((r) => <tr key={r.reason}><td>{r.label}</td><td className="num">{r.waste_qty}</td><td className="num">{money(r.waste_value)}</td></tr>)}</tbody>
          </table>
          <div className="mt-3"><CardTitle title="Điểm nhà cung cấp" info="Trên các đơn đến hạn giao trong kỳ: tỷ lệ giao đủ, giao đúng hẹn, số lần giao date ngắn và số đơn vị bị từ chối tại cửa." /></div>
          <table>
            <thead><tr><th>NCC</th><th className="num">Số đơn</th><th className="num">Giao đủ</th><th className="num">Đúng hẹn</th><th className="num">Thiếu (đv)</th><th className="num">Date ngắn</th><th className="num">Từ chối (đv)</th></tr></thead>
            <tbody>{cost.data.supplier_scorecard.map((s) => (
              <tr key={s.supplier}><td>{s.supplier}</td><td className="num">{s.orders}</td><td className="num">{pct(s.fill_rate)}</td><td className="num">{pct(s.on_time_rate)}</td>
                <td className="num">{s.short}</td><td className="num">{s.short_dated}</td><td className="num">{s.rejected}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {/* Từ trang Tổng quan cũ: những gì Ops Chest học được từ cách Store Manager quyết định */}
      <section className="kpi-group mt-3">
        <h2 className="section-title">Ops Chest học được gì</h2>
        <div className="grid cols-3-learn">
          <div className="card">
            <CardTitle title="Độ tin đề xuất" info="Tỷ lệ Store Manager duyệt và mức phải sửa số lượng khi duyệt: đo độ tin cậy của Ops Chest. Mọi quyết định cuối cùng thuộc về Store Manager." />
            {!acc.data ? <Skeleton rows={2} /> : acc.data.decided === 0 ? (
              <p className="muted small">Chưa có đề xuất nào được quyết định.</p>
            ) : (
              <div className="grid cols-3">
                <div className="kpi"><div className="label">Đã quyết định</div><div className="value">{acc.data.decided}</div></div>
                <div className="kpi"><div className="label">Tỷ lệ duyệt</div><div className="value">{pct(acc.data.approval_rate, 0)}</div></div>
                <div className="kpi"><div className="label">Bị sửa khi duyệt</div><div className="value">{pct(acc.data.edited_rate, 0)}</div>
                  <div className="delta">sửa TB {pct(acc.data.avg_qty_change_pct, 0)} số lượng</div></div>
              </div>
            )}
          </div>
          <Hypotheses />
          <LearnedAdjustments />
        </div>
      </section>
    </>
  );
}

