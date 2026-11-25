import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, getUser, type Proposal } from "../api";
import { TYPE_LABEL, compact, money } from "../format";
import ProposalCard from "./ProposalCard";
import EmptyState, { Skeleton } from "./ui/EmptyState";
import Segmented from "./ui/Segmented";
import { Chips } from "./ui/controls";

// Mở ngăn Hộp duyệt từ bất kỳ đâu: window.dispatchEvent(new CustomEvent(OPEN_INBOX_EVENT, { detail: { type } }))
// type (tuỳ chọn) = lọc sẵn một loại đề xuất, vd "PURCHASE_ORDER".
export const OPEN_INBOX_EVENT = "opschest:open-inbox";
export const openInbox = (type = "") => window.dispatchEvent(new CustomEvent(OPEN_INBOX_EVENT, { detail: { type } }));

// Gấp trước (sắp hết hiệu lực), rồi đến giá trị lớn. Đề xuất không có hạn xếp sau.
export function byUrgency(a: Proposal, b: Proposal): number {
  const ea = a.expires_at ? Date.parse(a.expires_at) : Infinity;
  const eb = b.expires_at ? Date.parse(b.expires_at) : Infinity;
  if (ea !== eb) return ea - eb;
  return Math.abs(b.est_value ?? 0) - Math.abs(a.est_value ?? 0);
}

type Tab = "pending" | "history";

// Ngăn kéo "Hộp duyệt": nơi duy nhất để duyệt đề xuất (thay cho trang Hộp duyệt cũ).
// Tab Chờ duyệt: duyệt tại chỗ; tab Lịch sử: đề xuất đã thực hiện / từ chối / hết hiệu lực.
export default function InboxPanel({ initialType = "" }: { initialType?: string }) {
  const [tab, setTab] = useState<Tab>("pending");
  const [type, setType] = useState(initialType);
  const [openId, setOpenId] = useState<number | null>(null);
  const isManager = getUser()?.role === "manager";
  const pending = useQuery({
    queryKey: ["proposals", "inbox"],
    queryFn: () => api<Proposal[]>("/proposals?status=PENDING,FAILED&limit=50"),
    refetchInterval: 30_000,
  });
  const history = useQuery({
    enabled: tab === "history",
    queryKey: ["proposals", "history"],
    queryFn: () => api<Proposal[]>("/proposals?status=EXECUTED,REJECTED,EXPIRED,SUPERSEDED&limit=50"),
  });
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<{ today: string }>("/meta") });
  const q = tab === "pending" ? pending : history;
  const all = q.data ?? [];
  const counts = all.reduce<Record<string, number>>((a, p) => ({ ...a, [p.type]: (a[p.type] ?? 0) + 1 }), {});
  const shown = all.filter((p) => !type || p.type === type);
  const list = tab === "pending" ? [...shown].sort(byUrgency) : shown;

  const poTotal = (pending.data ?? []).filter((p) => p.type === "PURCHASE_ORDER").reduce((s, p) => s + (p.est_value ?? 0), 0);
  const today = meta.data?.today?.slice(0, 10);
  const expToday = today ? (pending.data ?? []).filter((p) => p.expires_at && p.expires_at.slice(0, 10) <= today).length : 0;

  return (
    <section className="inbox" aria-label="Hộp đề xuất">
      <div className="row mb-3">
        <Segmented<Tab> label="Hộp duyệt" value={tab} onChange={(t) => { setTab(t); setOpenId(null); }} options={[
          { value: "pending", label: "Chờ duyệt", count: pending.data?.length },
          { value: "history", label: "Lịch sử" },
        ]} />
        {tab === "pending" && (
          <span className="inbox-summary" title="Xếp theo hạn hiệu lực, rồi giá trị">
            {poTotal > 0 && <span title={money(poTotal)}>Đặt hàng <b>{compact(poTotal)}</b></span>}
            {expToday > 0 && <span className="badge warn">{expToday} hết hạn hôm nay</span>}
          </span>
        )}
      </div>
      {Object.keys(counts).length > 1 && (
        <div className="mb-3">
          <Chips label="Loại đề xuất" value={type} onChange={(t) => { setType(t); setOpenId(null); }} options={[
            { value: "", label: "Tất cả", count: all.length },
            ...Object.entries(counts).map(([k, n]) => ({ value: k, label: TYPE_LABEL[k] ?? k, count: n })),
          ]} />
        </div>
      )}
      {q.isLoading && <Skeleton rows={4} />}
      {q.error && <div className="alert error">{(q.error as Error).message}</div>}
      {q.data && list.length === 0 && (
        <div className="card">
          <EmptyState title={tab === "pending" ? "Không có đề xuất nào chờ duyệt" : "Chưa có đề xuất nào"}>
            {tab === "pending" ? `Ops Chest quét tự động lúc 06:30 và 17:00${isManager ? ", hoặc bấm Quét đề xuất trong menu Công việc" : ""}.` : undefined}
          </EmptyState>
        </div>
      )}
      <div className="inbox-list">
        {list.map((p) => (
          <ProposalCard key={`${p.id}-${p.status}`} p={p} compact expanded={openId === p.id}
            onToggle={() => setOpenId(openId === p.id ? null : p.id)} />
        ))}
      </div>
    </section>
  );
}
