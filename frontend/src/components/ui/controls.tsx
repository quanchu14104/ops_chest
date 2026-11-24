import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

// Ô số có nút −/+ hai bên: bấm là đổi, không cần gõ. Giữ nút để tăng/giảm liên tục. Vẫn gõ được khi cần số lớn.
export function Stepper({ value, onChange, step = 1, min = 0, max, label, changed, placeholder }: {
  value: number | ""; onChange: (v: number | "") => void; step?: number; min?: number; max?: number; label: string;
  changed?: boolean; placeholder?: string;
}) {
  const timer = useRef<number | null>(null);
  const cur = useRef(value);
  cur.current = value;
  const clamp = (v: number) => Math.max(min, max != null ? Math.min(max, v) : v);
  const bump = (dir: 1 | -1) => onChange(clamp((cur.current === "" ? 0 : cur.current) + dir * step));
  const stop = () => {
    if (timer.current != null) window.clearInterval(timer.current);
    timer.current = null;
  };
  useEffect(() => stop, []);
  // Bấm một lần = một bước; giữ quá 400ms thì chạy liên tục
  const hold = (dir: 1 | -1) => {
    bump(dir);
    stop();
    const start = window.setTimeout(() => {
      timer.current = window.setInterval(() => bump(dir), 90);
    }, 400);
    timer.current = start;
  };
  const v = value === "" ? null : value;
  return (
    <span className={`stepper ${changed ? "changed" : ""}`}>
      <button type="button" tabIndex={-1} aria-label={`Giảm ${label}`} disabled={v != null && v <= min}
        onPointerDown={() => hold(-1)} onPointerUp={stop} onPointerLeave={stop}>−</button>
      <input inputMode="numeric" value={value} placeholder={placeholder} aria-label={label}
        onChange={(e) => {
          const t = e.target.value.replace(/\D/g, "");
          onChange(t === "" ? "" : clamp(Number(t)));
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp") { e.preventDefault(); bump(1); }
          if (e.key === "ArrowDown") { e.preventDefault(); bump(-1); }
        }} />
      <button type="button" tabIndex={-1} aria-label={`Tăng ${label}`} disabled={v != null && max != null && v >= max}
        onPointerDown={() => hold(1)} onPointerUp={stop} onPointerLeave={stop}>+</button>
    </span>
  );
}

// Thanh trượt mức giảm giá: kéo là thấy % ngay, bước 10%
export function PctSlider({ value, onChange, min = 0.1, max = 0.7, step = 0.1, label, disabled }: {
  value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; label: string; disabled?: boolean;
}) {
  const pctOf = (v: number) => Math.round(v * 100);
  const fill = max > min ? ((value - min) / (max - min)) * 100 : 100;
  return (
    <span className="pct-slider">
      <input type="range" min={pctOf(min)} max={pctOf(max)} step={pctOf(step)} value={pctOf(value)} disabled={disabled}
        aria-label={label} aria-valuetext={`${pctOf(value)}%`} style={{ "--fill": `${fill}%` } as CSSProperties}
        onChange={(e) => onChange(Number(e.target.value) / 100)} />
      <b className="pct-value">{pctOf(value)}%</b>
    </span>
  );
}

export type Chip<T extends string> = { value: T; label: ReactNode; count?: number; tone?: "bad" | "warn" | "ok" };

// Nhóm chip chọn một (bấm lại chip đang chọn thì bỏ chọn nếu `allowNone`)
export function Chips<T extends string>({ value, onChange, options, label, allowNone = false }: {
  value: T | ""; onChange: (v: T | "") => void; options: Chip<T>[]; label: string; allowNone?: boolean;
}) {
  return (
    <div className="chips" role="radiogroup" aria-label={label}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button key={o.value} type="button" role="radio" aria-checked={on} className={`chip ${on ? "on" : ""} ${o.tone ?? ""}`}
            onClick={() => onChange(on && allowNone ? "" : o.value)}>
            {o.label}
            {o.count != null && <span className="chip-count">{o.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

// Công tắc bật/tắt thay cho ô tích
export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode }) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" aria-hidden><span className="thumb" /></span>
      <span>{label}</span>
    </label>
  );
}

// Chữ giải thích không bắt buộc: thu vào biểu tượng ⓘ, rê chuột / chạm để xem
export function InfoTip({ text, align = "left" }: { text: ReactNode; align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  return (
    <span className={`infotip ${open ? "open" : ""} ${align}`} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" className="info-btn" aria-label="Giải thích" aria-expanded={open}
        onClick={() => setOpen((o) => !o)} onBlur={() => setOpen(false)}>i</button>
      {open && <span className="info-tip" role="tooltip">{text}</span>}
    </span>
  );
}

// Tiêu đề thẻ: tên + ⓘ giải thích + hành động bên phải
export function CardTitle({ title, info, children }: { title: ReactNode; info?: ReactNode; children?: ReactNode }) {
  return (
    <div className="card-title">
      <h2>{title}</h2>
      {info && <InfoTip text={info} />}
      <span className="spacer" />
      {children}
    </div>
  );
}

// Biểu tượng nét đơn dùng trong nút
const ICONS: Record<string, string> = {
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6 6 18",
  chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z",
  chevron: "M9 6l6 6-6 6",
  down: "M6 9l6 6 6-6",
  tag: "M3 12V4h8l10 10-8 8L3 12ZM7.5 7.5h.01",
  truck: "M3 6h11v10H3zM14 10h4l3 3v3h-7M7 19a2 2 0 1 0 0-.01M17 19a2 2 0 1 0 0-.01",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  note: "M4 4h16v12H8l-4 4V4Z",
  plus: "M12 5v14M5 12h14",
  scan: "M4 8V4h4M20 8V4h-4M4 16v4h4M20 16v4h-4M7 12h10",
};
export function Icon({ name }: { name: keyof typeof ICONS }) {
  return <svg viewBox="0 0 24 24" aria-hidden><path d={ICONS[name]} /></svg>;
}
