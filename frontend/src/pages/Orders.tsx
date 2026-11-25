import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { openInbox } from "../components/InboxPanel";
import { api, getUser, openPdf, type Proposal } from "../api";
import ExpiryPhoto from "../components/ExpiryPhoto";
import SupplierReturns from "../components/SupplierReturns";
import DateField from "../components/ui/DateField";
import EmptyState, { Skeleton } from "../components/ui/EmptyState";
import PageHeader from "../components/ui/PageHeader";
import Segmented from "../components/ui/Segmented";
import { CardTitle, Chips, Icon, Stepper, Switch } from "../components/ui/controls";
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

export type { PO };
const PO_STATUS: Record<string, string> = { SENT: "Chờ giao", RECEIVED: "Đã nhận", CANCELLED: "Đã huỷ" };
const PO_BADGE: Record<string, string> = { SENT: "PENDING", RECEIVED: "EXECUTED", CANCELLED: "REJECTED" };

// Lý do huỷ hay gặp: bấm chip là xong
const CANCEL_REASONS = ["NCC báo không giao được", "Quá hạn giao, không chờ nữa", "Đặt nhầm"];

export function CancelPO({ po, onDone }: { po: Pick<PO, "id" | "code" | "supplier">; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [pick, setPick] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => api(`/purchase-orders/${po.id}/cancel`, { method: "POST", body: { reason } }),
    onSuccess: onDone,
    onError: (e: Error) => setErr(e.message),
  });
  return (
    <div className="card mt-3">
      <CardTitle title={`Huỷ đơn ${po.code} · ${po.supplier}`}
        info="Chỉ huỷ khi nhà cung cấp không giao nữa. Hệ thống không tự báo cho nhà cung cấp, anh/chị cần báo trực tiếp." />
      <Chips label="Lý do huỷ" value={pick} onChange={(v) => { setPick(v); setReason(v === "__other__" ? "" : v); }}
        options={[...CANCEL_REASONS.map((r) => ({ value: r, label: r, tone: "bad" as const })), { value: "__other__", label: "Khác…", tone: "bad" as const }]} />
      {pick === "__other__" && (
        <input className="mt-2" style={{ width: "100%" }} autoFocus placeholder="Lý do huỷ" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Lý do huỷ" />
      )}
      {err && <div className="alert error mt-2">{err}</div>}
      <div className="row mt-3">
        <button className="danger-solid" disabled={!reason.trim() || m.isPending} onClick={() => m.mutate()}><Icon name="x" /> Xác nhận huỷ đơn</button>
        <button className="ghost" onClick={onDone}>Đóng</button>
      </div>
    </div>
  );
}

type LotIn = { qty: string; exp: string };
type LineIn = { lots: LotIn[]; rejected: string; reason: string; cost: string; acceptShort: boolean; acceptOver: boolean };

export function Receive({ id, onDone }: { id: number; onDone: () => void }) {
  const q = useQuery({ queryKey: ["po", id], queryFn: () => api<PODetail>(`/purchase-orders/${id}`) });
  const [inp, setInp] = useState<Record<number, LineIn>>({});
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<ReceiveResult | null>(null);
  const isManager = getUser()?.role === "manager";
  // Form nhận hàng mở dưới bảng đơn: cuộn tới để người nhận thấy ngay
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (q.data) ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [q.data]);
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
  if (!q.data) return <div className="card mt-3"><Skeleton rows={5} /></div>;
  const d = q.data;
  if (res)
    return (
      <div className="card mt-3" ref={ref}>
        <h2>Đã nhận hàng {res.code}</h2>
        <p>Ghi {res.lots.length} lô vào kho.</p>
        {res.shortages.length > 0 && (
          <div className="alert warn">
            Giao thiếu: {res.shortages.map((s) => `${s.name} thiếu ${s.short}/${s.ordered}`).join("; ")}. Lần đặt sau hệ thống tự tính lại, không tạo đơn bù.
          </div>
        )}
        {res.warnings.map((w) => <div key={w} className="alert warn mt-1">⚠ {w}</div>)}
        <div className="row mt-3"><button onClick={onDone}>Đóng</button></div>
      </div>
    );
  return (
    <div className="card mt-3" ref={ref}>
      <CardTitle title={`Nhận hàng ${d.code} · ${d.supplier}`}
        info="Bắt buộc ghi hạn sử dụng in trên bao bì cho từng lô; một thùng trộn nhiều HSD thì bấm + để tách lô. Hàng móp, date ngắn, sai hàng thì từ chối tại cửa: sau khi ký nhận, rủi ro thuộc về cửa hàng. Lô còn ít hạn hơn chuẩn hoặc giao dư nhiều chỉ Store Manager được xác nhận nhận." />
      <div className="table-wrap">
        <table>
          <thead><tr><th>Hàng</th><th className="num">Đặt</th><th>Nhận: số lượng · HSD</th><th>Từ chối</th><th className="num">Giá hóa đơn</th></tr></thead>
          <tbody>
            {d.lines.map((l) => {
              const v = get(l);
              const setLot = (i: number, patch: Partial<LotIn>) => set(l.line_id, { ...v, lots: v.lots.map((y, j) => (j === i ? { ...y, ...patch } : y)) });
              return (
                <tr key={l.line_id}>
                  <td title={`${l.sku} · chuẩn nhận: còn ≥ ${l.min_remaining_days}/${l.shelf_life_days} ngày`}>{l.name}</td>
                  <td className="num">{num(l.qty)}</td>
                  <td>
                    {v.lots.map((x, i) => (
                      <div className="row lot-in" key={i}>
                        <Stepper value={x.qty === "" ? "" : Number(x.qty)} step={l.pack_size || 1} label={`Số lượng lô ${i + 1} ${l.name}`}
                          onChange={(n) => setLot(i, { qty: n === "" ? "" : String(n) })} />
                        <DateField value={x.exp} label={`HSD lô ${i + 1} ${l.name}`} onChange={(iso) => setLot(i, { exp: iso })} suggest={l.default_expiry} />
                        <ExpiryPhoto sku={l.sku} onRead={(iso) => setLot(i, { exp: iso })} />
                        {v.lots.length > 1 && (
                          <button className="icon sm ghost" aria-label="Bỏ lô" title="Bỏ lô" onClick={() => set(l.line_id, { ...v, lots: v.lots.filter((_, j) => j !== i) })}><Icon name="x" /></button>
                        )}
                      </div>
                    ))}
                    <button className="sm ghost" title="Tách lô theo HSD khác" onClick={() => set(l.line_id, { ...v, lots: [...v.lots, { qty: "0", exp: "" }] })}><Icon name="plus" /> HSD</button>
                    {isManager && (
                      <div className="row mt-1">
                        <Switch checked={v.acceptShort} onChange={(c) => set(l.line_id, { ...v, acceptShort: c })} label="Nhận date ngắn" />
                        <Switch checked={v.acceptOver} onChange={(c) => set(l.line_id, { ...v, acceptOver: c })} label={`Nhận dư (>${l.over_tolerance})`} />
                      </div>
                    )}
                  </td>
                  <td>
                    <Stepper value={v.rejected === "" ? "" : Number(v.rejected)} placeholder="0" label={`Số từ chối ${l.name}`}
                      onChange={(n) => set(l.line_id, { ...v, rejected: n === "" || n === 0 ? "" : String(n) })} />
                    {Number(v.rejected) > 0 && (
                      <div className="mt-1">
                        <Chips label={`Lý do từ chối ${l.name}`} value={v.reason} onChange={(r) => set(l.line_id, { ...v, reason: r })}
                          options={Object.entries(d.reject_reasons).map(([k, t]) => ({ value: k, label: t, tone: "bad" as const }))} />
                      </div>
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
      {err && <div className="alert error mt-2">{err}</div>}
      <div className="row mt-3">
        <button className="ok lg" disabled={m.isPending} onClick={() => { setErr(null); m.mutate(); }}><Icon name="check" /> Xác nhận nhận hàng</button>
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
      <PageHeader title="Đặt & nhận hàng" desc="Đơn chỉ được gửi sau khi Store Manager duyệt đề xuất. Nhận hàng tại đây để ghi lô và HSD." />
      <div className="card tight mb-4">
        <div className="row">
          <b>Đặt ngoài lịch</b>
          <select className="grow" style={{ maxWidth: 360 }} value={sup} onChange={(e) => setSup(e.target.value)} aria-label="Nhà cung cấp">
            <option value="">Chọn nhà cung cấp…</option>
            {sups.data?.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
          </select>
          <button className="primary" disabled={!sup || create.isPending} onClick={() => create.mutate()}><Icon name="plus" /> {create.isPending ? "Đang tính…" : "Tạo đề xuất"}</button>
        </div>
        {msg && <div className={`alert ${msg.ok ? "ok" : "error"} mt-2`}>{msg.text} {msg.ok && <button className="linklike" onClick={() => openInbox()}>Mở hộp duyệt →</button>}</div>}
      </div>
      <div className="row mb-3">
        <Segmented label="Trạng thái đơn" value={status} onChange={setStatus}
          options={Object.entries(PO_STATUS).map(([value, label]) => ({ value, label }))} />
      </div>
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Mã đơn</th><th>Nhà cung cấp</th><th>Ngày đặt</th><th>Giao dự kiến</th><th className="num">Giá trị</th><th>Trạng thái</th><th /></tr></thead>
            <tbody>
              {pos.data?.map((po) => (
                <tr key={po.id}>
                  <td>{po.code}{po.proposal_id && <span className="badges"><span className="badge accent">từ đề xuất #{po.proposal_id}</span></span>}</td>
                  <td>{po.supplier}</td>
                  <td>{dateVi(po.order_date)}</td>
                  <td>{dateVi(po.expected_date)}{po.overdue_days > 0 && <span className="badges"><span className="badge st-FAILED">trễ {po.overdue_days} ngày</span></span>}</td>
                  <td className="num">{money(po.total_value)}</td>
                  <td><span className={`badge st-${PO_BADGE[po.status]}`}><span className="dot" />{PO_STATUS[po.status]}</span></td>
                  <td className="row" style={{ justifyContent: "flex-end" }}>
                    {po.has_pdf && <button className="sm" onClick={() => openPdf(po.id).catch((e) => alert(e.message))}>PDF</button>}
                    {po.status === "SENT" && <button className="sm ok" onClick={() => { setCancelling(null); setReceiving(po.id); }}><Icon name="truck" /> Nhận hàng</button>}
                    {po.status === "SENT" && isManager && <button className="sm danger" onClick={() => { setReceiving(null); setCancelling(po); }}>Huỷ đơn</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {pos.isLoading && <Skeleton rows={4} />}
          {pos.data?.length === 0 && <EmptyState title={`Không có đơn ${PO_STATUS[status].toLowerCase()}`}>Đơn đặt hàng xuất hiện ở đây sau khi Store Manager duyệt đề xuất.</EmptyState>}
        </div>
      </div>
      {cancelling && <CancelPO key={cancelling.id} po={cancelling} onDone={() => { setCancelling(null); qc.invalidateQueries(); }} />}
      {receiving && <Receive key={receiving} id={receiving} onDone={() => { setReceiving(null); qc.invalidateQueries(); }} />}
      <SupplierReturns />
    </>
  );
}
