import { useQuery } from "@tanstack/react-query";
import { api, getUser } from "../api";
import { Skeleton } from "./ui/EmptyState";
import { Icon, InfoTip } from "./ui/controls";

export type BriefingItem = { id: string; level: "action" | "warn" | "info"; count: number; text: string; prompt: string; quick?: string; detail?: string[] };
type Briefing = { today: string; date_label: string; items: BriefingItem[]; all_clear: boolean };

// Mỗi mục bản tin mở đúng thẻ tác vụ ngay trong chat (lệnh nhanh, không qua LLM)
function commandFor(id: string): { key: string; label: string } | null {
  if (id === "pending") return { key: "pending", label: "Mở thẻ duyệt" };
  if (id === "pulled") return { key: "pending:DISPOSE", label: "Duyệt ghi hủy" };
  if (id === "expired" || id === "pull") return { key: "pull", label: "Mở phiếu rút kệ" };
  if (id === "expiring") return { key: "lots", label: "Chọn lô xử lý" };
  if (id === "date_check") return { key: "date_check", label: "Mở phiếu kiểm date" };
  if (id === "phantom" || id === "count_due") return { key: "count_due", label: "Mở phiếu kiểm kê" };
  if (id === "due" || id.startsWith("closure-")) return { key: "pending:PURCHASE_ORDER", label: "Duyệt đơn đặt hàng" };
  if (id === "po" || id === "po_late" || id.startsWith("short-")) return { key: "orders", label: "Mở đơn chờ giao" };
  if (id.startsWith("return-")) return { key: "returns", label: "Mở phiếu trả NCC" };
  if (id === "oos") return { key: "oos", label: "Xem mặt hàng đang hết" };
  if (id.startsWith("hypothesis-")) return { key: "hypotheses", label: "Xem giả thuyết" };
  return null;
}

const GROUPS: { level: BriefingItem["level"]; title: string }[] = [
  { level: "action", title: "Cần quyết" },
  { level: "warn", title: "Cần để ý" },
  { level: "info", title: "Việc trong ngày" },
];

type Handlers = { onAsk: (prompt: string, quick?: string) => void; onCommand: (key: string) => void; disabled?: boolean };

function Item({ it, onAsk, onCommand, disabled }: { it: BriefingItem } & Handlers) {
  const t = commandFor(it.id);
  // Số đếm đã nằm trong ô số bên trái: bỏ số ở đầu câu cho đỡ lặp
  const text = it.text.replace(new RegExp(`^${it.count}\\s+`), "");
  const body = (
    <>
      <span className="bi-count">{it.count}</span>
      <span className="bi-text">{text}</span>
      {t && <span className="bi-chev"><Icon name="chevron" /></span>}
    </>
  );
  return (
    <li className={`briefing-item ${it.level}`}>
      {t ? (
        <button className="bi-main" title={t.label} disabled={disabled} onClick={() => onCommand(t.key)}>{body}</button>
      ) : (
        <div className="bi-main">{body}</div>
      )}
      {it.detail && it.detail.length > 1 && <InfoTip align="right" text={it.detail.join(" · ")} />}
      <button className="icon ghost bi-ask" disabled={disabled} onClick={() => onAsk(it.prompt, it.quick)}
        aria-label="Hỏi Ops Chest về mục này" title="Hỏi Ops Chest"><Icon name="chat" /></button>
    </li>
  );
}

// Bản tin đầu ngày: dựng từ dữ liệu thật ở backend (không qua LLM). Mỗi mục dẫn tới trang xử lý, hoặc hỏi Ops Chest.
export default function Briefing({ onAsk, onCommand, disabled }: Handlers) {
  const q = useQuery({ queryKey: ["briefing"], queryFn: () => api<Briefing>("/briefing"), refetchInterval: 60_000 });
  const isManager = getUser()?.role === "manager";
  if (q.isLoading) return <div className="hello"><Skeleton rows={3} height={18} /></div>;
  if (q.error || !q.data) return null; // lỗi bản tin không được chặn việc dùng chat
  const b = q.data;
  const nAction = b.items.filter((i) => i.level === "action").length;
  const nOther = b.items.length - nAction;
  return (
    <>
      <div className="hello">
        {b.all_clear || b.items.length === 0 ? (
          <h1>Hôm nay kho ổn</h1>
        ) : (
          <div className="bi-summary">
            {nAction > 0 && <span className="bi-stat action"><b>{nAction}</b> cần {isManager ? "quyết" : "SM quyết"}</span>}
            {nOther > 0 && <span className="bi-stat"><b>{nOther}</b> việc khác</span>}
          </div>
        )}
      </div>
      {b.all_clear ? null : (
        <div className="card focus">
          {GROUPS.map((g) => {
            const list = b.items.filter((i) => i.level === g.level);
            if (!list.length) return null;
            return (
              <section key={g.level} className={`bi-group ${g.level}`} aria-label={g.title}>
                <div className="focus-head">
                  <span>{g.title}</span>
                  <span>{list.length}</span>
                </div>
                <ul className="briefing-list">
                  {list.map((it) => <Item key={it.id} it={it} onAsk={onAsk} onCommand={onCommand} disabled={disabled} />)}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}
