import type { ReactNode } from "react";

// Trạng thái trống thống nhất: một dòng chính, một dòng giải thích, hành động tuỳ chọn
export default function EmptyState({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {children && <p className="muted small">{children}</p>}
      {action}
    </div>
  );
}

// Khung xám khi đang tải, giữ chỗ để trang không nhảy
export function Skeleton({ rows = 4, height = 14 }: { rows?: number; height?: number }) {
  return (
    <div className="skeleton" aria-busy="true" aria-label="Đang tải">
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} style={{ height, width: `${92 - ((i * 17) % 30)}%` }} />
      ))}
    </div>
  );
}
