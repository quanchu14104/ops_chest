import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, type CountLine } from "../api";
import StockCountForm from "../components/StockCountForm";

export default function StockCount() {
  const q = useQuery({ queryKey: ["count-sheet"], queryFn: () => api<CountLine[]>("/stock-count/sheet") });
  const categories = useMemo(() => [...new Set((q.data ?? []).map((l) => l.category))], [q.data]);
  const [category, setCategory] = useState("");
  const active = category || categories[0] || "";
  const lines = (q.data ?? []).filter((l) => l.category === active);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Kiểm kê</h1>
          <div className="muted">Đếm thực tế từng nhóm hàng. Phiếu cố ý không hiện số trên sổ để người đếm không đếm cho khớp. Chênh lệch chỉ được ghi sau khi Store Manager duyệt.</div>
        </div>
        <div className="row">
          <select value={active} onChange={(e) => setCategory(e.target.value)} aria-label="Nhóm hàng">
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>
      {q.error && <div className="alert error">{(q.error as Error).message}</div>}
      {q.isLoading ? <p className="muted">Đang tải…</p> : <StockCountForm key={active} lines={lines} title={`Phiếu đếm: ${active}`} note="Dòng để trống là chưa đếm." />}
    </>
  );
}
