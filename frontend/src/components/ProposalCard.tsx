import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, getUser, type Proposal } from "../api";
import { STATUS_LABEL, TYPE_LABEL, dateTimeVi, dateVi, money, num, pct } from "../format";

// "Hỏi lại": đưa ngữ cảnh đề xuất vào ô chat. Chat đang mở (trang Trợ lý) nghe sự kiện này và điền sẵn;
// nếu không ai nhận (vd đang ở Hộp duyệt) thì chuyển sang /chat kèm bản nháp qua router state.
export const ASK_EVENT = "opschest:ask";
export type AskDetail = { text: string; handled: boolean };

type Edits = { lines?: { product_id: number; qty: number }[]; items?: Record<string, unknown>[]; note?: string };

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge st-${status}`}>
      <span className="dot" />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export default function ProposalCard({ p: initial, compact = false }: { p: Proposal; compact?: boolean }) {
  const [p, setP] = useState(initial);
  const qc = useQueryClient();
  const user = getUser();
  const nav = useNavigate();
  const canDecide = user?.role === "manager" && (p.status === "PENDING" || p.status === "FAILED");
  const [open, setOpen] = useState(!compact);
  const [qty, setQty] = useState<Record<string, number>>({});
  const [md, setMd] = useState<Record<string, number>>({});
  const [excluded, setExcluded] = useState<Record<string, boolean>>({});
  const [note, setNote] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const edits = useMemo<Edits | undefined>(() => {
    const e: Edits = {};
    if (p.type === "PURCHASE_ORDER") {
      const lines = Object.entries(qty).map(([pid, q]) => ({ product_id: Number(pid), qty: q }));
      if (lines.length) e.lines = lines;
      if (note) e.note = note;
    } else if (["MARKDOWN", "RETURN", "DISPOSE"].includes(p.type)) {
      const ids = new Set([...Object.keys(qty), ...Object.keys(md), ...Object.keys(excluded)]);
      const items = [...ids].map((id) => ({
        lot_id: Number(id),
        ...(qty[id] !== undefined ? { qty: qty[id] } : {}),
        ...(md[id] !== undefined ? { markdown_pct: md[id] } : {}),
        ...(excluded[id] !== undefined ? { include: !excluded[id] } : {}),
      }));
      if (items.length) e.items = items;
    }
    return Object.keys(e).length ? e : undefined;
  }, [p.type, qty, md, excluded, note]);

  const done = (np: Proposal) => {
    setP(np);
    setError(np.status === "FAILED" ? String(np.execution_result?.error ?? "Lỗi") : null);
    qc.invalidateQueries();
  };
  const approve = useMutation({
    mutationFn: () => api<Proposal>(`/proposals/${p.id}/approve`, { method: "POST", body: { note: note || null, edits } }),
    onSuccess: done,
    onError: (e: Error) => setError(e.message),
  });
  const reject = useMutation({
    mutationFn: () => api<Proposal>(`/proposals/${p.id}/reject`, { method: "POST", body: { reason } }),
    onSuccess: done,
    onError: (e: Error) => setError(e.message),
  });

  const ask = () => {
    const text = `Vì sao có đề xuất #${p.id} (${TYPE_LABEL[p.type]}: ${p.title})? `;
    const ev = new CustomEvent<AskDetail>(ASK_EVENT, { detail: { text, handled: false } });
    window.dispatchEvent(ev);
    if (!ev.detail.handled) nav("/chat", { state: { draft: text } });
  };

  const pl = p.payload;
  const warnings = (p.evidence?.warnings as string[] | undefined) ?? [];
  const editable = canDecide && !approve.isPending;

  return (
    <div className={`card proposal st-${p.status}`}>
      <div className="row">
        <span className="badge accent">{TYPE_LABEL[p.type]}</span>
        <StatusBadge status={p.status} />
        <span className="meta">
          #{p.id} · tạo bởi {p.created_by === "agent" ? "Ops Chest (chat)" : p.created_by === "job" ? "Ops Chest (quét tự động)" : p.created_by} ·{" "}
          {dateTimeVi(p.created_at)}
          {p.expires_at && p.status === "PENDING" ? ` · hiệu lực đến ${dateTimeVi(p.expires_at)}` : ""}
        </span>
        <span className="spacer" />
        {p.est_value != null && (
          <b className="num">{p.type === "PURCHASE_ORDER" ? money(p.est_value) : p.est_value >= 0 ? `+${money(p.est_value)}` : money(p.est_value)}</b>
        )}
      </div>
      <h3 style={{ marginTop: 8 }}>{p.title}</h3>
      <p className="rationale">{p.rationale}</p>
      {warnings.map((w) => (
        <div key={w} className="alert warn" style={{ marginBottom: 8 }}>
          ⚠ {w}
        </div>
      ))}
      <div className="row">
        {compact && (
          <button className="sm" onClick={() => setOpen((o) => !o)}>
            {open ? "Thu gọn" : "Xem chi tiết"}
          </button>
        )}
        <button className="sm" onClick={ask} title="Đưa đề xuất này vào ô chat để hỏi tiếp hoặc nhờ sửa">
          Hỏi lại
        </button>
      </div>

      {open && p.type === "PURCHASE_ORDER" && (
        <div className="table-wrap" style={{ marginTop: 8 }}>
          <p className="small secondary">
            Gửi tới {pl.supplier_name} ({pl.supplier_email}) · giao dự kiến {dateVi(pl.expected_date)} · đơn tối thiểu {money(pl.min_order_value)}
          </p>
          <table>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Tên hàng</th>
                <th>ABC-XYZ</th>
                <th className="num">Tồn</th>
                <th className="num">Dự báo phủ</th>
                <th className="num">Đề xuất</th>
                <th className="num">Số lượng</th>
                <th className="num">Thành tiền</th>
              </tr>
            </thead>
            <tbody>
              {(pl.lines as Record<string, any>[]).map((l) => { // eslint-disable-line @typescript-eslint/no-explicit-any
                const q = qty[l.product_id] ?? l.qty;
                const changed = q !== l.suggested_qty;
                return (
                  <tr key={l.product_id}>
                    <td>{l.sku}</td>
                    <td>
                      {l.name}
                      {l.explain?.capped_by_shelf_life && <span className="badge" style={{ marginLeft: 6 }} title="Bị chặn theo hạn sử dụng">trần HSD</span>}
                      {(l.explain?.hypotheses ?? []).map((h: { hypothesis_id: number; factor: number }) => (
                        <span key={h.hypothesis_id} className="badge accent" style={{ marginLeft: 6 }} title="Dự báo đã áp dụng giả thuyết của Store Manager">giả thuyết ×{num(h.factor, 2)}</span>
                      ))}
                      {l.explain?.order_adjustment && <span className="badge accent" style={{ marginLeft: 6 }} title="Hệ số học từ cách Store Manager hay sửa đơn">hệ số ×{num(l.explain.order_adjustment, 2)}</span>}
                    </td>
                    <td>{l.abc_xyz ?? "—"}</td>
                    <td className="num">{num(l.on_hand)}</td>
                    <td className="num">{num(l.forecast_cover, 1)}</td>
                    <td className="num muted">{num(l.suggested_qty)}</td>
                    <td className="num">
                      {editable ? (
                        <input className={`qty ${changed ? "edited" : ""}`} type="number" min={0} step={l.pack_size || 1} value={q}
                          aria-label={`Số lượng ${l.name}`} onChange={(e) => setQty({ ...qty, [l.product_id]: Math.max(0, Number(e.target.value)) })} />
                      ) : (
                        <span className={changed ? "edited" : ""}>{num(q)}</span>
                      )}
                    </td>
                    <td className="num">{money(q * l.unit_cost)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {editable && (
            <input style={{ width: "100%", marginTop: 8 }} placeholder="Ghi chú gửi nhà cung cấp (tuỳ chọn)" value={note} onChange={(e) => setNote(e.target.value)} />
          )}
        </div>
      )}

      {open && ["MARKDOWN", "RETURN", "DISPOSE"].includes(p.type) && (
        <div className="table-wrap" style={{ marginTop: 8 }}>
          <table>
            <thead>
              <tr>
                {p.type === "MARKDOWN" && <th />}
                <th>Lô</th>
                <th>Tên hàng</th>
                <th>HSD</th>
                <th className="num">{p.type === "MARKDOWN" ? "Tồn lô" : "Số lượng"}</th>
                {p.type === "MARKDOWN" && <th>Mức giảm</th>}
                {p.type === "MARKDOWN" && <th className="num">Thu thêm (ước tính)</th>}
              </tr>
            </thead>
            <tbody>
              {(pl.items as Record<string, any>[]).map((it) => { // eslint-disable-line @typescript-eslint/no-explicit-any
                const id = String(it.lot_id);
                const exc = excluded[id] ?? it.include === false;
                return (
                  <tr key={id} style={{ opacity: exc ? 0.45 : 1 }}>
                    {p.type === "MARKDOWN" && (
                      <td>
                        <input type="checkbox" checked={!exc} disabled={!editable} aria-label={`Chọn lô ${id}`}
                          onChange={(e) => setExcluded({ ...excluded, [id]: !e.target.checked })} />
                      </td>
                    )}
                    <td>#{id}</td>
                    <td>
                      {it.name} <span className="muted small">{it.sku}</span>
                    </td>
                    <td>{dateVi(it.expiry_date)}</td>
                    <td className="num">
                      {editable && p.type !== "MARKDOWN" ? (
                        <input className="qty" type="number" min={0} max={it.lot_qty ?? it.qty} value={qty[id] ?? it.qty}
                          onChange={(e) => setQty({ ...qty, [id]: Math.max(0, Number(e.target.value)) })} />
                      ) : (
                        num(it.qty)
                      )}
                    </td>
                    {p.type === "MARKDOWN" && (
                      <td>
                        {editable ? (
                          <select value={md[id] ?? it.markdown_pct} onChange={(e) => setMd({ ...md, [id]: Number(e.target.value) })}>
                            {[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7].map((v) => (
                              <option key={v} value={v}>
                                {pct(v, 0)}
                              </option>
                            ))}
                          </select>
                        ) : (
                          pct(it.markdown_pct, 0)
                        )}{" "}
                        {it.timing === "EVENING" && <span className="badge">giờ vàng sau 18h</span>}
                      </td>
                    )}
                    {p.type === "MARKDOWN" && <td className="num">{money(it.est_gain)}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {p.type === "RETURN" && <p className="small secondary">Hoàn {pct(pl.credit_pct, 0)} giá vốn · ước tính {money(pl.est_credit)} · email gửi {pl.supplier_email}</p>}
        </div>
      )}

      {open && p.type === "DELIST" && (
        <ul className="small secondary">
          {((p.evidence?.reasons as string[]) ?? []).map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      {open && p.type === "DEMAND_HYPOTHESIS" && (
        <div className="table-wrap" style={{ marginTop: 8 }}>
          <p className="small secondary">Dự báo {num(pl.sku_count)} mặt hàng từ {dateVi(pl.start_date)} đến {dateVi(pl.end_date)}: {num(pl.baseline_total, 1)} thành {num(pl.adjusted_total, 1)} đơn vị.</p>
          <table>
            <thead><tr><th>Tên hàng</th><th className="num">Dự báo hiện tại</th><th className="num">Nếu duyệt</th></tr></thead>
            <tbody>
              {(pl.lines as { sku: string; name: string; baseline: number; adjusted: number }[]).map((l) => (
                <tr key={l.sku}><td>{l.name} <span className="muted small">{l.sku}</span></td><td className="num">{num(l.baseline, 1)}</td><td className="num">{num(l.adjusted, 1)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open && p.type === "STOCK_ADJUST" && (
        <div className="table-wrap" style={{ marginTop: 8 }}>
          <table>
            <thead><tr><th>Tên hàng</th><th className="num">Trên sổ</th><th className="num">Đếm được</th><th className="num">Lệch</th><th className="num">Giá trị</th></tr></thead>
            <tbody>
              {(pl.items as { sku: string; name: string; system_qty: number; counted_qty: number; diff: number; value: number }[]).map((it) => (
                <tr key={it.sku}><td>{it.name} <span className="muted small">{it.sku}</span></td><td className="num">{num(it.system_qty)}</td><td className="num">{num(it.counted_qty)}</td><td className="num">{it.diff > 0 ? "+" : ""}{num(it.diff)}</td><td className="num">{money(it.value)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {p.sm_edits?.length > 0 && (
        <p className="small muted" style={{ marginTop: 8 }}>
          SM đã sửa: {p.sm_edits.flatMap((e) => e.changes).map((c) => `${c.field}: ${String(c.from)} → ${String(c.to)}`).join("; ")}
        </p>
      )}
      {p.decided_by && (
        <p className="small muted">
          {STATUS_LABEL[p.status]} bởi {p.decided_by} lúc {dateTimeVi(p.decided_at)}
          {p.decision_note ? ` · "${p.decision_note}"` : ""}
        </p>
      )}
      {p.status === "EXECUTED" && p.execution_result && <ExecResult p={p} />}
      {error && <div className="alert error" style={{ marginTop: 8 }}>{error}</div>}

      {canDecide && (
        <div className="row prop-actions">
          {!rejecting ? (
            <>
              <button className="primary" disabled={approve.isPending} onClick={() => approve.mutate()}>
                {approve.isPending ? "Đang thực hiện…" : p.status === "FAILED" ? "Thử lại" : edits ? "Duyệt với chỉnh sửa" : "Duyệt"}
              </button>
              <button className="danger" onClick={() => setRejecting(true)}>
                Từ chối
              </button>
              <span className="small muted">
                {p.type === "PURCHASE_ORDER" ? "Khi duyệt, hệ thống gửi email + PDF cho nhà cung cấp." : "Chỉ thực hiện sau khi anh/chị duyệt."}
              </span>
            </>
          ) : (
            <>
              <input style={{ flex: 1, minWidth: 220 }} autoFocus placeholder="Lý do từ chối (bắt buộc)" value={reason} onChange={(e) => setReason(e.target.value)} />
              <button className="danger" disabled={!reason.trim() || reject.isPending} onClick={() => reject.mutate()}>
                Xác nhận từ chối
              </button>
              <button className="ghost" onClick={() => setRejecting(false)}>
                Huỷ
              </button>
            </>
          )}
        </div>
      )}
      {!canDecide && p.status === "PENDING" && user?.role !== "manager" && (
        <p className="small muted" style={{ marginTop: 8 }}>Chờ Store Manager duyệt.</p>
      )}
    </div>
  );
}

function ExecResult({ p }: { p: Proposal }) {
  const r = p.execution_result as Record<string, unknown>;
  let text = "Đã thực hiện.";
  if (p.type === "PURCHASE_ORDER") text = `Đã gửi đơn ${r.code} (${money(Number(r.total_value))}) tới ${r.email_to}. Giao dự kiến ${dateVi(String(r.expected_date))}.`;
  else if (p.type === "MARKDOWN") {
    const kept = (r.kept_higher as unknown[] | undefined)?.length ?? 0;
    text = `Đã áp giá giảm cho ${(r.lots_marked_down as unknown[]).length} lô.${kept ? ` Giữ nguyên ${kept} lô đang giảm sâu hơn.` : ""} ${r.instruction}`;
  }
  else if (p.type === "RETURN") text = `Đã gửi phiếu trả ${r.code} tới ${r.email_to}, hoàn dự kiến ${money(Number(r.credit))}.`;
  else if (p.type === "DISPOSE") text = `Đã ghi hủy ${r.lots_disposed} lô, giá vốn ${money(Number(r.waste_cost))}.`;
  else if (p.type === "DELIST" || p.type === "DEMAND_HYPOTHESIS" || p.type === "ORDER_ADJUST") text = String(r.note);
  else if (p.type === "STOCK_ADJUST") text = `Đã điều chỉnh tồn ${r.items} mặt hàng theo số đếm, giá trị lệch ròng ${money(Number(r.net_value))}.`;
  return <div className="alert ok" style={{ marginTop: 8 }}>✓ {text}</div>;
}
