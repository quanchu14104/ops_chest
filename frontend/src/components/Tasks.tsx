import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, getUser, type WidgetSpec } from "../api";
import type { BriefingItem } from "./Briefing";
import Panel, { type PanelSpec } from "./Panels";
import Widget from "./Widgets";
import { Skeleton } from "./ui/EmptyState";
import { Icon } from "./ui/controls";

// Mở một việc trong popup từ bất kỳ đâu (menu Công việc, bản tin): window.dispatchEvent(new CustomEvent(OPEN_TASK_EVENT, {detail: key}))
export const OPEN_TASK_EVENT = "opschest:task";
export const openTask = (key: string) => window.dispatchEvent(new CustomEvent<string>(OPEN_TASK_EVENT, { detail: key }));

type IconName = "check" | "tag" | "trash" | "scan" | "truck" | "note" | "chat" | "plus";
// Thẻ sống (panel) tự tải dữ liệu; việc còn lại lấy qua /chat/quick (chỉ đọc, không ghi gì, không qua LLM)
export const TASKS: { key: string; label: string; icon: IconName; briefing?: string; manager?: boolean }[] = [
  { key: "pending", label: "Chờ duyệt", icon: "check", briefing: "pending" },
  { key: "lots", label: "Cận date", icon: "tag", briefing: "expiring" },
  { key: "pull", label: "Rút kệ", icon: "trash", briefing: "pull" },
  { key: "date_check", label: "Kiểm date", icon: "scan", briefing: "date_check" },
  { key: "count_due", label: "Kiểm kê", icon: "note", briefing: "count_due" },
  { key: "orders", label: "Nhận hàng", icon: "truck", briefing: "po" },
  { key: "returns", label: "Trả NCC", icon: "truck" },
  { key: "oos", label: "Hàng hết", icon: "note", briefing: "oos" },
  { key: "kpi", label: "KPI", icon: "note" },
  { key: "scan", label: "Quét đề xuất", icon: "scan", manager: true },
  { key: "scan_evening", label: "Quét giảm giá", icon: "tag", manager: true },
];

const TITLES: Record<string, string> = {
  pending: "Đề xuất chờ duyệt", lots: "Hàng cận date", pull: "Rút kệ cuối ngày", date_check: "Kiểm date", count_due: "Kiểm kê",
  orders: "Đơn chờ giao", returns: "Phiếu trả NCC", oos: "Mặt hàng đang hết", kpi: "KPI 30 ngày", hypotheses: "Giả thuyết nhu cầu",
  scan: "Quét & tạo đề xuất", scan_evening: "Quét giảm giá cuối ngày", inventory: "Tồn kho",
};

// "tên:đối số" -> thẻ sống hoặc khóa truy vấn nhanh
function resolve(key: string): { title: string; panel?: PanelSpec; quick?: string; scan?: "morning" | "evening" } {
  const [name, arg] = key.split(":");
  const title = TITLES[name] ?? name;
  const panel = (p: PanelSpec["panel"], params: Record<string, unknown> = {}): PanelSpec => ({ kind: "panel", panel: p, title, params });
  if (name === "pending") return { title, panel: panel("inbox", { type: arg ?? null }) };
  if (name === "lots") return { title, panel: panel("lots", { days: arg ? Number(arg) : 3 }) };
  if (name === "orders") return { title, panel: panel("orders") };
  if (name === "returns") return { title, panel: panel("returns") };
  // Quét giống job 06:30 (sáng) / 17:00 (giảm giá cuối ngày): chỉ tạo đề xuất chờ duyệt, rồi hiện thẻ duyệt
  if (name === "scan") return { title, scan: "morning", panel: panel("inbox", { type: null }) };
  if (name === "scan_evening") return { title, scan: "evening", panel: panel("inbox", { type: "MARKDOWN" }) };
  return { title, quick: key };
}

// Số đếm trên từng việc lấy từ bản tin (đã tải sẵn ở trang chủ)
function useCounts(): Record<string, number> {
  const pending = useQuery({ queryKey: ["pending-count"], queryFn: () => api<unknown[]>("/proposals?status=PENDING&limit=200") });
  const brief = useQuery({ queryKey: ["briefing"], queryFn: () => api<{ items: BriefingItem[] }>("/briefing") });
  const out: Record<string, number> = {};
  for (const it of brief.data?.items ?? []) out[it.id] = it.count;
  out.pending = pending.data?.length ?? 0;
  return out;
}

// Menu Công việc: popup lưới nút to; bấm một việc là mở popup của việc đó
export function TaskMenu({ disabled }: { disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const counts = useCounts();
  const isManager = getUser()?.role === "manager";
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div className="task-menu-wrap" ref={ref}>
      <button type="button" className={`task-menu-btn ${open ? "on" : ""}`} disabled={disabled} onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu" aria-expanded={open}>
        <svg viewBox="0 0 24 24" aria-hidden><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" /></svg>
        Công việc
        {counts.pending > 0 && <span className="chip-count hot">{counts.pending}</span>}
      </button>
      {open && (
        <div className="task-menu" role="menu" aria-label="Công việc">
          {TASKS.filter((t) => !t.manager || isManager).map((t) => {
            const n = t.briefing ? counts[t.briefing] : undefined;
            return (
              <button key={t.key} role="menuitem" className={`task-tile ${t.key === "pending" && n ? "hot" : ""}`}
                onClick={() => { setOpen(false); openTask(t.key); }}>
                <span className="task-ico"><Icon name={t.icon} /></span>
                <span className="task-name">{t.label}</span>
                {n ? <span className="task-n">{n}</span> : null}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function QuickBody({ k }: { k: string }) {
  const q = useQuery({ queryKey: ["quick", k], queryFn: () => api<{ title: string; ui: ({ type: "widget" } & WidgetSpec)[] }>(`/chat/quick/${encodeURIComponent(k)}`) });
  if (q.isLoading) return <Skeleton rows={6} />;
  if (q.error) return <div className="alert error">{(q.error as Error).message}</div>;
  return (
    <div className="panel-stack">
      {q.data?.ui.map((u, i) => {
        const { type: _t, ...spec } = u;
        return <Widget key={i} spec={spec as WidgetSpec} />;
      })}
    </div>
  );
}

function ScanBody({ panel, kind }: { panel: PanelSpec; kind: "morning" | "evening" }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["scan-run", kind],
    queryFn: async () => { await api("/proposals/generate", { method: "POST", body: { kind } }); await qc.invalidateQueries(); return true; },
    staleTime: Infinity, gcTime: 0,
  });
  if (q.isLoading) return <><p className="muted">Đang quét…</p><Skeleton rows={4} /></>;
  if (q.error) return <div className="alert error">{(q.error as Error).message}</div>;
  return <Panel spec={panel} />;
}

// Popup của một việc: lớp phủ giữa màn hình (toàn màn hình trên điện thoại), Esc hoặc bấm ra ngoài để đóng
export function TaskDialog() {
  const [key, setKey] = useState<string | null>(null);
  useEffect(() => {
    const on = (e: Event) => setKey((e as CustomEvent<string>).detail);
    window.addEventListener(OPEN_TASK_EVENT, on);
    return () => window.removeEventListener(OPEN_TASK_EVENT, on);
  }, []);
  useEffect(() => {
    if (!key) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setKey(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [key]);
  if (!key) return null;
  const t = resolve(key);
  return (
    <div className="task-dialog-scrim" onMouseDown={(e) => e.target === e.currentTarget && setKey(null)}>
      <div className="task-dialog" role="dialog" aria-modal="true" aria-label={t.title}>
        <div className="task-dialog-head">
          <h2>{t.title}</h2>
          <span className="spacer" />
          <button className="icon ghost" aria-label="Đóng" onClick={() => setKey(null)}><Icon name="x" /></button>
        </div>
        <div className="task-dialog-body" key={key}>
          {t.scan && t.panel ? <ScanBody panel={t.panel} kind={t.scan} /> : t.panel ? <Panel spec={t.panel} /> : <QuickBody k={t.quick!} />}
        </div>
      </div>
    </div>
  );
}
