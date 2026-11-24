import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useRef, useState } from "react";
import { api, getUser, type Proposal } from "../api";
import { TYPE_LABEL, compact, dateVi, money } from "../format";
import { CancelPO, Receive, type PO } from "../pages/Orders";
import ExpiringLots from "./ExpiringLots";
import { byUrgency } from "./InboxPanel";
import ProposalCard from "./ProposalCard";
import SupplierReturns from "./SupplierReturns";
import EmptyState, { Skeleton } from "./ui/EmptyState";
import { Chips, Icon } from "./ui/controls";

// Thẻ tác vụ SỐNG trong chat: tự tải số liệu hiện tại và có nút thao tác thật (đi qua REST có kiểm quyền).
// Backend chỉ phát {kind: "panel", panel, params}; xem app/agent/widgets.py::panel.
export type PanelSpec = { kind: "panel"; panel: "inbox" | "lots" | "orders" | "returns"; title: string; params: Record<string, unknown> };

export default function Panel({ spec }: { spec: PanelSpec }) {
  if (spec.panel === "inbox") return <InboxCard type={(spec.params.type as string | null) ?? ""} />;
  if (spec.panel === "lots") return <ExpiringLots initialDays={Number(spec.params.days ?? 3)} showKpis={false} />;
  if (spec.panel === "orders") return <OrdersCard />;
  if (spec.panel === "returns") return <SupplierReturns />;
  return null;
}

// Đề xuất chờ duyệt, duyệt ngay trong chat. Thẻ đã thấy vẫn giữ lại sau khi duyệt để hiện kết quả (đã gửi đơn...).
function InboxCard({ type: initialType }: { type: string }) {
  const [type, setType] = useState(initialType);
  const q = useQuery({
    queryKey: ["proposals", "inbox"],
    queryFn: () => api<Proposal[]>("/proposals?status=PENDING,FAILED&limit=50"),
  });
  const seen = useRef(new Map<number, Proposal>());
  for (const p of q.data ?? []) if (!seen.current.has(p.id)) seen.current.set(p.id, p);
  const pendingIds = new Set((q.data ?? []).map((p) => p.id));
  const all = [...seen.current.values()];
  const list = all.filter((p) => !type || p.type === type).sort(byUrgency);
  const counts = (q.data ?? []).reduce<Record<string, number>>((a, p) => ({ ...a, [p.type]: (a[p.type] ?? 0) + 1 }), {});
  const [openId, setOpenId] = useState<number | null | undefined>(undefined);
  const firstPending = list.find((p) => pendingIds.has(p.id))?.id ?? null;
  const current = openId === undefined ? firstPending : openId;

  if (q.isLoading) return <div className="card"><Skeleton rows={4} /></div>;
  return (
    <div className="panel-stack">
      {(q.data?.length ?? 0) > 0 && Object.keys(counts).length > 1 && (
        <Chips label="Loại đề xuất" value={type} onChange={setType} options={[
          { value: "", label: "Tất cả", count: q.data?.length },
          ...Object.entries(counts).map(([k, n]) => ({ value: k, label: TYPE_LABEL[k] ?? k, count: n })),
        ]} />
      )}
      {list.length === 0 ? (
        <div className="card"><EmptyState title="Không còn đề xuất nào chờ duyệt" /></div>
      ) : list.map((p) => (
        <ProposalCard key={p.id} p={p} compact expanded={current === p.id} onToggle={() => setOpenId(current === p.id ? null : p.id)} />
      ))}
    </div>
  );
}

// Đơn chờ giao: bấm Nhận hàng là form nhận mở ngay dưới đơn; Store Manager huỷ được đơn NCC không giao.
function OrdersCard() {
  const qc = useQueryClient();
  const isManager = getUser()?.role === "manager";
  const q = useQuery({ queryKey: ["pos", "SENT"], queryFn: () => api<PO[]>("/purchase-orders?status=SENT&limit=100") });
  const [open, setOpen] = useState<{ id: number; mode: "receive" | "cancel" } | null>(null);
  const close = () => { setOpen(null); qc.invalidateQueries(); };
  if (q.isLoading) return <div className="card"><Skeleton rows={3} /></div>;
  if (!q.data?.length) return <div className="card"><EmptyState title="Không có đơn nào chờ giao" /></div>;
  return (
    <div className="card">
      <div className="table-wrap">
        <table className="stack-sm">
          <thead><tr><th>Đơn</th><th>Giao</th><th className="num">Giá trị</th><th aria-label="Thao tác" /></tr></thead>
          <tbody>
            {q.data.map((po) => (
              <Fragment key={po.id}>
                <tr>
                  <td className="cell-main" title={po.code}>{po.supplier}</td>
                  <td data-label="Giao">
                    {dateVi(po.expected_date)}
                    {po.overdue_days > 0 && <span className="badges"><span className="badge bad">trễ {po.overdue_days} ngày</span></span>}
                  </td>
                  <td data-label="Giá trị" className="num" title={money(po.total_value)}>{compact(po.total_value)}</td>
                  <td className="num row-actions">
                    <button className="sm ok" onClick={() => setOpen(open?.id === po.id && open.mode === "receive" ? null : { id: po.id, mode: "receive" })}>
                      <Icon name="truck" /> Nhận hàng
                    </button>
                    {isManager && (
                      <button className="icon sm danger" aria-label={`Huỷ đơn ${po.code}`} title="Huỷ đơn"
                        onClick={() => setOpen(open?.id === po.id && open.mode === "cancel" ? null : { id: po.id, mode: "cancel" })}><Icon name="x" /></button>
                    )}
                  </td>
                </tr>
                {open?.id === po.id && (
                  <tr className="opt-row">
                    <td colSpan={4}>
                      {open.mode === "receive" ? <Receive id={po.id} onDone={close} /> : <CancelPO po={po} onDone={close} />}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
