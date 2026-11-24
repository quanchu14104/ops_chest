import { useQuery } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import EmptyState, { Skeleton } from "../components/ui/EmptyState";
import PageHeader from "../components/ui/PageHeader";
import { TYPE_LABEL, actorLabel, compact, dateTimeVi, dateVi, num } from "../format";

type Row = { id: number; ts: string; actor: string; action: string; entity: string; entity_id: string | null; detail: Record<string, unknown> | null };

const ACTION: Record<string, string> = {
  PROPOSAL_CREATED: "Tạo đề xuất",
  PROPOSAL_EDITED: "Sửa đề xuất",
  PROPOSAL_APPROVED: "Duyệt",
  PROPOSAL_EXECUTED: "Thực hiện xong",
  PROPOSAL_FAILED: "Thực hiện lỗi",
  PROPOSAL_REJECTED: "Từ chối",
  PROPOSAL_EXPIRED: "Hết hiệu lực",
  PROPOSAL_SUPERSEDED: "Thay bằng bản sửa",
  PROPOSAL_REVISED: "Tạo bản sửa",
  PO_RECEIVED: "Nhận hàng",
  RECEIVE_SHORT_DATED: "Cảnh báo hàng giao cận date",
  AGENT_TURN: "Lượt chat",
  LOTS_PULLED: "Rút kệ",
  SIM_ADVANCED: "Tua ngày (demo)",
};

const ENTITY: Record<string, string> = {
  proposal: "Đề xuất", chat_session: "Hội thoại", purchase_order: "Đơn hàng", lot: "Lô", clock: "Ngày nghiệp vụ",
};

type D = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function changeText(c: unknown): string {
  if (typeof c === "string") return c;
  const x = c as { field?: string; from?: unknown; to?: unknown };
  return x && x.field ? `${x.field}: ${String(x.from)} → ${String(x.to)}` : JSON.stringify(c);
}

// Diễn giải `detail` thành một câu đọc được; JSON gốc vẫn xem được trong "Chi tiết kỹ thuật"
export function auditSummary(r: Row): string {
  const d = (r.detail ?? {}) as D;
  switch (r.action) {
    case "AGENT_TURN": {
      const parts = [`${num(d.rounds)} vòng`, `${(d.tools ?? []).length} lần tra dữ liệu`];
      if (d.usage_reported) parts.push(`${compact(d.prompt_tokens ?? 0)} token vào · ${num(d.completion_tokens)} ra`);
      if (d.seconds != null) parts.push(`${num(d.seconds, 1)} giây`);
      if (d.tool_errors) parts.push(`${d.tool_errors} lần tra lỗi`);
      if (d.outcome && d.outcome !== "ok") parts.push(`kết quả: ${d.outcome}`);
      return parts.join(" · ");
    }
    case "PROPOSAL_CREATED":
      return [TYPE_LABEL[d.type] ?? d.type, d.title].filter(Boolean).join(": ");
    case "PROPOSAL_REVISED":
      return `Bản sửa của #${d.from}${d.changes?.length ? `: ${d.changes.map(changeText).join("; ")}` : ""}`;
    case "PROPOSAL_SUPERSEDED":
    case "PROPOSAL_EDITED":
      return (d.changes ?? []).map(changeText).join("; ") || "Đã sửa";
    case "PROPOSAL_APPROVED":
      return d.note ? `Ghi chú: "${d.note}"` : "Duyệt không ghi chú";
    case "PROPOSAL_REJECTED":
      return d.reason ? `Lý do: ${d.reason}` : "";
    case "PROPOSAL_FAILED":
      return d.error ? `Lỗi: ${d.error}` : "";
    case "PROPOSAL_EXPIRED":
      return "Hết hạn hiệu lực trước khi được duyệt";
    case "PROPOSAL_EXECUTED":
      if (d.code && d.email_to) return `${d.code} gửi tới ${d.email_to}`;
      if (d.lots_marked_down) return `Áp giá giảm cho ${d.lots_marked_down.length} lô`;
      if (d.lots_disposed != null) return `Ghi hủy ${d.lots_disposed} lô`;
      return d.note ?? d.instruction ?? "";
    case "PO_RECEIVED":
      return `${d.code ?? ""}: nhận ${(d.lots ?? []).length} lô`;
    case "LOTS_PULLED": {
      const lots = (d.lots ?? []) as { pulled_qty?: number }[];
      return `Gỡ ${lots.length} lô khỏi kệ, ${num(lots.reduce((s, l) => s + (l.pulled_qty ?? 0), 0))} đơn vị`;
    }
    case "SIM_ADVANCED":
      return `Tua ${d.days} ngày từ ${dateVi(d.from)}`;
    default: {
      const flat = Object.entries(d).filter(([, v]) => v != null && typeof v !== "object").slice(0, 3);
      return flat.map(([k, v]) => `${k}: ${String(v)}`).join(" · ");
    }
  }
}

function EntityCell({ r }: { r: Row }) {
  // Một số bản ghi (vd rút kệ nhiều lô) có mã đối tượng là cả danh sách: rút gọn, mã đầy đủ ở tooltip
  const id = r.entity_id && r.entity_id.length > 14 ? `${r.entity_id.slice(0, 12)}…` : r.entity_id;
  const label = `${ENTITY[r.entity] ?? r.entity}${id ? ` #${id}` : ""}`;
  if (id !== r.entity_id) return <span title={r.entity_id ?? undefined}>{label}</span>;
  if (r.entity === "chat_session" && r.entity_id) return <Link to={`/chat/${r.entity_id}`}>{label}</Link>;
  if (r.entity === "purchase_order") return <Link to="/orders">{label}</Link>;
  return <>{label}</>;
}

export default function Audit() {
  const q = useQuery({ queryKey: ["audit"], queryFn: () => api<Row[]>("/audit?limit=300") });
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [entity, setEntity] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  // Sắp theo thứ tự ghi sổ (id), vì giờ ghi lẫn giờ demo và giờ thật (L-14)
  const all = useMemo(() => [...(q.data ?? [])].sort((a, b) => b.id - a.id), [q.data]);
  const opts = (f: (r: Row) => string) => [...new Set(all.map(f))].sort();
  const rows = all.filter((r) => (!actor || actorLabel(r.actor) === actor) && (!action || r.action === action) && (!entity || r.entity === entity));

  return (
    <>
      <PageHeader title="Nhật ký" desc="Mọi đề xuất, quyết định và thao tác có tác dụng thật đều được ghi lại: ai làm, lúc nào, nội dung gì." />
      <div className="card">
        <div className="row filters mb-3">
          <select value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Lọc theo người làm">
            <option value="">Mọi người / hệ thống</option>
            {opts((r) => actorLabel(r.actor)).map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Lọc theo hành động">
            <option value="">Mọi hành động</option>
            {opts((r) => r.action).map((a) => <option key={a} value={a}>{ACTION[a] ?? a}</option>)}
          </select>
          <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Lọc theo đối tượng">
            <option value="">Mọi đối tượng</option>
            {opts((r) => r.entity).map((a) => <option key={a} value={a}>{ENTITY[a] ?? a}</option>)}
          </select>
          <span className="spacer" />
          {q.data && <span className="small muted">{rows.length} / {all.length} dòng gần nhất</span>}
        </div>
        {q.isLoading && <Skeleton rows={8} />}
        {q.data && rows.length === 0 && <EmptyState title="Không có hoạt động nào khớp bộ lọc" />}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table className="stack-sm audit">
              <thead><tr><th>Thời gian</th><th>Người / hệ thống</th><th>Hành động</th><th>Đối tượng</th><th>Nội dung</th><th aria-label="Chi tiết" /></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.id}>
                    <tr>
                      <td data-label="Thời gian" className="small nowrap">{dateTimeVi(r.ts)}</td>
                      <td data-label="Người làm">{actorLabel(r.actor)}</td>
                      <td data-label="Hành động" className="nowrap">{ACTION[r.action] ?? r.action}</td>
                      <td data-label="Đối tượng" className="nowrap"><EntityCell r={r} /></td>
                      <td className="cell-main audit-summary">{auditSummary(r)}</td>
                      <td data-label="">
                        {r.detail && (
                          <button className="sm ghost" onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id}>
                            {open === r.id ? "Ẩn" : "Chi tiết"}
                          </button>
                        )}
                      </td>
                    </tr>
                    {open === r.id && (
                      <tr className="opt-row">
                        <td colSpan={6}>
                          <div className="small muted mb-3">Chi tiết kỹ thuật (bản ghi gốc #{r.id})</div>
                          <pre className="json">{JSON.stringify(r.detail, null, 2)}</pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
