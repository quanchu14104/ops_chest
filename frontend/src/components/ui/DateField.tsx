import { useEffect, useRef, useState } from "react";
import { dateVi } from "../../format";

// "dd/mm/yyyy" -> "yyyy-mm-dd"; null nếu sai định dạng hoặc không có ngày đó (vd 31/02)
export function parseViDate(s: string): string | null {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s.trim());
  if (!m) return null;
  const [, d, mo, y] = m;
  const dt = new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d)));
  if (dt.getUTCFullYear() !== Number(y) || dt.getUTCMonth() !== Number(mo) - 1 || dt.getUTCDate() !== Number(d)) return null;
  return `${y}-${mo}-${d}`;
}

// Gõ số liền nhau thì tự chèn dấu "/". Khi đang xoá thì giữ nguyên để xoá lùi qua dấu "/" không bị kẹt.
function mask(raw: string, deleting: boolean): string {
  if (deleting) return raw.replace(/[^\d/]/g, "");
  const digits = raw.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) return digits.length === 2 ? `${digits}/` : digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}${digits.length === 4 ? "/" : ""}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

// Ô ngày theo kiểu Việt Nam (dd/mm/yyyy), không phụ thuộc ngôn ngữ trình duyệt.
// value/onChange dùng ISO; chuỗi rỗng = chưa nhập hoặc chưa hợp lệ.
// `suggest`: ngày gợi ý (vd HSD mặc định) — chỉ hiện để người dùng bấm "Dùng", không tự điền.
export default function DateField({ value, onChange, label, suggest, min }: {
  value: string; onChange: (iso: string) => void; label: string; suggest?: string | null; min?: string;
}) {
  const [text, setText] = useState(value ? dateVi(value) : "");
  const [touched, setTouched] = useState(false);
  const emitted = useRef(value);

  // Giá trị đổi từ bên ngoài (bấm "Dùng gợi ý", form reset) thì đồng bộ lại chữ trong ô
  useEffect(() => {
    if (value !== emitted.current) {
      emitted.current = value;
      setText(value ? dateVi(value) : "");
    }
  }, [value]);

  const emit = (iso: string) => {
    emitted.current = iso;
    if (iso !== value) onChange(iso);
  };
  const iso = parseViDate(text);
  const tooEarly = !!(iso && min && iso < min);
  const invalid = text.length > 0 && (text.length >= 10 || touched) && (!iso || tooEarly);

  return (
    <span className="datefield">
      <input
        className={invalid ? "invalid" : undefined}
        value={text}
        inputMode="numeric"
        placeholder="dd/mm/yyyy"
        maxLength={10}
        aria-label={label}
        aria-invalid={invalid || undefined}
        title={invalid ? (tooEarly ? `Ngày phải từ ${dateVi(min)} trở đi` : "Ngày không hợp lệ (dd/mm/yyyy)") : undefined}
        onChange={(e) => {
          const kind = (e.nativeEvent as InputEvent).inputType ?? "";
          const t = mask(e.target.value, kind.startsWith("delete"));
          setText(t);
          const p = parseViDate(t);
          emit(p && !(min && p < min) ? p : "");
        }}
        onBlur={() => setTouched(true)}
      />
      {suggest && !text && (
        <button type="button" className="sm ghost suggest" onClick={() => { setText(dateVi(suggest)); emit(suggest); }}
          title="Điền ngày gợi ý; vẫn cần đối chiếu với HSD in trên bao bì">
          Gợi ý {dateVi(suggest)} · Dùng
        </button>
      )}
    </span>
  );
}
