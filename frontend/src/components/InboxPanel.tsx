import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, getUser, type Proposal } from "../api";
import ProposalCard from "./ProposalCard";
import EmptyState, { Skeleton } from "./ui/EmptyState";

// Phát sự kiện này để mở ngăn Hộp duyệt từ bất kỳ đâu (vd dòng "đề xuất chờ duyệt" trong bản tin)
export const OPEN_INBOX_EVENT = "opschest:open-inbox";

// Gấp trước (sắp hết hiệu lực), rồi đến giá trị lớn. Đề xuất không có hạn xếp sau.
export function byUrgency(a: Proposal, b: Proposal): number {
  const ea = a.expires_at ? Date.parse(a.expires_at) : Infinity;
  const eb = b.expires_at ? Date.parse(b.expires_at) : Infinity;
  if (ea !== eb) return ea - eb;
  return Math.abs(b.est_value ?? 0) - Math.abs(a.est_value ?? 0);
}

// Nội dung ngăn kéo "Hộp duyệt": danh sách đề xuất đang chờ, duyệt tại chỗ.
export default function InboxPanel({ onNavigate }: { onNavigate?: () => void }) {
  const q = useQuery({
    queryKey: ["proposals", "inbox"],
    queryFn: () => api<Proposal[]>("/proposals?status=PENDING,FAILED&limit=50"),
    refetchInterval: 30_000,
  });
  const list = [...(q.data ?? [])].sort(byUrgency);
  const isManager = getUser()?.role === "manager";
  // Ngăn kéo hẹp: mỗi lúc chỉ mở một thẻ, mặc định gập hết để thấy cả danh sách
  const [openId, setOpenId] = useState<number | null>(null);
  return (
    <section className="inbox" aria-label="Hộp đề xuất">
      <div className="row mb-3">
        <span className="secondary">
          {list.length > 0 ? `${list.length} đề xuất chờ ${isManager ? "anh/chị" : "Store Manager"} duyệt` : "Không có đề xuất nào chờ"}
        </span>
        <span className="spacer" />
        <Link to="/approvals" className="small" onClick={onNavigate}>Xem tất cả và lịch sử →</Link>
      </div>
      {q.isLoading && <Skeleton rows={4} />}
      {q.error && <div className="alert error">{(q.error as Error).message}</div>}
      {q.data && list.length === 0 && (
        <div className="card">
          <EmptyState title="Hộp duyệt trống">Ops Chest quét tự động lúc 06:30 và 17:00, hoặc anh/chị có thể nhờ trong chat.</EmptyState>
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
