import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, openPdf, type Proposal } from "../api";
import { dateVi, money, num } from "../format";

type PO = { id: number; code: string; supplier: string; status: string; order_date: string; expected_date: string; total_value: number; proposal_id: number | null; has_pdf: boolean };
type PODetail = PO & { lines: { line_id: number; sku: string; name: string; qty: number; unit_cost: number; received_qty: number | null; shelf_life_days: number; default_expiry: string }[] };
type Supplier = { code: string; name: string };

const PO_STATUS: Record<string, string> = { SENT: "Chờ giao", RECEIVED: "Đã nhận", CANCELLED: "Đã huỷ" };

function Receive({ id, onDone }: { id: number; onDone: () => void }) {
  const q = useQuery({ queryKey: ["po", id], queryFn: () => api<PODetail>(`/purchase-orders/${id}`) });
  const [qty, setQty] = useState<Record<number, number>>({});
  const [exp, setExp] = useState<Record<number, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () =>
      api(`/purchase-orders/${id}/receive`, {
        method: "POST",
        body: { lines: q.data!.lines.map((l) => ({ line_id: l.line_id, received_qty: qty[l.line_id] ?? l.qty, expiry_date: exp[l.line_id] ?? l.default_expiry })) },
      }),
    onSuccess: onDone,
    onError: (e: Error) => setErr(e.message),
  });
  if (!q.data) return <p className="muted">Đang tải…</p>;
  const d = q.data;
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <h2>Nhận hàng {d.code} · {d.supplier}</h2>
      <p className="small secondary">
        Bắt buộc ghi <b>hạn sử dụng in trên bao bì</b> cho từng lô. Đây là dữ liệu máy POS không có; thiếu nó thì không quản lý FEFO và cảnh báo cận date được.
        Ô HSD đã điền sẵn theo hạn chuẩn của mặt hàng, hãy sửa nếu khác.
      </p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>SKU</th><th>Tên hàng</th><th className="num">Đặt</th><th className="num">Nhận thực tế</th><th>HSD trên bao bì</th></tr></thead>
          <tbody>
            {d.lines.map((l) => (
              <tr key={l.line_id}>
                <td>{l.sku}</td>
                <td>{l.name}</td>
                <td className="num">{num(l.qty)}</td>
                <td className="num">
                  <input className="qty" type="number" min={0} value={qty[l.line_id] ?? l.qty} onChange={(e) => setQty({ ...qty, [l.line_id]: Number(e.target.value) })} />
                </td>
                <td>
                  <input type="date" value={exp[l.line_id] ?? l.default_expiry} onChange={(e) => setExp({ ...exp, [l.line_id]: e.target.value })} aria-label={`HSD ${l.name}`} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {err && <div className="alert error" style={{ marginTop: 8 }}>{err}</div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="primary" disabled={m.isPending} onClick={() => m.mutate()}>Xác nhận nhận hàng</button>
        <button className="ghost" onClick={onDone}>Đóng</button>
      </div>
    </div>
  );
}

export default function Orders() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("SENT");
  const [receiving, setReceiving] = useState<number | null>(null);
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
          {Object.entries(PO_STATUS).slice(0, 2).map(([k, l]) => (
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
                  <td>{dateVi(po.expected_date)}</td>
                  <td className="num">{money(po.total_value)}</td>
                  <td><span className={`badge st-${po.status === "SENT" ? "PENDING" : "EXECUTED"}`}><span className="dot" />{PO_STATUS[po.status]}</span></td>
                  <td className="row" style={{ justifyContent: "flex-end" }}>
                    {po.has_pdf && <button className="sm" onClick={() => openPdf(po.id).catch((e) => alert(e.message))}>PDF</button>}
                    {po.status === "SENT" && <button className="sm" onClick={() => setReceiving(po.id)}>Nhận hàng</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {pos.data?.length === 0 && <p className="muted">Không có đơn nào.</p>}
        </div>
      </div>
      {receiving && <Receive id={receiving} onDone={() => { setReceiving(null); qc.invalidateQueries(); }} />}
    </>
  );
}
