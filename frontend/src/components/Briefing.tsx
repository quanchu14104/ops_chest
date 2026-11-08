import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export type BriefingItem = { id: string; level: "action" | "warn" | "info"; count: number; text: string; prompt: string };
type Briefing = { today: string; date_label: string; items: BriefingItem[]; all_clear: boolean };

const ICON: Record<BriefingItem["level"], string> = { action: "●", warn: "▲", info: "○" };

// Bản tin đầu ngày: dựng từ dữ liệu thật ở backend (không qua LLM). Bấm một dòng để hỏi Ops Chest về nó.
export default function Briefing({ onAsk, disabled }: { onAsk: (prompt: string) => void; disabled?: boolean }) {
  const q = useQuery({ queryKey: ["briefing"], queryFn: () => api<Briefing>("/briefing"), refetchInterval: 60_000 });
  if (q.isLoading) return <div className="card briefing muted">Đang chuẩn bị bản tin…</div>;
  if (q.error || !q.data) return null; // lỗi bản tin không được chặn việc dùng chat
  const b = q.data;
  return (
    <div className="card briefing">
      <h2>Hôm nay {b.date_label}</h2>
      {b.all_clear ? (
        <p className="secondary">Không có việc gấp nào. Anh/chị có thể hỏi Ops Chest bất cứ điều gì về kho.</p>
      ) : (
        <ul className="briefing-list">
          {b.items.map((it) => (
            <li key={it.id}>
              <button className={`briefing-item ${it.level}`} disabled={disabled} onClick={() => onAsk(it.prompt)} title="Hỏi Ops Chest về mục này">
                <span className="briefing-icon" aria-hidden>{ICON[it.level]}</span>
                <span>{it.text}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
