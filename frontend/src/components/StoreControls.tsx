import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, getUser, type Proposal } from "../api";
import { dateVi, money, num, pct } from "../format";

type Hypothesis = {
  id: number; scope: string; factor: number; start_date: string; end_date: string; reason: string; status: string;
  baseline_total: number; actual_total: number | null; ratio: number | null; verdict_label: string | null;
};
type Learning = {
  patterns: { category: string; edits: number; proposals: number; median_ratio: number; factor: number }[];
  active: { id: number; category: string; factor: number; reason: string }[];
};
type Advance = {
  from: string; to: string; proposals_expired_unanswered: number; pulled_awaiting_writeoff_value: number;
  totals: { revenue: number; sold: number; lost: number; received_pos: number };
  new_proposals: { id: number; title: string; created: boolean }[];
  hypotheses_evaluated: Hypothesis[];
};

export function Hypotheses() {
  const qc = useQueryClient();
  const isManager = getUser()?.role === "manager";
  const q = useQuery({ queryKey: ["hypotheses"], queryFn: () => api<Hypothesis[]>("/hypotheses") });
  const cancel = useMutation({
    mutationFn: (id: number) => api(`/hypotheses/${id}/cancel`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
  });
  const rows = (q.data ?? []).filter((h) => h.status !== "CANCELLED").slice(0, 6);
  return (
    <div className="card">
      <h2>Giả thuyết nhu cầu</h2>
      <p className="small secondary">Nói trong chat, ví dụ: "Thứ Bảy này có trận bóng, bia bán gấp rưỡi". Dự báo chỉ đổi sau khi anh/chị duyệt, và được chấm đúng/sai khi sự kiện qua đi.</p>
      {rows.length === 0 ? <p className="muted">Chưa có giả thuyết nào.</p> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Phạm vi</th><th className="num">Hệ số</th><th>Thời gian</th><th>Kết quả</th><th /></tr></thead>
            <tbody>
              {rows.map((h) => (
                <tr key={h.id}>
                  <td>{h.scope}<div className="small muted">{h.reason}</div></td>
                  <td className="num">×{num(h.factor, 2)}</td>
                  <td>{dateVi(h.start_date)} – {dateVi(h.end_date)}</td>
                  <td>
                    {h.status === "ACTIVE" ? <span className="badge accent">Đang áp dụng</span> : <span className="badge">{h.verdict_label}</span>}
                    {h.ratio != null && <div className="small muted">thực tế ×{num(h.ratio, 2)} so với dự báo nền</div>}
                  </td>
                  <td>{isManager && h.status === "ACTIVE" && <button className="sm" disabled={cancel.isPending} onClick={() => cancel.mutate(h.id)}>Huỷ</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function LearnedAdjustments() {
  const qc = useQueryClient();
  const isManager = getUser()?.role === "manager";
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const q = useQuery({ queryKey: ["learning"], queryFn: () => api<Learning>("/learning/order-edits") });
  const propose = useMutation({
    mutationFn: (category: string) => api<Proposal>("/learning/propose", { method: "POST", body: { category } }),
    onSuccess: (p) => { setMsg({ ok: true, text: `Đã tạo đề xuất #${p.id}, chờ duyệt.` }); qc.invalidateQueries(); },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  const off = useMutation({
    mutationFn: (id: number) => api(`/learning/adjustments/${id}/deactivate`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
  });
  const d = q.data;
  return (
    <div className="card">
      <h2>Học từ cách anh/chị sửa đơn</h2>
      <p className="small secondary">Chỉ gợi ý khi có ít nhất 5 lần sửa trên 3 đơn, cùng chiều và lệch từ 15% trở lên.</p>
      {d && d.patterns.length === 0 && d.active.length === 0 && <p className="muted">Chưa thấy thói quen sửa nào đủ rõ.</p>}
      {d?.patterns.map((p) => (
        <div className="row" key={p.category} style={{ borderTop: "1px solid var(--grid)", padding: "8px 0" }}>
          <div><b>{p.category}</b><div className="small muted">{p.edits} lần sửa trên {p.proposals} đơn, thường chốt bằng {pct(p.median_ratio, 0)} đề xuất</div></div>
          <span className="spacer" />
          <button className="sm" disabled={propose.isPending} onClick={() => propose.mutate(p.category)}>Đề xuất ×{num(p.factor, 2)}</button>
        </div>
      ))}
      {d?.active.map((a) => (
        <div className="row" key={a.id} style={{ borderTop: "1px solid var(--grid)", padding: "8px 0" }}>
          <div><b>{a.category}</b> <span className="badge accent">đang áp dụng ×{num(a.factor, 2)}</span></div>
          <span className="spacer" />
          {isManager && <button className="sm" disabled={off.isPending} onClick={() => off.mutate(a.id)}>Tắt</button>}
        </div>
      ))}
      {msg && <div className={`alert ${msg.ok ? "ok" : "error"}`} style={{ marginTop: 8 }}>{msg.text} {msg.ok && <Link to="/approvals">Mở hộp duyệt →</Link>}</div>}
    </div>
  );
}

export function FastForward() {
  const qc = useQueryClient();
  const [realize, setRealize] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: (days: number) => api<Advance>("/sim/advance", { method: "POST", body: { days, realize_hypotheses: realize } }),
    onSuccess: () => { setErr(null); qc.invalidateQueries(); },
    onError: (e: Error) => setErr(e.message),
  });
  const samples = useMutation({
    mutationFn: () => api<{ created: number; message?: string; category?: string }>("/sim/demo-edit-history", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
    onError: (e: Error) => setErr(e.message),
  });
  if (getUser()?.role !== "manager") return null;
  const r = run.data;
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Tua nhanh (chỉ cho demo)</h2>
      <p className="small secondary">
        Giả lập hàng về và khách mua trong những ngày tới. Không tự duyệt, đặt hàng hay ghi hủy: đề xuất không ai duyệt sẽ hết hiệu lực và thấy được hậu quả trên kệ.
      </p>
      <div className="row">
        {[1, 3, 7].map((d) => <button key={d} disabled={run.isPending} onClick={() => run.mutate(d)}>Tua {d} ngày</button>)}
        <label className="small secondary"><input type="checkbox" checked={realize} onChange={(e) => setRealize(e.target.checked)} /> Giả thuyết đang áp dụng xảy ra đúng</label>
        <span className="spacer" />
        <button className="ghost" disabled={samples.isPending} onClick={() => samples.mutate()}>Nạp lịch sử sửa mẫu</button>
        {run.isPending && <span className="muted">Đang giả lập…</span>}
      </div>
      {err && <div className="alert error" style={{ marginTop: 8 }}>{err}</div>}
      {samples.data && <div className="small muted" style={{ marginTop: 6 }}>{samples.data.message ?? `Đã thêm ${samples.data.created} đơn mẫu cho nhóm ${samples.data.category}.`}</div>}
      {r && (
        <div className="alert ok" style={{ marginTop: 10 }}>
          Từ {dateVi(r.from)} đến {dateVi(r.to)}: doanh thu {money(r.totals.revenue)}, bán {num(r.totals.sold)} đơn vị, hụt {num(r.totals.lost)} đơn vị do hết hàng, nhận {r.totals.received_pos} đơn.{" "}
          {r.proposals_expired_unanswered > 0 && `${r.proposals_expired_unanswered} đề xuất hết hiệu lực vì không ai duyệt. `}
          {r.pulled_awaiting_writeoff_value > 0 && `Hàng đã rút kệ chờ ghi hủy: ${money(r.pulled_awaiting_writeoff_value)}. `}
          {r.new_proposals.filter((p) => p.created).length} đề xuất mới chờ duyệt.
          {r.hypotheses_evaluated.map((h) => <div key={h.id}>Giả thuyết "{h.reason}": <b>{h.verdict_label}</b> (thực tế ×{num(h.ratio, 2)} so với dự báo nền, dự đoán ×{num(h.factor, 2)}).</div>)}
        </div>
      )}
    </div>
  );
}
