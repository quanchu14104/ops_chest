import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Proposal } from "../api";
import ProposalCard from "./ProposalCard";

// Gấp trước (sắp hết hiệu lực), rồi đến giá trị lớn. Đề xuất không có hạn xếp sau.
function byUrgency(a: Proposal, b: Proposal): number {
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
  return (
    <section className="inbox" aria-label="Hộp đề xuất">
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="secondary">{list.length > 0 ? `${list.length} đề xuất chờ anh/chị` : "Không có đề xuất nào chờ"}</span>
        <span className="spacer" />
        <Link to="/approvals" className="small" onClick={onNavigate}>Xem tất cả và lịch sử →</Link>
      </div>
      {q.isLoading && <p className="muted small">Đang tải…</p>}
      {q.error && <div className="alert error">{(q.error as Error).message}</div>}
      {q.data && list.length === 0 && (
        <div className="card" style={{ textAlign: "center", padding: "40px 16px" }}>
          <h2>Hộp duyệt trống</h2>
          <p className="muted small">Ops Chest quét tự động lúc 06:30 và 17:00, hoặc anh/chị có thể nhờ trong chat.</p>
        </div>
      )}
      <div className="inbox-list">
        {list.map((p) => (
          <ProposalCard key={`${p.id}-${p.status}`} p={p} compact />
        ))}
      </div>
    </section>
  );
}
