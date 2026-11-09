import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import ChartView from "../components/ChartView";
import { FastForward, Hypotheses, LearnedAdjustments } from "../components/StoreControls";
import { TYPE_LABEL, dateVi, money, num, pct } from "../format";

type Kpi = Record<string, number>;
type Dash = {
  today: string;
  inventory: { total_value: number; out_of_stock_skus: number; active_skus: number; value_expiring_within_3_days: number; value_already_expired_on_shelf: number; purchase_orders_awaiting_delivery: number };
  kpi_current: { start: string; end: string; kpi: Kpi };
  kpi_previous: { start: string; end: string; kpi: Kpi };
  expiring: { total_value_at_risk: number; lots: { lot_id: number; sku: string; name: string; qty: number; days_left: number; bucket: string; value_at_risk: number }[] };
  pending: { id: number; type: string; title: string; est_value: number | null; created_by: string }[];
  suppliers_due_today: { code: string; name: string }[];
  agent_acceptance: { decided: number; approval_rate: number | null; edited_rate: number | null; avg_qty_change_pct: number | null };
  daily: { period: string; revenue: number; gross_profit: number; qty: number; lost_qty: number }[];
};

function Tile({ label, value, cur, prev, lowerIsBetter = false, fmt }: { label: string; value: string; cur?: number; prev?: number; lowerIsBetter?: boolean; fmt?: (v: number) => string }) {
  let delta = null;
  if (cur != null && prev != null && prev !== 0) {
    const d = (cur - prev) / Math.abs(prev);
    const good = lowerIsBetter ? d < 0 : d > 0;
    delta = (
      <div className={`delta ${Math.abs(d) < 0.005 ? "" : good ? "good" : "bad"}`}>
        {d > 0 ? "▲" : d < 0 ? "▼" : "•"} {pct(Math.abs(d))} so với 30 ngày trước{fmt ? ` (${fmt(prev)})` : ""}
      </div>
    );
  }
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {delta}
    </div>
  );
}

export default function Dashboard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dash>("/dashboard") });
  const scan = useMutation({
    mutationFn: (kind: string) => api(`/proposals/generate`, { method: "POST", body: { kind } }),
    onSuccess: () => qc.invalidateQueries(),
  });
  if (q.isLoading) return <p className="muted">Đang tải…</p>;
  if (q.error) return <div className="alert error">{(q.error as Error).message}</div>;
  const d = q.data!;
  const c = d.kpi_current.kpi;
  const p = d.kpi_previous.kpi;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Tổng quan</h1>
          <div className="muted">
            Hôm nay {dateVi(d.today)} · KPI 30 ngày {dateVi(d.kpi_current.start)} – {dateVi(d.kpi_current.end)}
          </div>
        </div>
        <div className="row">
          <button onClick={() => scan.mutate("morning")} disabled={scan.isPending}>
            {scan.isPending ? "Đang quét…" : "Quét & tạo đề xuất ngay"}
          </button>
          <button onClick={() => scan.mutate("evening")} disabled={scan.isPending}>
            Quét giờ vàng
          </button>
        </div>
      </div>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <Tile label="Doanh thu 30 ngày" value={money(c.revenue)} cur={c.revenue} prev={p.revenue} />
        <Tile label="Lợi nhuận gộp (sau hủy)" value={money(c.gross_profit)} cur={c.gross_profit} prev={p.gross_profit} />
        <Tile label="Tỷ lệ hủy (giá vốn)" value={pct(c.waste_rate)} cur={c.waste_rate} prev={p.waste_rate} lowerIsBetter fmt={(v) => pct(v)} />
        <Tile label="Tỷ lệ hết hàng" value={pct(c.oos_rate)} cur={c.oos_rate} prev={p.oos_rate} lowerIsBetter fmt={(v) => pct(v)} />
        <Tile label="Giá trị tồn kho" value={money(d.inventory.total_value)} />
        <Tile label="Hàng sắp hết hạn (≤3 ngày)" value={money(d.inventory.value_expiring_within_3_days)} />
      </div>

      <div className="grid cols-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="row" style={{ marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>Việc cần duyệt hôm nay</h2>
            <span className="spacer" />
            <Link to="/approvals">Mở hộp duyệt →</Link>
          </div>
          {d.pending.length === 0 ? (
            <p className="muted">Không có đề xuất nào đang chờ. Bấm "Quét & tạo đề xuất ngay" hoặc hỏi Ops Chest.</p>
          ) : (
            <table>
              <tbody>
                {d.pending.slice(0, 8).map((x) => (
                  <tr key={x.id}>
                    <td style={{ width: 90 }}>
                      <span className="badge accent">{TYPE_LABEL[x.type]}</span>
                    </td>
                    <td>
                      <Link to="/approvals">{x.title}</Link>
                    </td>
                    <td className="num">{x.est_value != null ? money(x.est_value) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="small muted" style={{ marginTop: 8 }}>
            NCC đến lịch đặt hôm nay: {d.suppliers_due_today.map((s) => s.name).join(", ") || "không có"}. Đơn đang chờ giao:{" "}
            {d.inventory.purchase_orders_awaiting_delivery}.
          </p>
        </div>

        <div className="card">
          <div className="row" style={{ marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>Hàng có nguy cơ hủy (3 ngày)</h2>
            <span className="spacer" />
            <Link to="/expiring">Xem tất cả →</Link>
          </div>
          {d.expiring.lots.length === 0 ? (
            <p className="muted">Không có lô nào sắp hết hạn.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Hàng</th>
                  <th>Còn hạn</th>
                  <th className="num">SL</th>
                  <th className="num">Giá vốn dự kiến hủy</th>
                </tr>
              </thead>
              <tbody>
                {d.expiring.lots.map((l) => (
                  <tr key={l.lot_id}>
                    <td>{l.name}</td>
                    <td>{l.bucket}</td>
                    <td className="num">{num(l.qty)}</td>
                    <td className="num">{money(l.value_at_risk)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="grid cols-2">
        <ChartView
          spec={{
            metric: "sales", type: "line", title: "Doanh thu & lợi nhuận gộp theo ngày", period: `${dateVi(d.kpi_current.start)} – ${dateVi(d.kpi_current.end)}`,
            x_key: "period", unit: "VND", series: [{ key: "revenue", label: "Doanh thu" }, { key: "gross_profit", label: "Lợi nhuận gộp" }],
            data: d.daily, row_count: d.daily.length,
          }}
        />
        <div className="card">
          <h2>Mức độ Store Manager tin đề xuất</h2>
          {d.agent_acceptance.decided === 0 ? (
            <p className="muted">Chưa có đề xuất nào được quyết định. Chỉ số này đo tỷ lệ duyệt và mức SM phải sửa số lượng, tức độ tin cậy của Ops Chest.</p>
          ) : (
            <div className="grid cols-3">
              <div className="kpi"><div className="label">Đã quyết định</div><div className="value">{d.agent_acceptance.decided}</div></div>
              <div className="kpi"><div className="label">Tỷ lệ duyệt</div><div className="value">{pct(d.agent_acceptance.approval_rate, 0)}</div></div>
              <div className="kpi"><div className="label">Bị sửa khi duyệt</div><div className="value">{pct(d.agent_acceptance.edited_rate, 0)}</div>
                <div className="delta">sửa TB {pct(d.agent_acceptance.avg_qty_change_pct, 0)} số lượng</div></div>
            </div>
          )}
          <p className="small muted" style={{ marginTop: 12 }}>
            Mọi quyết định cuối cùng thuộc về Store Manager. Ops Chest chỉ tạo đề xuất; đặt hàng, đổi giá, ghi hủy chỉ diễn ra sau khi duyệt.
          </p>
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <Hypotheses />
        <LearnedAdjustments />
      </div>
      <FastForward />
    </>
  );
}
