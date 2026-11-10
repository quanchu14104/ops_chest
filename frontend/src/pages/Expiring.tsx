import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type ChartSpec, type Proposal, type PullLine } from "../api";
import ChartView from "../components/ChartView";
import PullListForm from "../components/PullListForm";
import { WASTE_REASON_LABEL, dateVi, money, num } from "../format";

type Opt = { action: string; label: string; delta_vs_keep: number; feasible: boolean; note: string };
type LotRow = {
  lot_id: number; sku: string; name: string; category: string; qty: number; expiry_date: string; sell_by: string; days_left: number;
  bucket: string; status: string; expected_sold: number; expected_waste: number; value_at_risk: number; supplier: string;
  markdown_pct: number; options: Opt[];
};
type Resp = { as_of: string; lots: LotRow[]; total_value_at_risk: number; summary: { bucket: string; lots: number; value_at_risk: number }[] };

export default function Expiring() {
  const [days, setDays] = useState(7);
  const [onlyRisk, setOnlyRisk] = useState(true);
  const [sel, setSel] = useState<Record<number, boolean>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["expiring", days], queryFn: () => api<Resp>(`/inventory/expiring?days=${days}`) });
  const chart = useQuery({ queryKey: ["chart-expiry"], queryFn: () => api<ChartSpec>(`/charts?metric=expiry_risk`) });
  const create = useMutation({
    mutationFn: (type: string) =>
      api<Proposal[]>("/proposals/create", { method: "POST", body: { type, lot_ids: type === "DISPOSE" ? null : Object.keys(sel).filter((k) => sel[Number(k)]).map(Number) } }),
    onSuccess: (r) => {
      setMsg({ ok: true, text: `Đã tạo ${r.length} đề xuất (#${r.map((p) => p.id).join(", #")}). Chờ Store Manager duyệt trong Hộp duyệt.` });
      setSel({});
      qc.invalidateQueries();
    },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  const pull = useQuery({ queryKey: ["pull-list"], queryFn: () => api<{ closing_hour: number; lots: PullLine[] }>("/shelf/pull-list") });
  const [woQty, setWoQty] = useState<Record<number, string>>({});
  const [woReason, setWoReason] = useState("DAMAGED");
  const [woNote, setWoNote] = useState("");
  const writeOff = useMutation({
    mutationFn: () =>
      api<Proposal>("/write-offs", {
        method: "POST",
        body: { note: woNote || null, lines: selectedIds.map((id) => ({ lot_id: Number(id), qty: Number(woQty[Number(id)] || 0), reason: woReason })) },
      }),
    onSuccess: (p) => {
      setMsg({ ok: true, text: `Đã tạo đề xuất báo hủy #${p.id}. Tồn kho chỉ trừ khi Store Manager duyệt.` });
      setSel({});
      setWoQty({});
      setWoNote("");
      qc.invalidateQueries();
    },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  const rows = (q.data?.lots ?? []).filter((l) => !onlyRisk || l.status !== "OK");
  const selectedIds = Object.keys(sel).filter((k) => sel[Number(k)]);
  const hasExpired = rows.some((r) => r.status === "EXPIRED");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Hàng cận date</h1>
          <div className="muted">
            Dự kiến hủy tính bằng mô phỏng bán FEFO theo dự báo nhu cầu. Phương án xếp theo tiền thu hồi kỳ vọng.
          </div>
        </div>
        <div className="row">
          <label className="small secondary">
            Trong{" "}
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {[1, 3, 7, 14, 30, 60].map((d) => <option key={d} value={d}>{d} ngày</option>)}
            </select>
          </label>
          <label className="small secondary row" style={{ gap: 4 }}>
            <input type="checkbox" checked={onlyRisk} onChange={(e) => setOnlyRisk(e.target.checked)} /> Chỉ lô có nguy cơ hủy
          </label>
        </div>
      </div>
      <div className="grid cols-2" style={{ marginBottom: 16 }}>
        {chart.data && <ChartView spec={chart.data} height={200} />}
        <div className="card">
          <h2>Tạo đề xuất xử lý</h2>
          <p className="secondary small">
            Chọn lô trong bảng rồi tạo đề xuất. Đề xuất vào Hộp duyệt; giá chỉ đổi, phiếu trả chỉ gửi khi Store Manager duyệt.
          </p>
          <div className="row">
            <button disabled={!selectedIds.length || create.isPending} onClick={() => create.mutate("MARKDOWN")}>Đề xuất giảm giá ({selectedIds.length})</button>
            <button disabled={!selectedIds.length || create.isPending} onClick={() => create.mutate("RETURN")}>Đề xuất trả NCC ({selectedIds.length})</button>
            <button disabled={!hasExpired || create.isPending} onClick={() => create.mutate("DISPOSE")}>Đề xuất ghi hủy lô quá hạn</button>
          </div>
          {selectedIds.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <p className="small secondary">Báo hủy hàng vỡ, hỏng, lỗi (không phải hết hạn) cho các lô đã chọn:</p>
              {selectedIds.map((id) => {
                const l = rows.find((r) => r.lot_id === Number(id));
                return (
                  <div className="row small" key={id} style={{ marginBottom: 4 }}>
                    <span style={{ flex: 1 }}>{l ? `${l.name} · lô #${id}` : `Lô #${id}`}</span>
                    <input className="qty" type="number" min={1} max={l?.qty} placeholder="SL" value={woQty[Number(id)] ?? ""}
                      onChange={(e) => setWoQty({ ...woQty, [Number(id)]: e.target.value })} aria-label={`Số lượng hủy lô ${id}`} />
                  </div>
                );
              })}
              <div className="row">
                <select value={woReason} onChange={(e) => setWoReason(e.target.value)} aria-label="Lý do hủy">
                  {Object.entries(WASTE_REASON_LABEL).filter(([k]) => k !== "EXPIRED").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <input style={{ flex: 1 }} placeholder="Ghi chú (tuỳ chọn)" value={woNote} onChange={(e) => setWoNote(e.target.value)} />
                <button disabled={writeOff.isPending || selectedIds.some((id) => !woQty[Number(id)])} onClick={() => writeOff.mutate()}>Báo hủy</button>
              </div>
            </div>
          )}
          {msg && <div className={`alert ${msg.ok ? "ok" : "error"}`} style={{ marginTop: 10 }}>{msg.text} {msg.ok && <Link to="/approvals">Mở hộp duyệt →</Link>}</div>}
          <p className="small muted" style={{ marginTop: 10 }}>
            Tổng giá vốn dự kiến hủy: <b>{money(q.data?.total_value_at_risk)}</b>
          </p>
        </div>
      </div>
      <div style={{ marginBottom: 16 }}>
        <PullListForm lines={pull.data?.lots ?? []} title={`Rút kệ cuối ngày (sau ${pull.data?.closing_hour ?? 22}h)`}
          note="Bắt buộc: gỡ hết hàng của các lô đã qua ngày bán cuối và ghi số thực gỡ. Không cần chờ duyệt; Store Manager chỉ duyệt bút toán ghi hủy." />
      </div>
      <div className="card">
        {q.isLoading ? <p className="muted">Đang tính…</p> : rows.length === 0 ? <p className="muted">Không có lô nào có nguy cơ hủy trong {days} ngày tới. 🎉</p> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th />
                  <th>Hàng</th>
                  <th>HSD</th>
                  <th>Còn</th>
                  <th className="num">Tồn lô</th>
                  <th className="num">Dự kiến bán</th>
                  <th className="num">Dự kiến hủy</th>
                  <th className="num">Giá vốn rủi ro</th>
                  <th>Phương án tốt nhất</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((l) => {
                  const best = l.options[0];
                  return (
                    <tr key={l.lot_id}>
                      <td>
                        <input type="checkbox" checked={!!sel[l.lot_id]} disabled={l.status === "EXPIRED"} aria-label={`Chọn lô ${l.lot_id}`}
                          onChange={(e) => setSel({ ...sel, [l.lot_id]: e.target.checked })} />
                      </td>
                      <td>
                        {l.name} <span className="muted small">{l.sku} · lô #{l.lot_id}</span>
                        {l.markdown_pct > 0 && <span className="badge" style={{ marginLeft: 6 }}>đang giảm {Math.round(l.markdown_pct * 100)}%</span>}
                      </td>
                      <td>{dateVi(l.expiry_date)}{l.sell_by !== l.expiry_date && <div className="muted small">bán đến {dateVi(l.sell_by)}</div>}</td>
                      <td>{l.bucket}</td>
                      <td className="num">{num(l.qty)}</td>
                      <td className="num">{num(l.expected_sold, 1)}</td>
                      <td className="num">{num(l.expected_waste, 1)}</td>
                      <td className="num">{money(l.value_at_risk)}</td>
                      <td>
                        {l.status === "EXPIRED" ? <span className="badge st-FAILED"><span className="dot" />Quá ngày bán cuối: cần rút kệ</span>
                          : best ? <span title={best.note}>{best.label} <span className="muted small">(+{money(best.delta_vs_keep)})</span></span> : <span className="muted">Giữ nguyên</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
