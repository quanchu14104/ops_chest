import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { api, type Proposal } from "../api";
import { WASTE_REASON_LABEL, dateVi, money, num, optionLabel } from "../format";
import ProposalCard from "./ProposalCard";
import EmptyState, { Skeleton } from "./ui/EmptyState";
import { Chips, Icon, Stepper, Switch } from "./ui/controls";

type Opt = { action: string; label: string; delta_vs_keep: number; feasible: boolean; note: string };
type LotRow = {
  lot_id: number; sku: string; name: string; category: string; qty: number; expiry_date: string; sell_by: string; days_left: number;
  bucket: string; status: string; expected_sold: number; expected_waste: number; value_at_risk: number; supplier: string;
  markdown_pct: number; evening_markdown_pct?: number; options: Opt[];
};
type Resp = { as_of: string; lots: LotRow[]; total_value_at_risk: number };

// Lô cận date: chọn lô rồi bấm tạo đề xuất. Dùng chung cho trang "Hàng cận date" và thẻ trong chat.
// Đề xuất vừa tạo hiện ngay bên dưới để Store Manager duyệt tại chỗ, không phải chuyển trang.
export default function ExpiringLots({ initialDays = 7, showKpis = true }: { initialDays?: number; showKpis?: boolean }) {
  const [days, setDays] = useState(initialDays);
  const [onlyRisk, setOnlyRisk] = useState(true);
  const [sel, setSel] = useState<Record<number, boolean>>({});
  const [openLot, setOpenLot] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [created, setCreated] = useState<Proposal[]>([]);
  const [writeOffOpen, setWriteOffOpen] = useState(false);
  const [keepWarn, setKeepWarn] = useState(false);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["expiring", days], queryFn: () => api<Resp>(`/inventory/expiring?days=${days}`) });

  const rows = (q.data?.lots ?? []).filter((l) => !onlyRisk || l.status !== "OK");
  const selectedIds = Object.keys(sel).filter((k) => sel[Number(k)]).map(Number);
  const selectedRows = rows.filter((r) => selectedIds.includes(r.lot_id));
  const expiredRows = rows.filter((r) => r.status === "EXPIRED");
  // Tổng cộng từ đúng các dòng đang hiện, để số lô và số tiền luôn cùng một tập (L-08)
  const shownValue = rows.reduce((s, r) => s + r.value_at_risk, 0);
  const keepBest = selectedRows.filter((r) => r.options[0]?.action === "KEEP");

  const done = (ps: Proposal[]) => {
    setErr(null);
    setCreated((c) => [...ps, ...c]);
    setSel({});
    setWriteOffOpen(false);
    setKeepWarn(false);
    qc.invalidateQueries();
  };
  const create = useMutation({
    mutationFn: (type: string) =>
      api<Proposal[]>("/proposals/create", { method: "POST", body: { type, lot_ids: type === "DISPOSE" ? null : selectedIds } }),
    onSuccess: done,
    onError: (e: Error) => setErr(e.message),
  });
  const [woQty, setWoQty] = useState<Record<number, string>>({});
  const [woReason, setWoReason] = useState("DAMAGED");
  const [woNote, setWoNote] = useState("");
  const writeOff = useMutation({
    mutationFn: () =>
      api<Proposal>("/write-offs", {
        method: "POST",
        body: { note: woNote || null, lines: selectedIds.map((id) => ({ lot_id: id, qty: Number(woQty[id] || 0), reason: woReason })) },
      }),
    onSuccess: (p) => {
      setWoQty({});
      setWoNote("");
      done([p]);
    },
    onError: (e: Error) => setErr(e.message),
  });
  // Lô mà phương án tốt nhất là giữ giá: giảm giá sẽ thu về ít hơn, hỏi lại trước khi tạo (L-06)
  const proposeMarkdown = () => (keepBest.length && !keepWarn ? setKeepWarn(true) : create.mutate("MARKDOWN"));

  return (
    <div className="lots-panel">
      <div className="row mb-3">
        <Chips label="Khoảng ngày" value={String(days)} onChange={(v) => v && setDays(Number(v))}
          options={[1, 3, 7, 14, 30].map((d) => ({ value: String(d), label: `${d} ngày` }))} />
        <Switch checked={onlyRisk} onChange={setOnlyRisk} label="Chỉ lô rủi ro" />
      </div>

      {showKpis && (
        <div className="grid kpis mb-3">
          <div className="card kpi">
            <div className="label">Lô rủi ro · {days} ngày</div>
            <div className="value">{q.data ? num(rows.filter((r) => r.status !== "OK").length) : "…"}</div>
          </div>
          <div className="card kpi">
            <div className="label has-hint" title={`Cộng từ ${rows.length} lô đang hiện`}>Giá vốn rủi ro</div>
            <div className="value">{q.data ? money(shownValue) : "…"}</div>
          </div>
          <div className={`card kpi ${expiredRows.length ? "kpi-alert" : ""}`}>
            <div className="label">Quá ngày bán cuối</div>
            <div className="value">{num(expiredRows.length)}</div>
          </div>
        </div>
      )}
      {expiredRows.length > 0 && (
        <div className="row mb-3">
          <button className="danger sm" disabled={create.isPending} onClick={() => create.mutate("DISPOSE")}>
            <Icon name="trash" /> Đề xuất ghi hủy {expiredRows.length} lô quá hạn
          </button>
        </div>
      )}

      <div className="card">
        {q.isLoading ? <Skeleton rows={5} /> : rows.length === 0 ? (
          <EmptyState title={`Không có lô rủi ro trong ${days} ngày tới`} />
        ) : (
          <div className="table-wrap">
            <table className="stack-sm lots">
              <thead>
                <tr>
                  <th aria-label="Chọn" />
                  <th>Hàng</th>
                  <th>Hạn</th>
                  <th className="num">Tồn</th>
                  <th className="num" title="Số dự kiến phải hủy nếu giữ giá">Dự kiến hủy</th>
                  <th className="num">Giá vốn rủi ro</th>
                  <th>Nên làm</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((l) => {
                  const best = l.options[0];
                  const isOpen = openLot === l.lot_id;
                  return (
                    <Fragment key={l.lot_id}>
                      <tr className={sel[l.lot_id] ? "row-selected" : undefined}>
                        <td data-label="Chọn">
                          <input type="checkbox" checked={!!sel[l.lot_id]} disabled={l.status === "EXPIRED"} aria-label={`Chọn lô ${l.lot_id} ${l.name}`}
                            onChange={(e) => setSel({ ...sel, [l.lot_id]: e.target.checked })} />
                        </td>
                        <td className="cell-main" title={`${l.sku} · lô #${l.lot_id} · dự kiến bán ${num(l.expected_sold, 1)}`}>
                          {l.name}
                          <span className="badges">
                            {l.markdown_pct > 0 && <span className="badge">−{Math.round(l.markdown_pct * 100)}%</span>}
                            {(l.evening_markdown_pct ?? 0) > l.markdown_pct && <span className="badge" title="Giảm cuối ngày">−{Math.round((l.evening_markdown_pct ?? 0) * 100)}% tối</span>}
                          </span>
                        </td>
                        <td data-label="Hạn" title={`HSD ${dateVi(l.expiry_date)}${l.sell_by !== l.expiry_date ? ` · bán đến ${dateVi(l.sell_by)}` : ""}`}>
                          <span className={`badge ${l.days_left <= 0 ? "bad" : l.days_left <= 2 ? "warn" : ""}`}>{l.bucket}</span>
                        </td>
                        <td data-label="Tồn" className="num">{num(l.qty)}</td>
                        <td data-label="Dự kiến hủy" className="num">{num(l.expected_waste, 1)}</td>
                        <td data-label="Giá vốn rủi ro" className="num">{money(l.value_at_risk)}</td>
                        <td data-label="Phương án">
                          {l.status === "EXPIRED" ? <span className="badge bad">Cần rút kệ</span>
                            : best ? (
                              <button className="sm opt-toggle" onClick={() => setOpenLot(isOpen ? null : l.lot_id)} aria-expanded={isOpen}
                                title={l.options.length > 1 ? "Xem mọi phương án" : best.note}>
                                {optionLabel(best.label).replace(/^Giảm giá /, "Giảm ")} <b className="gain">+{money(best.delta_vs_keep)}</b>
                                {l.options.length > 1 && <Icon name={isOpen ? "down" : "chevron"} />}
                              </button>
                            ) : <span className="muted">Giữ nguyên</span>}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="opt-row">
                          <td colSpan={7}>
                            <div className="opt-chips">
                              {l.options.map((o, i) => (
                                <span key={`${o.label}-${i}`} className={`opt-chip ${i === 0 ? "best" : ""} ${o.feasible ? "" : "off"}`} title={o.note}>
                                  {optionLabel(o.label).replace(/^Giảm giá /, "Giảm ")}
                                  <b className={o.delta_vs_keep < 0 ? "neg" : "gain"}>{o.delta_vs_keep >= 0 ? "+" : ""}{money(o.delta_vs_keep)}</b>
                                </span>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selectedIds.length > 0 && (
        <div className="sticky-bar mt-3" role="region" aria-label="Thao tác với lô đã chọn">
          <span className="sel-count"><b>{selectedIds.length}</b> lô · {money(selectedRows.reduce((s, r) => s + r.value_at_risk, 0))}</span>
          <span className="spacer" />
          <button className="primary" disabled={create.isPending} onClick={proposeMarkdown}><Icon name="tag" /> Giảm giá</button>
          <button disabled={create.isPending} onClick={() => create.mutate("RETURN")}><Icon name="truck" /> Trả NCC</button>
          <button className={writeOffOpen ? "danger-solid" : "danger"} onClick={() => setWriteOffOpen((o) => !o)} aria-expanded={writeOffOpen}><Icon name="trash" /> Báo hủy</button>
          <button className="icon ghost" aria-label="Bỏ chọn" title="Bỏ chọn" onClick={() => { setSel({}); setKeepWarn(false); setWriteOffOpen(false); }}><Icon name="x" /></button>
          {keepWarn && (
            <div className="alert warn sticky-panel row">
              <span className="grow" title={keepBest.map((r) => r.name).join(", ")}><b>{keepBest.length} lô</b> nên giữ giá: giảm sẽ thu về ít hơn</span>
              <button className="sm" onClick={() => { setSel({ ...sel, ...Object.fromEntries(keepBest.map((r) => [r.lot_id, false])) }); setKeepWarn(false); }}>Bỏ các lô đó</button>
              <button className="sm" onClick={() => create.mutate("MARKDOWN")}>Vẫn giảm</button>
            </div>
          )}
          {writeOffOpen && (
            <div className="sticky-panel stack-sm-gap">
              {selectedRows.map((l) => (
                <div className="row" key={l.lot_id}>
                  <span className="grow" title={`Lô #${l.lot_id}`}>{l.name}</span>
                  <Stepper value={woQty[l.lot_id] === undefined || woQty[l.lot_id] === "" ? "" : Number(woQty[l.lot_id])} max={l.qty} placeholder="0"
                    label={`Số lượng hủy lô ${l.lot_id}`} onChange={(v) => setWoQty({ ...woQty, [l.lot_id]: v === "" ? "" : String(v) })} />
                </div>
              ))}
              <Chips label="Lý do hủy" value={woReason} onChange={(v) => v && setWoReason(v)}
                options={Object.entries(WASTE_REASON_LABEL).filter(([k]) => k !== "EXPIRED").map(([k, v]) => ({ value: k, label: v }))} />
              <div className="row">
                <input className="grow" placeholder="Ghi chú" value={woNote} onChange={(e) => setWoNote(e.target.value)} aria-label="Ghi chú báo hủy" />
                <button className="danger-solid" disabled={writeOff.isPending || selectedIds.some((id) => !Number(woQty[id]))} onClick={() => writeOff.mutate()}>
                  <Icon name="trash" /> Tạo đề xuất báo hủy
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {err && <div className="alert error mt-3">{err}</div>}
      {created.length > 0 && (
        <div className="stack mt-3" aria-label="Đề xuất vừa tạo">
          {created.map((p) => <ProposalCard key={`${p.id}-${p.status}`} p={p} compact />)}
        </div>
      )}
    </div>
  );
}
