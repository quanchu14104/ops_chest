import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, getUser, type Proposal } from "../api";
import ProposalCard from "../components/ProposalCard";
import { TYPE_LABEL } from "../format";

const TABS: [string, string][] = [
  ["PENDING,FAILED", "Chờ duyệt"],
  ["EXECUTED", "Đã thực hiện"],
  ["REJECTED,EXPIRED", "Từ chối / hết hiệu lực"],
];

export default function Approvals() {
  const [tab, setTab] = useState(TABS[0][0]);
  const [type, setType] = useState("");
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["proposals", tab, type],
    queryFn: () => api<Proposal[]>(`/proposals?status=${tab}${type ? `&type=${type}` : ""}`),
  });
  const scan = useMutation({
    mutationFn: () => api("/proposals/generate", { method: "POST", body: { kind: "morning" } }),
    onSuccess: () => qc.invalidateQueries(),
  });
  const isManager = getUser()?.role === "manager";
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Hộp duyệt</h1>
          <div className="muted">
            {isManager ? "Xem lý do, sửa số lượng nếu cần, rồi duyệt hoặc từ chối. Không có gì được thực hiện trước khi anh/chị duyệt."
              : "Chỉ Store Manager được duyệt. Bạn có thể xem đề xuất."}
          </div>
        </div>
        <button onClick={() => scan.mutate()} disabled={scan.isPending}>
          {scan.isPending ? "Đang quét…" : "Quét & tạo đề xuất ngay"}
        </button>
      </div>
      <div className="row" style={{ marginBottom: 16 }}>
        <div className="seg" role="tablist">
          {TABS.map(([k, l]) => (
            <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)} role="tab" aria-selected={tab === k}>
              {l}
            </button>
          ))}
        </div>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Loại đề xuất">
          <option value="">Mọi loại</option>
          {Object.entries(TYPE_LABEL).map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
      </div>
      {q.isLoading && <p className="muted">Đang tải…</p>}
      {q.error && <div className="alert error">{(q.error as Error).message}</div>}
      {q.data?.length === 0 && <p className="muted">Không có đề xuất nào.</p>}
      <div className="grid">
        {q.data?.map((p) => (
          <ProposalCard key={`${p.id}-${p.status}`} p={p} compact={tab !== TABS[0][0]} />
        ))}
      </div>
    </>
  );
}
