import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { dateTimeVi } from "../format";

type Row = { id: number; ts: string; actor: string; action: string; entity: string; entity_id: string | null; detail: Record<string, unknown> | null };

const ACTION: Record<string, string> = {
  PROPOSAL_CREATED: "Tạo đề xuất",
  PROPOSAL_EDITED: "Sửa đề xuất",
  PROPOSAL_APPROVED: "Duyệt",
  PROPOSAL_EXECUTED: "Thực hiện xong",
  PROPOSAL_FAILED: "Thực hiện lỗi",
  PROPOSAL_REJECTED: "Từ chối",
  PROPOSAL_EXPIRED: "Hết hiệu lực",
  PO_RECEIVED: "Nhận hàng",
  RECEIVE_SHORT_DATED: "Cảnh báo hàng giao cận date",
};

export default function Audit() {
  const q = useQuery({ queryKey: ["audit"], queryFn: () => api<Row[]>("/audit?limit=300") });
  return (
    <>
      <div className="page-head">
        <div><h1>Nhật ký</h1><div className="muted">Mọi đề xuất, quyết định và thao tác có tác dụng thật đều được ghi lại: ai làm, lúc nào, nội dung gì.</div></div>
      </div>
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Thời gian</th><th>Người/hệ thống</th><th>Hành động</th><th>Đối tượng</th><th>Chi tiết</th></tr></thead>
            <tbody>
              {q.data?.map((r) => (
                <tr key={r.id}>
                  <td className="small">{dateTimeVi(r.ts)}</td>
                  <td>{r.actor === "agent" ? "Ops Chest (chat)" : r.actor === "job" ? "Ops Chest (quét)" : r.actor}</td>
                  <td>{ACTION[r.action] ?? r.action}</td>
                  <td>{r.entity} #{r.entity_id}</td>
                  <td className="small muted" style={{ maxWidth: 480, wordBreak: "break-word" }}>{r.detail ? JSON.stringify(r.detail).slice(0, 220) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {q.data?.length === 0 && <p className="muted">Chưa có hoạt động nào.</p>}
        </div>
      </div>
    </>
  );
}
