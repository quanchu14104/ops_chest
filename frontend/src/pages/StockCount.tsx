import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type CountLine, type DateCheckLine } from "../api";
import DateCheckForm from "../components/DateCheckForm";
import StockCountForm from "../components/StockCountForm";
import { Skeleton } from "../components/ui/EmptyState";
import PageHeader from "../components/ui/PageHeader";
import Segmented from "../components/ui/Segmented";
import { Chips, InfoTip } from "../components/ui/controls";

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
      <div className="row mb-3">
        <Chips label="Nhóm vòng đời" value={cls} onChange={(v) => setCls(v)} options={[
          { value: "", label: "Lịch hôm nay" },
          ...Object.entries(CLASS_LABEL).map(([k, v]) => ({ value: k, label: <span title={v}>{v.split(" (")[0]}</span> })),
        ]} />
      </div>
      {q.error && <div className="alert error">{(q.error as Error).message}</div>}
      {q.isLoading ? <div className="card"><Skeleton rows={6} /></div> : (
        <DateCheckForm key={cls} lines={lines} title="Phiếu kiểm date"
          note="Đếm số lượng theo từng HSD in trên bao bì. Kệ có hàng in HSD mà phiếu chưa có thì bấm “Có HSD khác trên kệ” để thêm dòng đếm riêng (không sửa hạn của lô trên sổ). Mặt hàng đã nhập số thì HSD để trống được tính là 0." />
      )}
    </>
  );
}

const DUE = "__due__";

function SkuCount() {
  const q = useQuery({ queryKey: ["count-sheet"], queryFn: () => api<CountLine[]>("/stock-count/sheet") });
  const due = useQuery({ queryKey: ["count-due"], queryFn: () => api<(CountLine & { reason: string })[]>("/stock-count/sheet?due=true") });
  const categories = useMemo(() => [...new Set((q.data ?? []).map((l) => l.category))], [q.data]);
  const [category, setCategory] = useState(DUE);
  const active = category || categories[0] || "";
  const lines = active === DUE ? (due.data ?? []) : (q.data ?? []).filter((l) => l.category === active);
  return (
    <>
      <div className="row mb-3">
        <select value={active} onChange={(e) => setCategory(e.target.value)} aria-label="Nhóm hàng">
          <option value={DUE}>Đến lịch đếm ({due.data?.length ?? "…"})</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      {q.error && <div className="alert error">{(q.error as Error).message}</div>}
      {q.isLoading || due.isLoading ? <div className="card"><Skeleton rows={6} /></div> : (
        <StockCountForm key={active} lines={lines} title={active === DUE ? "Phiếu đếm: đến lịch và nghi tồn ảo" : `Phiếu đếm: ${active}`}
          note={active === DUE ? "Nghi tồn ảo: mặt hàng bán đều nhưng nhiều ngày không bán trong khi sổ còn hàng (kệ có thể đã trống). Dòng để trống là chưa đếm." : "Dòng để trống là chưa đếm."} />
      )}
    </>
  );
}

type Tab = "date" | "sku";

export default function StockCount() {
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "sku" ? "sku" : "date";
  const setTab = (t: Tab) => setParams(t === "sku" ? { tab: "sku" } : {}, { replace: true });
  return (
    <>
      <PageHeader title="Kiểm kê"
        desc="Phiếu cố ý không hiện số trên sổ để người đếm không đếm cho khớp. Chênh lệch chỉ được ghi sau khi Store Manager duyệt." />
      <div className="row mb-4">
        <Segmented<Tab> label="Loại phiếu" value={tab} onChange={setTab} options={[
          { value: "date", label: "Kiểm date" },
          { value: "sku", label: "Kiểm kê SKU" },
        ]} />
        <InfoTip text={tab === "date" ? "Đếm theo từng HSD để sổ theo lô khớp với kệ." : "Dùng cho hàng còn xa hạn: đếm tổng theo mặt hàng."} />
      </div>
      {tab === "date" ? <DateCheck /> : <SkuCount />}
    </>
  );
}
