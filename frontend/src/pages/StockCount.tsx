import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, type CountLine, type DateCheckLine } from "../api";
import DateCheckForm from "../components/DateCheckForm";
import StockCountForm from "../components/StockCountForm";

const CLASS_LABEL: Record<string, string> = { FRESH: "Hàng tươi (mỗi ngày)", SHORT: "Hàng ngắn ngày (thứ Hai)", LONG: "Hàng dài ngày (ngày 1 hằng tháng)" };

function DateCheck() {
  const [cls, setCls] = useState("");
  const q = useQuery({
    queryKey: ["date-check-sheet", cls],
    queryFn: () => api<{ due_today: string[]; lines: DateCheckLine[] }>(`/date-check/sheet${cls ? `?freshness=${cls}` : ""}`),
  });
  const due = q.data?.due_today ?? [];
  const lines = (q.data?.lines ?? []).filter((l) => (cls ? true : due.includes(l.freshness_class)));
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <select value={cls} onChange={(e) => setCls(e.target.value)} aria-label="Nhóm vòng đời">
          <option value="">Theo lịch hôm nay ({due.map((c) => CLASS_LABEL[c]?.split(" (")[0]).join(", ") || "…"})</option>
          {Object.entries(CLASS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {q.error && <div className="alert error">{(q.error as Error).message}</div>}
      {q.isLoading ? <p className="muted">Đang tải…</p> : (
        <DateCheckForm key={cls} lines={lines} title="Phiếu kiểm date"
          note="Đếm số lượng theo từng HSD in trên bao bì. Gặp HSD phiếu chưa có thì bấm “Thêm HSD”. Mặt hàng đã nhập số thì HSD để trống được tính là 0." />
      )}
    </>
  );
}

function SkuCount() {
  const q = useQuery({ queryKey: ["count-sheet"], queryFn: () => api<CountLine[]>("/stock-count/sheet") });
  const categories = useMemo(() => [...new Set((q.data ?? []).map((l) => l.category))], [q.data]);
  const [category, setCategory] = useState("");
  const active = category || categories[0] || "";
  const lines = (q.data ?? []).filter((l) => l.category === active);
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <select value={active} onChange={(e) => setCategory(e.target.value)} aria-label="Nhóm hàng">
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      {q.error && <div className="alert error">{(q.error as Error).message}</div>}
      {q.isLoading ? <p className="muted">Đang tải…</p> : <StockCountForm key={active} lines={lines} title={`Phiếu đếm: ${active}`} note="Dòng để trống là chưa đếm." />}
    </>
  );
}

export default function StockCount() {
  const [tab, setTab] = useState<"date" | "sku">("date");
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Kiểm kê</h1>
          <div className="muted">
            Phiếu cố ý không hiện số trên sổ để người đếm không đếm cho khớp. Chênh lệch chỉ được ghi sau khi Store Manager duyệt.
            Kiểm date đếm theo từng HSD để sổ theo lô khớp với kệ; kiểm kê theo SKU dùng cho hàng còn xa hạn.
          </div>
        </div>
        <div className="seg">
          <button className={tab === "date" ? "on" : ""} onClick={() => setTab("date")}>Kiểm date theo HSD</button>
          <button className={tab === "sku" ? "on" : ""} onClick={() => setTab("sku")}>Kiểm kê theo SKU</button>
        </div>
      </div>
      {tab === "date" ? <DateCheck /> : <SkuCount />}
    </>
  );
}
