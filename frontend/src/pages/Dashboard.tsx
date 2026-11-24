import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, getUser } from "../api";
import ChartView from "../components/ChartView";
import { FastForward, Hypotheses, LearnedAdjustments } from "../components/StoreControls";
import { Skeleton } from "../components/ui/EmptyState";
import PageHeader from "../components/ui/PageHeader";
import { CardTitle, Icon } from "../components/ui/controls";
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

function Tile({ label, value, cur, prev, lowerIsBetter = false, fmt, hint, note }: {
  label: string; value: string; cur?: number; prev?: number; lowerIsBetter?: boolean; fmt?: (v: number) => string; hint?: string; note?: string;
}) {
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
      <div className={`label ${hint ? "has-hint" : ""}`} title={hint}>{label}</div>
      <div className="value">{value}</div>
      {delta}
      {note && <div className="delta">{note}</div>}
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
  const isManager = getUser()?.role === "manager";
  if (q.isLoading) return <><PageHeader title="Tổng quan" /><div className="grid kpis">{[0, 1, 2, 3].map((i) => <div key={i} className="card"><Skeleton rows={2} height={18} /></div>)}</div></>;
  if (q.error) return <div className="alert error">{(q.error as Error).message}</div>;
  const d = q.data!;
  const c = d.kpi_current.kpi;
  const p = d.kpi_previous.kpi;
  // Dữ liệu demo chỉ có hàng tươi: tồn kho và "sắp hết hạn" bằng nhau thì gộp một ô cho khỏi gây hiểu lầm (L-07)
  const allFresh = d.inventory.total_value > 0 && Math.abs(d.inventory.total_value - d.inventory.value_expiring_within_3_days) < 1;
  const due = d.suppliers_due_today;
  return (
    <>
      <PageHeader title="Tổng quan"
        desc={<>Hôm nay {dateVi(d.today)} · KPI 30 ngày {dateVi(d.kpi_current.start)} – {dateVi(d.kpi_current.end)}, so với 30 ngày trước đó</>}
        actions={isManager && (
          <>
            <button onClick={() => scan.mutate("morning")} disabled={scan.isPending} title="Quét đặt hàng, cận date, ghi hủy như lúc 06:30">
              {scan.isPending ? "Đang quét…" : "Quét & tạo đề xuất ngay"}
            </button>
            <button onClick={() => scan.mutate("evening")} disabled={scan.isPending} title="Quét giảm giá cuối ngày như lúc 17:00">
              Quét giảm giá cuối ngày
            </button>
          </>
        )}
      />

      <div className="grid kpis mb-4">
        <Tile label="Doanh thu 30 ngày" value={money(c.revenue)} cur={c.revenue} prev={p.revenue} />
        <Tile label="Lợi nhuận gộp (sau hủy, hao hụt)" value={money(c.gross_profit)} cur={c.gross_profit} prev={p.gross_profit} />
        <Tile label="Tỷ lệ hủy (giá vốn)" hint="Giá vốn hàng hủy / giá vốn hàng nhập trong kỳ" value={pct(c.waste_rate)} cur={c.waste_rate} prev={p.waste_rate} lowerIsBetter fmt={(v) => pct(v)} />
        <Tile label="Tỷ lệ hết hàng" hint="Tỷ lệ ngày-mặt hàng có lúc hết hàng trên kệ" value={pct(c.oos_rate)} cur={c.oos_rate} prev={p.oos_rate} lowerIsBetter fmt={(v) => pct(v)} />
        {allFresh ? (
          <Tile label="Giá trị tồn kho" value={money(d.inventory.total_value)} note="Toàn bộ tồn là hàng tươi hạn ≤3 ngày" />
        ) : (
          <>
            <Tile label="Giá trị tồn kho" value={money(d.inventory.total_value)} />
            <Tile label="Hàng sắp hết hạn (≤3 ngày)" value={money(d.inventory.value_expiring_within_3_days)} />
          </>
        )}
      </div>

      <div className="grid cols-2 mb-4">
        <div className="card">
          <CardTitle title={<>Chờ duyệt <span className="count-pill">{d.pending.length}</span></>}>
            <Link to="/approvals" className="btn sm">Mở <Icon name="chevron" /></Link>
          </CardTitle>
          {d.pending.length === 0 ? (
            <p className="muted small">Không có đề xuất nào.</p>
          ) : (
            <table>
              <tbody>
                {d.pending.slice(0, 8).map((x) => (
                  <tr key={x.id}>
                    <td style={{ width: 90 }}>
                      <span className="badge accent">{TYPE_LABEL[x.type]}</span>
                    </td>
                    <td>
                      <Link to={`/approvals?type=${x.type}&open=${x.id}`}>{x.title}</Link>
                    </td>
                    <td className="num">{x.est_value != null ? money(x.est_value) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="facts mt-2">
            <span title={due.map((x) => x.name).join(", ")}>NCC đến lịch <b>{due.length}</b></span>
            <Link to="/orders">Đơn chờ giao <b>{d.inventory.purchase_orders_awaiting_delivery}</b></Link>
          </div>
        </div>

        <div className="card">
          <CardTitle title="Nguy cơ hủy · 3 ngày">
            <Link to="/expiring" className="btn sm">Mở <Icon name="chevron" /></Link>
          </CardTitle>
          {d.expiring.lots.length === 0 ? (
            <p className="muted small">Không có lô nào.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Hàng</th>
                  <th>Hạn</th>
                  <th className="num">SL</th>
                  <th className="num">Rủi ro</th>
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
          <CardTitle title="Độ tin đề xuất" info="Tỷ lệ Store Manager duyệt và mức phải sửa số lượng khi duyệt: đo độ tin cậy của Ops Chest. Mọi quyết định cuối cùng thuộc về Store Manager." />
          {d.agent_acceptance.decided === 0 ? (
            <p className="muted small">Chưa có đề xuất nào được quyết định.</p>
          ) : (
            <div className="grid cols-3">
              <div className="kpi"><div className="label">Đã quyết định</div><div className="value">{d.agent_acceptance.decided}</div></div>
              <div className="kpi"><div className="label">Tỷ lệ duyệt</div><div className="value">{pct(d.agent_acceptance.approval_rate, 0)}</div></div>
              <div className="kpi"><div className="label">Bị sửa khi duyệt</div><div className="value">{pct(d.agent_acceptance.edited_rate, 0)}</div>
                <div className="delta">sửa TB {pct(d.agent_acceptance.avg_qty_change_pct, 0)} số lượng</div></div>
            </div>
          )}
        </div>
      </div>

      <div className="grid cols-2 mt-3">
        <Hypotheses />
        <LearnedAdjustments />
      </div>
      <FastForward />
    </>
  );
}
