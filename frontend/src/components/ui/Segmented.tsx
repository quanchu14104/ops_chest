import { useRef, type KeyboardEvent, type ReactNode } from "react";

export type SegOption<T extends string> = { value: T; label: ReactNode; count?: number };

// Nhóm tab dạng nút liền nhau; mũi tên trái/phải chuyển tab (chuẩn tablist)
export default function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T; onChange: (v: T) => void; options: SegOption<T>[]; label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const onKey = (e: KeyboardEvent) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const i = options.findIndex((o) => o.value === value);
    const next = options[(i + (e.key === "ArrowRight" ? 1 : options.length - 1)) % options.length];
    onChange(next.value);
    requestAnimationFrame(() => ref.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus());
  };
  return (
    <div className="seg" role="tablist" aria-label={label} ref={ref} onKeyDown={onKey}>
      {options.map((o) => (
        <button key={o.value} type="button" role="tab" aria-selected={o.value === value} tabIndex={o.value === value ? 0 : -1}
          className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
          {o.count != null && <span className="seg-count">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}
