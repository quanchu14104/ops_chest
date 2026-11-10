import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, getUser, openPdf, type Proposal } from "../api";
import ExpiryPhoto from "../components/ExpiryPhoto";
import SupplierReturns from "../components/SupplierReturns";
import { dateVi, money, num } from "../format";

type PO = { id: number; code: string; supplier: string; status: string; order_date: string; expected_date: string; total_value: number; proposal_id: number | null; has_pdf: boolean; overdue_days: number };
type PODetail = PO & {
  reject_reasons: Record<string, string>;
  lines: {
    line_id: number; sku: string; name: string; qty: number; unit_cost: number; received_qty: number | null; shelf_life_days: number;
    default_expiry: string; min_remaining_days: number; over_tolerance: number; pack_size: number;
  }[];
};
type ReceiveResult = { code: string; lots: { sku: string; qty: number }[]; shortages: { sku: string; name: string; ordered: number; short: number }[]; warnings: string[] };
type Supplier = { code: string; name: string };

const PO_STATUS: Record<string, string> = { SENT: "Chờ giao", RECEIVED: "Đã nhận", CANCELLED: "Đã huỷ" };
const PO_BADGE: Record<string, string> = { SENT: "PENDING", RECEIVED: "EXECUTED", CANCELLED: "REJECTED" };

function CancelPO({ po, onDone }: { po: PO; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => api(`/purchase-orders/${po.id}/cancel`, { method: "POST", body: { reason } }),
    onSuccess: onDone,
    onError: (e: Error) => setErr(e.message),
  });
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <h2>Huỷ đơn {po.code} · {po.supplier}</h2>
      <p className="small secondary">Chỉ huỷ khi nhà cung cấp không giao nữa. Hệ thống không tự báo cho nhà cung cấp, anh/chị cần báo trực tiếp.</p>
      <input style={{ width: "100%" }} autoFocus placeholder="Lý do huỷ (bắt buộc)" value={reason} onChange={(e) => setReason(e.target.value)} />
      {err && <div className="alert error" style={{ marginTop: 8 }}>{err}</div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="danger" disabled={!reason.trim() || m.isPending} onClick={() => m.mutate()}>Xác nhận huỷ đơn</button>
        <button className="ghost" onClick={onDone}>Đóng</button>
      </div>
    </div>
  );
}

type LotIn = { qty: string; exp: string };
type LineIn = { lots: LotIn[]; rejected: string; reason: string; cost: string; acceptShort: boolean; acceptOver: boolean };

function Receive({ id, onDone }: { id: number; onDone: () => void }) {
  const q = useQuery({ queryKey: ["po", id], queryFn: () => api<PODetail>(`/purchase-orders/${id}`) });
  const [inp, setInp] = useState<Record<number, LineIn>>({});
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<ReceiveResult | null>(null);
  const isManager = getUser()?.role === "manager";
  const get = (l: PODetail["lines"][number]): LineIn =>
    inp[l.line_id] ?? { lots: [{ qty: String(l.qty), exp: "" }], rejected: "", reason: "", cost: "", acceptShort: false, acceptOver: false };
  const set = (lineId: number, v: LineIn) => setInp((cur) => ({ ...cur, [lineId]: v }));
  const m = useMutation({
    mutationFn: () =>
      api<ReceiveResult>(`/purchase-orders/${id}/receive`, {
        method: "POST",
        body: {
          lines: q.data!.lines.map((l) => {
            const v = get(l);
            return {
              line_id: l.line_id,
              lots: v.lots.map((x) => ({ qty: Number(x.qty || 0), expiry_date: x.exp || null })),
              rejected_qty: v.rejected ? Number(v.rejected) : null,
              reject_reason: v.rejected ? v.reason || null : null,
              actual_unit_cost: v.cost ? Number(v.cost) : null,
              accept_short_dated: v.acceptShort,
              accept_over: v.acceptOver,
            };
          }),
        },
      }),
    onSuccess: (r) => setRes(r),
    onError: (e: Error) => setErr(e.message),
  });
  if (!q.data) return <p className="muted">Đang tải…</p>;
  const d = q.data;
  if (res)
    return (
      <div className="card" style={{ marginTop: 12 }}>
        <h2>Đã nhận hàng {res.code}</h2>
        <p>Ghi {res.lots.length} lô vào kho.</p>
        {res.shortages.length > 0 && (
          <div className="alert warn">
            Giao thiếu: {res.shortages.map((s) => `${s.name} thiếu ${s.short}/${s.ordered}`).join("; ")}. Lần đặt sau hệ thống tự tính lại, không tạo đơn bù.
          </div>
        )}
        {res.warnings.map((w) => <div key={w} className="alert warn" style={{ marginTop: 6 }}>⚠ {w}</div>)}
        <div className="row" style={{ marginTop: 10 }}><button onClick={onDone}>Đóng</button></div>
      </div>
    );
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <h2>Nhận hàng {d.code} · {d.supplier}</h2>
      <p className="small secondary">
        Bắt buộc ghi <b>hạn sử dụng in trên bao bì</b> cho từng lô; một thùng trộn nhiều HSD thì bấm <b>+ HSD</b> để tách lô.
        Hàng móp, date ngắn, sai hàng thì <b>từ chối tại cửa</b>: sau khi ký nhận, rủi ro thuộc về cửa hàng.
        Lô còn ít hạn hơn chuẩn nhận hàng hoặc giao dư nhiều chỉ Store Manager được xác nhận nhận.
      </p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Hàng</th><th className="num">Đặt</th><th>Nhận: số lượng · HSD</th><th>Từ chối</th><th className="num">Giá hóa đơn</th></tr></thead>
          <tbody>
            {d.lines.map((l) => {
              const v = get(l);
              const setLot = (i: number, patch: Partial<LotIn>) => set(l.line_id, { ...v, lots: v.lots.map((y, j) => (j === i ? { ...y, ...patch } : y)) });
              return (
                <tr key={l.line_id}>
                  <td>{l.sku} · {l.name}<div className="muted small">Chuẩn: còn ≥ {l.min_remaining_days}/{l.shelf_life_days} ngày</div></td>
                  <td className="num">{num(l.qty)}</td>
                  <td>
                    {v.lots.map((x, i) => (
                      <div className="row" key={i} style={{ marginBottom: 4, flexWrap: "nowrap" }}>
                        <input className="qty" type="number" min={0} value={x.qty} aria-label={`Số lượng lô ${i + 1} ${l.name}`} onChange={(e) => setLot(i, { qty: e.target.value })} />
                        <input type="date" value={x.exp} aria-label={`HSD lô ${i + 1} ${l.name}`} onChange={(e) => setLot(i, { exp: e.target.value })} />
                        <ExpiryPhoto sku={l.sku} onRead={(iso) => setLot(i, { exp: iso })} />
                        {v.lots.length > 1 && (
                          <button className="sm ghost" aria-label="Bỏ lô" onClick={() => set(l.line_id, { ...v, lots: v.lots.filter((_, j) => j !== i) })}>✕</button>
                        )}
                      </div>
                    ))}
                    <button className="sm ghost" onClick={() => set(l.line_id, { ...v, lots: [...v.lots, { qty: "0", exp: "" }] })}>+ HSD</button>
                    {isManager && (
                      <div className="small">
                        <label><input type="checkbox" checked={v.acceptShort} onChange={(e) => set(l.line_id, { ...v, acceptShort: e.target.checked })} /> SM xác nhận nhận lô date ngắn</label>{" "}
                        <label><input type="checkbox" checked={v.acceptOver} onChange={(e) => set(l.line_id, { ...v, acceptOver: e.target.checked })} /> SM xác nhận nhận dư (quá {l.over_tolerance})</label>
                      </div>
                    )}
                  </td>
                  <td>
                    <input className="qty" type="number" min={0} placeholder="0" value={v.rejected} aria-label={`Số từ chối ${l.name}`}
                      onChange={(e) => set(l.line_id, { ...v, rejected: e.target.value })} />
                    {Number(v.rejected) > 0 && (
                      <select value={v.reason} onChange={(e) => set(l.line_id, { ...v, reason: e.target.value })} aria-label={`Lý do từ chối ${l.name}`}>
                        <option value="">Lý do…</option>
                        {Object.entries(d.reject_reasons).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
                      </select>
                    )}
                  </td>
                  <td className="num">
                    <input className="qty" type="number" min={0} placeholder={String(l.unit_cost)} value={v.cost} aria-label={`Giá hóa đơn ${l.name}`}
                      onChange={(e) => set(l.line_id, { ...v, cost: e.target.value })} style={{ width: 90 }} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {err && <div className="alert error" style={{ marginTop: 8 }}>{err}</div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="primary" disabled={m.isPending} onClick={() => { setErr(null); m.mutate(); }}>Xác nhận nhận hàng</button>
        <button className="ghost" onClick={onDone}>Đóng</button>
      </div>
    </div>
  );
}

export default function Orders() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("SENT");
  const [receiving, setReceiving] = useState<number | null>(null);
  const [cancelling, setCancelling] = useState<PO | null>(null);
  const isManager = getUser()?.role === "manager";
  const [sup, setSup] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const pos = useQuery({ queryKey: ["pos", status], queryFn: () => api<PO[]>(`/purchase-orders?status=${status}&limit=100`) });
  const sups = useQuery({ queryKey: ["suppliers"], queryFn: () => api<Supplier[]>("/suppliers") });
  const create = useMutation({
    mutationFn: () => api<Proposal[]>("/proposals/create", { method: "POST", body: { type: "PURCHASE_ORDER", supplier: sup } }),
    onSuccess: (r) => { setMsg({ ok: true, text: `Đã tạo đề xuất #${r[0].id}: ${r[0].title}.` }); qc.invalidateQueries(); },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Đặt &amp; nhận hàng</h1>
          <div className="muted">Đơn chỉ được gửi sau khi Store Manager duyệt đề xuất. Nhận hàng tại đây để ghi lô và HSD.</div>
        </div>
      </div>
      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Đề xuất đặt hàng ngoài lịch</h2>
        <div className="row">
          <select value={sup} onChange={(e) => setSup(e.target.value)} aria-label="Nhà cung cấp">
            <option value="">Chọn nhà cung cấp…</option>
            {sups.data?.map((s) => <option key={s.code} value={s.code}>{s.code} · {s.name}</option>)}
          </select>
          <button disabled={!sup || create.isPending} onClick={() => create.mutate()}>{create.isPending ? "Đang tính…" : "Tính & tạo đề xuất"}</button>
        </div>
        {msg && <div className={`alert ${msg.ok ? "ok" : "error"}`} style={{ marginTop: 10 }}>{msg.text} {msg.ok && <Link to="/approvals">Mở hộp duyệt →</Link>}</div>}
      </div>
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="seg">
          {Object.entries(PO_STATUS).map(([k, l]) => (
            <button key={k} className={status === k ? "on" : ""} onClick={() => setStatus(k)}>{l}</button>
          ))}
        </div>
      </div>
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Mã đơn</th><th>Nhà cung cấp</th><th>Ngày đặt</th><th>Giao dự kiến</th><th className="num">Giá trị</th><th>Trạng thái</th><th /></tr></thead>
            <tbody>
              {pos.data?.map((po) => (
                <tr key={po.id}>
                  <td>{po.code}{po.proposal_id && <span className="badge accent" style={{ marginLeft: 6 }}>từ đề xuất #{po.proposal_id}</span>}</td>
                  <td>{po.supplier}</td>
                  <td>{dateVi(po.order_date)}</td>
                  <td>{dateVi(po.expected_date)}{po.overdue_days > 0 && <span className="badge st-FAILED" style={{ marginLeft: 6 }}>trễ {po.overdue_days} ngày</span>}</td>
                  <td className="num">{money(po.total_value)}</td>
                  <td><span className={`badge st-${PO_BADGE[po.status]}`}><span className="dot" />{PO_STATUS[po.status]}</span></td>
                  <td className="row" style={{ justifyContent: "flex-end" }}>
                    {po.has_pdf && <button className="sm" onClick={() => openPdf(po.id).catch((e) => alert(e.message))}>PDF</button>}
                    {po.status === "SENT" && <button className="sm" onClick={() => { setCancelling(null); setReceiving(po.id); }}>Nhận hàng</button>}
                    {po.status === "SENT" && isManager && <button className="sm danger" onClick={() => { setReceiving(null); setCancelling(po); }}>Huỷ đơn</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {pos.data?.length === 0 && <p className="muted">Không có đơn nào.</p>}
        </div>
      </div>
      {cancelling && <CancelPO key={cancelling.id} po={cancelling} onDone={() => { setCancelling(null); qc.invalidateQueries(); }} />}
      {receiving && <Receive key={receiving} id={receiving} onDone={() => { setReceiving(null); qc.invalidateQueries(); }} />}
      <SupplierReturns />
    </>
  );
}
