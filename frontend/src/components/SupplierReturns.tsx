import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, getUser } from "../api";
import { dateVi, money, num } from "../format";

export type ReturnItem = { lot_id: number; sku: string; name: string; qty: number; unit_cost: number; expiry_date: string; picked_qty?: number };
export type SupplierReturn = {
  id: number; code: string; supplier: string; status: string; status_label: string; mode: string; mode_label: string;
  credit_pct: number; items: ReturnItem[]; est_credit: number; credit_value: number | null; requested_date: string;
  confirmed_date: string | null; picked_up_date: string | null; credited_date: string | null; note: string | null; days_open: number;
};

const BADGE: Record<string, string> = { REQUESTED: "PENDING", CONFIRMED: "APPROVED", PICKED_UP: "APPROVED", CREDITED: "EXECUTED", REFUSED: "REJECTED" };

// Phiếu trả NCC: tiền (hoặc hàng đổi) chỉ được ghi khi NCC thực lấy hàng. Các nút ở đây là thao tác của Store Manager.
function ReturnRow({ r }: { r: SupplierReturn }) {
  const qc = useQueryClient();
  const isManager = getUser()?.role === "manager";
  const [mode, setMode] = useState<"" | "pickup" | "refuse">("");
  const [picked, setPicked] = useState<Record<number, string>>({});
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const act = useMutation({
    mutationFn: (a: { path: string; body: unknown }) => api(`/supplier-returns/${r.id}/${a.path}`, { method: "POST", body: a.body }),
    onSuccess: () => { setMode(""); setErr(null); qc.invalidateQueries(); },
    onError: (e: Error) => setErr(e.message),
  });
  const open = r.status === "REQUESTED" || r.status === "CONFIRMED";
  return (
    <>
      <tr>
        <td>{r.code}</td>
        <td>{r.supplier}</td>
        <td>{r.mode_label}</td>
        <td className="small">{r.items.map((i) => `${i.name} ×${i.picked_qty ?? i.qty}`).join("; ")}</td>
        <td className="num">{r.mode === "CREDIT" ? money(r.credit_value ?? r.est_credit) : "—"}{r.credit_value == null && r.mode === "CREDIT" && <div className="muted small">dự kiến</div>}</td>
        <td>
          <span className={`badge st-${BADGE[r.status]}`}><span className="dot" />{r.status_label}</span>
          {open && r.days_open >= 5 && <span className="badge st-FAILED" style={{ marginLeft: 6 }}>{r.days_open} ngày chưa lấy</span>}
          <div className="muted small">gửi {dateVi(r.requested_date)}</div>
        </td>
        <td className="row" style={{ justifyContent: "flex-end" }}>
          {isManager && r.status === "REQUESTED" && <button className="sm" disabled={act.isPending} onClick={() => act.mutate({ path: "confirm", body: {} })}>NCC xác nhận</button>}
          {isManager && open && <button className="sm" onClick={() => setMode(mode === "pickup" ? "" : "pickup")}>NCC đã lấy hàng</button>}
          {isManager && open && <button className="sm danger" onClick={() => setMode(mode === "refuse" ? "" : "refuse")}>NCC từ chối</button>}
          {isManager && r.status === "PICKED_UP" && <button className="sm" disabled={act.isPending} onClick={() => act.mutate({ path: "credited", body: {} })}>Đã nhận tiền hoàn</button>}
        </td>
      </tr>
      {mode === "pickup" && (
        <tr>
          <td colSpan={7}>
            <div className="small secondary">Nhập số NCC thực nhận. Phần không nhận quay lại bán. Lúc này hệ thống mới ghi {r.mode === "CREDIT" ? "tiền hoàn" : "lô hàng đổi (giá vốn 0)"}.</div>
            {r.items.map((i) => (
              <div className="row small" key={i.lot_id} style={{ marginTop: 4 }}>
                <span style={{ flex: 1 }}>{i.name} · lô #{i.lot_id} · HSD {dateVi(i.expiry_date)} · đề nghị {num(i.qty)}</span>
                <input className="qty" type="number" min={0} max={i.qty} value={picked[i.lot_id] ?? String(i.qty)}
                  onChange={(e) => setPicked({ ...picked, [i.lot_id]: e.target.value })} aria-label={`Số NCC nhận lô ${i.lot_id}`} />
              </div>
            ))}
            <button className="sm primary" style={{ marginTop: 6 }} disabled={act.isPending}
              onClick={() => act.mutate({ path: "pickup", body: { lines: r.items.map((i) => ({ lot_id: i.lot_id, qty: Number(picked[i.lot_id] ?? i.qty) })) } })}>
              Xác nhận NCC đã lấy
            </button>
          </td>
        </tr>
      )}
      {mode === "refuse" && (
        <tr>
          <td colSpan={7}>
            <div className="row">
              <input style={{ flex: 1 }} placeholder="Lý do NCC từ chối (bắt buộc)" value={reason} onChange={(e) => setReason(e.target.value)} />
              <button className="sm danger" disabled={!reason.trim() || act.isPending} onClick={() => act.mutate({ path: "refuse", body: { reason } })}>
                Xác nhận: hàng quay lại bán
              </button>
            </div>
            <div className="small muted">Hệ thống sẽ xét lại phương án giảm giá cho các lô này.</div>
          </td>
        </tr>
      )}
      {err && <tr><td colSpan={7}><div className="alert error">{err}</div></td></tr>}
    </>
  );
}

export default function SupplierReturns() {
  const q = useQuery({ queryKey: ["supplier-returns"], queryFn: () => api<SupplierReturn[]>("/supplier-returns") });
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Phiếu trả nhà cung cấp</h2>
      <p className="small secondary">
        Duyệt đề xuất trả hàng chỉ tách hàng khỏi kệ và gửi email. Tiền hoàn hoặc hàng đổi được ghi khi NCC thực lấy hàng; trong lúc chờ, hàng vẫn nằm ở cửa hàng.
      </p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Phiếu</th><th>NCC</th><th>Hình thức</th><th>Hàng</th><th className="num">Hoàn</th><th>Trạng thái</th><th /></tr></thead>
          <tbody>{q.data?.map((r) => <ReturnRow key={r.id} r={r} />)}</tbody>
        </table>
        {q.data?.length === 0 && <p className="muted">Chưa có phiếu trả nào.</p>}
      </div>
    </div>
  );
}
