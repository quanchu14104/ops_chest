import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export type BriefingItem = { id: string; level: "action" | "warn" | "info"; count: number; text: string; prompt: string; quick?: string };
type Briefing = { today: string; date_label: string; items: BriefingItem[]; all_clear: boolean };

// Bản tin đầu ngày: dựng từ dữ liệu thật ở backend (không qua LLM). Bấm một dòng để hỏi Ops Chest về nó.
export default function Briefing({ onAsk, disabled }: { onAsk: (prompt: string, quick?: string) => void; disabled?: boolean }) {
  const q = useQuery({ queryKey: ["briefing"], queryFn: () => api<Briefing>("/briefing"), refetchInterval: 60_000 });
  if (q.isLoading) return <div className="hello"><p>Đang chuẩn bị bản tin…</p></div>;
  if (q.error || !q.data) return null; // lỗi bản tin không được chặn việc dùng chat
  const b = q.data;
  const urgent = b.items.filter((i) => i.level !== "info").length;
  const title = b.all_clear || b.items.length === 0 ? "Hôm nay kho ổn, chưa có việc gấp." : urgent > 0 ? `Hôm nay có ${urgent} việc cần anh/chị quyết.` : "Hôm nay có vài điểm cần lưu ý.";
  return (
    <>
      <div className="hello">
        <h1>{title}</h1>
        <p>{b.date_label}. Mọi đề xuất chỉ thực hiện sau khi anh/chị duyệt.</p>
      </div>
      {b.all_clear ? (
        <p className="secondary">Anh/chị có thể hỏi Ops Chest bất cứ điều gì về kho.</p>
      ) : (
        <div className="card focus">
          <div className="focus-head">
            <span>Việc hôm nay</span>
            <span>{b.items.length} mục</span>
          </div>
          <ul className="briefing-list">
            {b.items.map((it) => (
              <li key={it.id}>
                <button className={`briefing-item ${it.level}`} disabled={disabled} onClick={() => onAsk(it.prompt, it.quick)} title="Hỏi Ops Chest về mục này">
                  <span className="bi-dot" aria-hidden />
                  <span>{it.text}</span>
                  <span className="bi-go">
                    <span>Hỏi Ops Chest</span>
                    <svg viewBox="0 0 24 24" aria-hidden><path d="M5 12h14M13 6l6 6-6 6" /></svg>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
