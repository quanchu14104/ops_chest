import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, type ChartSpec, type Proposal } from "../api";
import ChartView from "../components/ChartView";
import FrnBacktest, { type FrnBt } from "../components/FrnBacktest";
import FrnModelReport from "../components/FrnModelReport";
import { dateVi, money, pct } from "../format";

type Cost = {
  start: string; end: string; kpi: Record<string, number>; shrink_value: number;
  top_waste_skus: { sku: string; name: string; waste_qty: number; waste_value: number }[];
  waste_by_reason: { reason: string; label: string; waste_qty: number; waste_value: number }[];
  supplier_scorecard: { supplier: string; orders: number; fill_rate: number | null; on_time_rate: number | null; short: number; short_dated: number; rejected: number }[];
};
type Cand = { sku: string; name: string; category: string; cell: string; margin_90d: number; waste_rate: number; reasons: string[] };
type BT = { start: string; days: number; results: Record<string, Record<string, number>>; delta: Record<string, number> };
type SensRow = {
  key: string; label: string; note: string; gain: number; gain_pct: number; waste_a: number; waste_b: number; oos_a: number; oos_b: number;
  oos_traffic_a?: number; oos_traffic_b?: number; oos_class_a_a?: number; oos_class_a_b?: number;
};
type Sens = { start: string; days: number; rows: SensRow[] };

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
  const abc = useQuery({ queryKey: ["chart-abc"], queryFn: () => api<ChartSpec>(`/charts?metric=abc_xyz`) });
  const cost = useQuery({ enabled: !!meta.data, queryKey: ["cost", days, meta.data?.today], queryFn: () => api<Cost>(`/reports/cost?start=${iso(start)}&end=${iso(end)}`) });
  const cands = useQuery({ queryKey: ["delist"], queryFn: () => api<Cand[]>(`/reports/delist`) });
  const bt = useMutation({ mutationFn: (d: number) => api<BT>(`/reports/backtest?days=${d}`) });
  const frnBt = useQuery({ queryKey: ["bt-frn"], queryFn: () => api<FrnBt>("/reports/backtest/frn"), retry: false });
  // Bang do nhay cu chi can khi chua co backtest FRN
  const sens = useQuery({ enabled: frnBt.isError, queryKey: ["bt-sensitivity"], queryFn: () => api<Sens>("/reports/backtest/sensitivity"), retry: false });
  const delist = useMutation({
    mutationFn: (sku: string) => api<Proposal[]>("/proposals/create", { method: "POST", body: { type: "DELIST", sku } }),
    onSuccess: (r) => { setMsg(`Đã tạo đề xuất #${r[0].id}. Vào Hộp duyệt để quyết định.`); qc.invalidateQueries(); },
    onError: (e: Error) => setMsg(e.message),
  });
  const k = cost.data?.kpi;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Phân tích</h1>
          <div className="muted">Biểu đồ, chi phí, ABC-XYZ, ứng viên ngừng nhập và mô phỏng hiệu quả.</div>
        </div>
        <div className="row">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Khoảng thời gian">
            {[30, 60, 90, 180, 365].map((d) => <option key={d} value={d}>{d} ngày gần nhất</option>)}
          </select>
          <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Gom theo">
            <option value="day">Theo ngày</option>
            <option value="week">Theo tuần</option>
            <option value="month">Theo tháng</option>
          </select>
        </div>
      </div>

      {k && (
        <div className="grid kpis" style={{ marginBottom: 16 }}>
          {[["Lợi nhuận gộp (sau hủy, hao hụt)", money(k.gross_profit)], ["GMROI (lãi gộp / tồn TB)", k.gmroi == null ? "—" : k.gmroi.toLocaleString("vi-VN")],
            ["Giá vốn hàng hủy", money(k.waste_cost)], ["Tỷ lệ hủy", pct(k.waste_rate)], ["Tỷ lệ hết hàng", pct(k.oos_rate)],
            ["Lãi mất do hết hàng", money(k.lost_margin)], ["Đã giảm giá", money(k.markdown_loss)], ["NCC hoàn tiền", money(k.return_credit)],
            ["Số ngày tồn kho", `${k.inventory_days.toLocaleString("vi-VN")} ngày`], ["Hao hụt (kiểm kê, rút kệ)", money(cost.data?.shrink_value ?? 0)]].map(([l, v]) => (
            <div className="card kpi" key={l}><div className="label">{l}</div><div className="value" style={{ fontSize: 20 }}>{v}</div></div>
          ))}
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ marginBottom: 8 }}>
          <div className="seg" role="tablist">
            {METRICS.map(([m, l]) => <button key={m} className={metric === m ? "on" : ""} onClick={() => setMetric(m)}>{l}</button>)}
          </div>
        </div>
        {chart.data ? <ChartView spec={chart.data} height={300} /> : <p className="muted">Đang tải…</p>}
      </div>

      <div className="grid cols-2" style={{ marginBottom: 16 }}>
        {abc.data && <ChartView spec={abc.data} />}
        <div className="card">
          <h2>Ứng viên ngừng nhập</h2>
          <p className="small secondary">Ô C-Y/C-Z, hủy nhiều hoặc lỗ, không phải hàng kéo khách. Ngừng nhập là quyết định của Store Manager.</p>
          {msg && <div className="alert ok" style={{ marginBottom: 8 }}>{msg}</div>}
          {cands.data?.length === 0 && <p className="muted">Không có ứng viên.</p>}
          {cands.data?.map((c) => (
            <div key={c.sku} style={{ borderTop: "1px solid var(--grid)", padding: "8px 0" }}>
              <div className="row">
                <b>{c.name}</b> <span className="muted small">{c.sku} · {c.category}</span> <span className="badge">{c.cell}</span>
                <span className="spacer" />
                <button className="sm" onClick={() => delist.mutate(c.sku)} disabled={delist.isPending}>Đề xuất ngừng nhập</button>
              </div>
              <ul className="small secondary" style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {c.reasons.map((r) => <li key={r}>{r}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </div>

      {cost.data && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Top 10 mặt hàng hủy nhiều nhất ({dateVi(cost.data.start)} – {dateVi(cost.data.end)})</h2>
          <table>
            <thead><tr><th>SKU</th><th>Tên hàng</th><th className="num">SL hủy</th><th className="num">Giá vốn hủy</th></tr></thead>
            <tbody>{cost.data.top_waste_skus.map((s) => <tr key={s.sku}><td>{s.sku}</td><td>{s.name}</td><td className="num">{s.waste_qty}</td><td className="num">{money(s.waste_value)}</td></tr>)}</tbody>
          </table>
          <p className="small muted">{(k as unknown as { note_inventory?: string })?.note_inventory}</p>
          <h2 style={{ marginTop: 16 }}>Hủy theo lý do</h2>
          <p className="small secondary">Hết hạn thường là đặt dư; vỡ, hỏng do bảo quản hay lỗi nhà cung cấp là vấn đề khác và cần cách xử lý khác.</p>
          <table>
            <thead><tr><th>Lý do</th><th className="num">SL hủy</th><th className="num">Giá vốn hủy</th></tr></thead>
            <tbody>{cost.data.waste_by_reason.map((r) => <tr key={r.reason}><td>{r.label}</td><td className="num">{r.waste_qty}</td><td className="num">{money(r.waste_value)}</td></tr>)}</tbody>
          </table>
          <h2 style={{ marginTop: 16 }}>Điểm nhà cung cấp</h2>
          <p className="small secondary">Trên các đơn đến hạn giao trong kỳ: tỷ lệ giao đủ, giao đúng hẹn, số lần giao date ngắn và số đơn vị bị từ chối tại cửa.</p>
          <table>
            <thead><tr><th>NCC</th><th className="num">Số đơn</th><th className="num">Giao đủ</th><th className="num">Đúng hẹn</th><th className="num">Thiếu (đv)</th><th className="num">Date ngắn</th><th className="num">Từ chối (đv)</th></tr></thead>
            <tbody>{cost.data.supplier_scorecard.map((s) => (
              <tr key={s.supplier}><td>{s.supplier}</td><td className="num">{s.orders}</td><td className="num">{pct(s.fill_rate)}</td><td className="num">{pct(s.on_time_rate)}</td>
                <td className="num">{s.short}</td><td className="num">{s.short_dated}</td><td className="num">{s.rejected}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}

      <FrnModelReport />

      {frnBt.data ? (
        <div className="card"><FrnBacktest d={frnBt.data} /></div>
      ) : frnBt.isPending ? (
        <div className="card"><p className="muted">Đang tải kết quả mô phỏng…</p></div>
      ) : (
      <div className="card">
        <h2>Mô phỏng A/B (dữ liệu giả lập cũ)</h2>
        {!(frnBt.error instanceof ApiError && frnBt.error.status === 404) && (
          <div className="alert error" style={{ marginBottom: 8 }}>Không tải được backtest trên dữ liệu FRN: {(frnBt.error as Error).message}</div>
        )}
        <p className="small secondary">
          Chạy lại cùng cửa hàng với <b>cùng nhu cầu khách</b> (tất định) bằng 2 chính sách đặt hàng. A: mức tồn theo trung bình 4 tuần, cuối ngày giảm 30% hàng hết hạn hôm nay.
          B: dự báo + newsvendor/order-up-to có sàn mức phục vụ (kéo khách 95%, nhóm A 90%) + trần HSD và sức chứa + giảm giá giờ vàng theo khung bán của nhóm hàng/trả NCC (coi như SM duyệt hết). Trong mô phỏng, khách chỉ phản ứng với giảm giá bằng một nửa mức engine giả định. Mất khoảng 10-30 giây.
        </p>
        <div className="row">
          {[30, 60, 90].map((d) => <button key={d} disabled={bt.isPending} onClick={() => bt.mutate(d)}>Chạy {d} ngày</button>)}
          {bt.isPending && <span className="muted">Đang mô phỏng…</span>}
        </div>
        {bt.error && <div className="alert error">{(bt.error as Error).message}</div>}
        {bt.data && <Backtest d={bt.data} />}
        {sens.data && <Sensitivity d={sens.data} />}
      </div>
      )}
    </>
  );
}

function Sensitivity({ d }: { d: Sens }) {
  const signed = (v: number) => `${v >= 0 ? "+" : ""}${pct(v)}`;
  const core = d.rows.filter((r) => r.key === "reference" || r.key.startsWith("seed_")).map((r) => r.gain_pct);
  const oosWorse = d.rows.every((r) => r.oos_b > r.oos_a);
  const ref = d.rows.find((r) => r.key === "reference");
  return (
    <div className="table-wrap" style={{ marginTop: 16 }}>
      <h2>Kết quả phụ thuộc vào giả định đến đâu</h2>
      <p className="small secondary">
        Tính sẵn từ {dateVi(d.start)}, {d.days} ngày. Mỗi dòng chỉ đổi một điều so với dòng tham chiếu. Lợi nhuận gộp của B so với A ở kịch bản tham chiếu và các chuỗi nhu cầu khác: <b>{signed(Math.min(...core))} đến {signed(Math.max(...core))}</b>.
      </p>
      <table>
        <thead><tr><th>Kịch bản</th><th className="num">Lợi nhuận B so với A</th><th className="num">Tỷ lệ hủy A / B</th><th className="num">Hết hàng A / B</th><th className="num">Hàng kéo khách A / B</th><th className="num">Nhóm A A / B</th></tr></thead>
        <tbody>{d.rows.map((r) => (
          <tr key={r.key}>
            <td><b>{r.label}</b><div className="small muted">{r.note}</div></td>
            <td className="num">{signed(r.gain_pct)}</td>
            <td className="num">{pct(r.waste_a)} / {pct(r.waste_b)}</td>
            <td className="num">{pct(r.oos_a)} / {pct(r.oos_b)}</td>
            <td className="num">{r.oos_traffic_a == null ? "—" : `${pct(r.oos_traffic_a)} / ${pct(r.oos_traffic_b)}`}</td>
            <td className="num">{r.oos_class_a_a == null ? "—" : `${pct(r.oos_class_a_a)} / ${pct(r.oos_class_a_b)}`}</td>
          </tr>
        ))}</tbody>
      </table>
      {oosWorse && <div className="alert" style={{ marginTop: 10 }}>Đánh đổi: tỷ lệ hết hàng của B cao hơn A ở mọi kịch bản. Lợi nhuận tăng chủ yếu nhờ hủy ít hơn, không phải nhờ bán được nhiều hơn.</div>}
      {!oosWorse && ref && ref.oos_b <= ref.oos_a && (
        <div className="alert" style={{ marginTop: 10 }}>
          Ở kịch bản tham chiếu, B không hết hàng nhiều hơn A ({pct(ref.oos_b)} so với {pct(ref.oos_a)}) nhờ sàn mức phục vụ. Cái giá là phần lợi nhuận tăng thêm nhỏ hơn cách đặt cũ (dòng "B không có sàn mức phục vụ").
        </div>
      )}
    </div>
  );
}

function Backtest({ d }: { d: BT }) {
  const names = Object.keys(d.results);
  const rows: [string, string, (v: number) => string][] = [
    ["revenue", "Doanh thu", money], ["gross_profit", "Lợi nhuận gộp (sau hủy)", money], ["waste_cost", "Giá vốn hàng hủy", money],
    ["waste_rate", "Tỷ lệ hủy", (v) => pct(v)], ["oos_rate", "Tỷ lệ hết hàng", (v) => pct(v)], ["lost_margin", "Lãi mất do hết hàng", money],
    ["markdown_loss", "Giảm giá đã chi", money], ["return_credit", "NCC hoàn tiền", money], ["avg_inventory_value", "Tồn kho TB", money],
  ];
  return (
    <div className="table-wrap" style={{ marginTop: 12 }}>
      <p className="small muted">Từ {dateVi(d.start)}, {d.days} ngày.</p>
      <table>
        <thead><tr><th>Chỉ số</th>{names.map((n) => <th key={n} className="num">{n}</th>)}</tr></thead>
        <tbody>{rows.map(([k, l, f]) => <tr key={k}><td>{l}</td>{names.map((n) => <td key={n} className="num">{f(d.results[n][k])}</td>)}</tr>)}</tbody>
      </table>
      <div className="alert ok" style={{ marginTop: 10 }}>
        B so với A: lợi nhuận gộp <b>{d.delta.gross_profit_gain >= 0 ? "+" : ""}{money(d.delta.gross_profit_gain)}</b>, giảm hàng hủy <b>{money(d.delta.waste_cost_saved)}</b>,
        tồn kho TB {d.delta.inventory_value_reduction >= 0 ? "giảm" : "tăng"} {money(Math.abs(d.delta.inventory_value_reduction))}.
      </div>
    </div>
  );
}
