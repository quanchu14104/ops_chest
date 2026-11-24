import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, getUser, type Proposal } from "../api";
import { byUrgency } from "../components/InboxPanel";
import ProposalCard from "../components/ProposalCard";
import EmptyState, { Skeleton } from "../components/ui/EmptyState";
import PageHeader from "../components/ui/PageHeader";
import Segmented from "../components/ui/Segmented";
import { Chips } from "../components/ui/controls";
import { TYPE_LABEL, compact, money } from "../format";

type Tab = "PENDING,FAILED" | "EXECUTED" | "REJECTED,EXPIRED,SUPERSEDED";
const TABS: { value: Tab; label: string }[] = [
  { value: "PENDING,FAILED", label: "Chờ duyệt" },
  { value: "EXECUTED", label: "Đã thực hiện" },
  { value: "REJECTED,EXPIRED,SUPERSEDED", label: "Từ chối / hết hiệu lực" },
];

export default function Approvals() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>("PENDING,FAILED");
  const type = params.get("type") ?? "";
  const setType = (t: string) => {
    const next = new URLSearchParams(params);
    if (t) next.set("type", t);
    else next.delete("type");
    setParams(next, { replace: true });
  };
  // ?open=<id> (từ trang Tổng quan) mở sẵn đúng đề xuất đó
  const [openId, setOpenId] = useState<number | null | undefined>(() => Number(params.get("open")) || undefined);
  const qc = useQueryClient();
  // Lấy cả tab rồi lọc loại ở trình duyệt, để chip loại hiện được số đếm
  const q = useQuery({
    queryKey: ["proposals", tab],
    queryFn: () => api<Proposal[]>(`/proposals?status=${tab}`),
  });
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<{ today: string }>("/meta") });
  const scan = useMutation({
    mutationFn: () => api("/proposals/generate", { method: "POST", body: { kind: "morning" } }),
    onSuccess: () => qc.invalidateQueries(),
  });
  const isManager = getUser()?.role === "manager";
  const pendingTab = tab === "PENDING,FAILED";
  const all = q.data ?? [];
  const typeCounts = all.reduce<Record<string, number>>((acc, p) => ({ ...acc, [p.type]: (acc[p.type] ?? 0) + 1 }), {});
  const filtered = type ? all.filter((p) => p.type === type) : all;
  const list = pendingTab ? [...filtered].sort(byUrgency) : filtered;
  // Mỗi lúc chỉ mở một thẻ; tab chờ duyệt mở sẵn thẻ gấp nhất
  const current = openId === undefined ? (pendingTab ? list[0]?.id ?? null : null) : openId;

  const poTotal = list.filter((p) => p.type === "PURCHASE_ORDER").reduce((s, p) => s + (p.est_value ?? 0), 0);
  const today = meta.data?.today?.slice(0, 10);
  const expToday = today ? list.filter((p) => p.expires_at && p.expires_at.slice(0, 10) <= today).length : 0;

  return (
    <>
      <PageHeader
        title="Hộp duyệt"
        desc={isManager ? "Xem lý do, sửa số lượng nếu cần, rồi duyệt hoặc từ chối. Không có gì được thực hiện trước khi anh/chị duyệt."
          : "Chỉ Store Manager được duyệt. Bạn có thể xem đề xuất."}
        actions={isManager && (
          <button onClick={() => scan.mutate()} disabled={scan.isPending} title="Chạy lại phần quét buổi sáng: đặt hàng, cận date, ghi hủy">
            {scan.isPending ? "Đang quét…" : "Quét & tạo đề xuất ngay"}
          </button>
        )}
      />
      <div className="row mb-3">
        <Segmented<Tab> label="Trạng thái đề xuất" value={tab} onChange={(t) => { setTab(t); setOpenId(undefined); }} options={TABS} />
        {pendingTab && list.length > 0 && (
          <span className="inbox-summary" role="status" title="Xếp theo hạn hiệu lực, rồi giá trị">
            {poTotal > 0 && <span title={money(poTotal)}>Đặt hàng <b>{compact(poTotal)}</b></span>}
            {expToday > 0 && <span className="badge warn">{expToday} hết hạn hôm nay</span>}
          </span>
        )}
      </div>
      {all.length > 0 && (
        <div className="mb-4">
          <Chips label="Loại đề xuất" value={type} onChange={(t) => { setType(t); setOpenId(undefined); }} options={[
            { value: "", label: "Tất cả", count: all.length },
            ...Object.entries(typeCounts).map(([k, n]) => ({ value: k, label: TYPE_LABEL[k] ?? k, count: n })),
          ]} />
        </div>
      )}
      {q.isLoading && <div className="card"><Skeleton rows={5} /></div>}
      {q.error && <div className="alert error">{(q.error as Error).message}</div>}
      {q.data && list.length === 0 && (
        <div className="card">
          <EmptyState title={pendingTab ? "Không có đề xuất nào chờ duyệt" : "Chưa có đề xuất nào"}>
            {pendingTab ? "Ops Chest quét tự động lúc 06:30 và 17:00. Đề xuất mới sẽ hiện ở đây." : "Đổi bộ lọc loại đề xuất để xem thêm."}
          </EmptyState>
        </div>
      )}
      <div className="grid">
        {list.map((p) => (
          <ProposalCard key={`${p.id}-${p.status}`} p={p} compact expanded={current === p.id}
            onToggle={() => setOpenId(current === p.id ? null : p.id)} />
        ))}
      </div>
    </>
  );
}
