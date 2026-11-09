import { useRef, useState } from "react";
import { api } from "../api";
import { dateVi } from "../format";

type Read = { expiry_date: string | null; raw_text: string | null; warnings: string[] };

const MAX_SIDE = 1280;

// Thu nhỏ trước khi gửi: ảnh điện thoại vài MB, trong khi đọc chữ trên tem chỉ cần khoảng 1280px
async function toJpegBase64(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
}

// Chỉ điền sẵn ô HSD. Người nhận hàng vẫn phải đối chiếu với bao bì và bấm xác nhận.
export default function ExpiryPhoto({ sku, disabled, onRead }: { sku: string; disabled?: boolean; onRead: (iso: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState<{ ok: boolean; text: string } | null>(null);

  async function pick(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setHint(null);
    try {
      const image_base64 = await toJpegBase64(file);
      const r = await api<Read>("/vision/expiry", { method: "POST", body: { image_base64, mime_type: "image/jpeg", sku } });
      if (r.expiry_date) {
        onRead(r.expiry_date);
        setHint({ ok: r.warnings.length === 0, text: `Đọc được ${dateVi(r.expiry_date)}${r.warnings.length ? `. ${r.warnings.join(" ")}` : ". Hãy đối chiếu với bao bì."}` });
      } else {
        setHint({ ok: false, text: r.warnings.join(" ") });
      }
    } catch (e) {
      setHint({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <>
      <input ref={input} type="file" accept="image/*" capture="environment" hidden onChange={(e) => pick(e.target.files?.[0])} aria-label={`Ảnh tem HSD ${sku}`} />
      <button type="button" className="sm" disabled={disabled || busy} onClick={() => input.current?.click()} style={{ marginLeft: 6 }}>
        {busy ? "Đang đọc…" : "Chụp HSD"}
      </button>
      {hint && <div className={`small ${hint.ok ? "muted" : "secondary"}`} style={{ marginTop: 4, maxWidth: 260 }}>{hint.text}</div>}
    </>
  );
}
