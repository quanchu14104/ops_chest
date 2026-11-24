import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, getUser, type Proposal } from "../api";
import { STATUS_LABEL, TYPE_LABEL, WASTE_REASON_LABEL, actorLabel, dateTimeVi, dateVi, markdownTimeLabel, money, num, pct } from "../format";
import Segmented from "./ui/Segmented";
import { Chips, Icon, InfoTip, PctSlider, Stepper } from "./ui/controls";

// "Hỏi lại": đưa ngữ cảnh đề xuất vào ô chat. Chat đang mở (trang Trợ lý) nghe sự kiện này và điền sẵn;
// nếu không ai nhận (vd đang ở Hộp duyệt) thì chuyển sang /chat kèm bản nháp qua router state.
export const ASK_EVENT = "opschest:ask";
export type AskDetail = { text: string; handled: boolean };

type Edits = { lines?: { product_id: number; qty: number }[]; items?: Record<string, unknown>[]; note?: string; min_order_ack?: boolean };
type MinOrder = {
  shortfall: number;
  top_up: { lines: { product_id: number; sku: string; name: string; add_qty: number; unit_cost: number; line_value: number; days_cover_before: number }[]; added_value: number; reaches_min: boolean };
  defer: { feasible: boolean; at_risk: string[] };
};
type Explain = {
  capped_by_shelf_life?: boolean; capped_by_capacity?: boolean; service_floor?: number; forecast_method?: string;
  hypotheses?: { hypothesis_id: number; factor: number }[]; order_adjustment?: number | null;
};
type PoLine = {
  product_id: number; sku: string; name: string; qty: number; suggested_qty: number; pack_size?: number; unit_cost: number;
  abc_xyz?: string | null; on_hand: number; forecast_cover: number; explain?: Explain;
};
type LineFilter = "attention" | "edited" | "all";

// Đơn dài hơn ngưỡng này thì có thanh lọc và mặc định chỉ hiện dòng cần xem
const LONG_ORDER = 15;

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge st-${status}`}>
      <span className="dot" />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

// Dòng đáng để SM nhìn kỹ: bị chặn trần, có giả thuyết/hệ số, hàng nhóm A, hoặc đặt lệch nhiều so với dự báo
function needsAttention(l: PoLine): boolean {
  const e = l.explain ?? {};
  if (e.capped_by_shelf_life || e.capped_by_capacity || (e.hypotheses?.length ?? 0) > 0 || e.order_adjustment) return true;
  if ((l.abc_xyz ?? "").startsWith("A")) return true;
  const base = Math.max(l.forecast_cover, 1);
  return Math.abs(l.suggested_qty - l.forecast_cover) / base > 0.5;
}

const METHOD_LABEL: Record<string, string> = { lightgbm_frn: "LightGBM", ewma: "EWMA" };

// Lý do từ chối hay gặp: bấm một chip là xong; "Khác" mới cần gõ
const REJECT_REASONS: Record<string, string[]> = {
  PURCHASE_ORDER: ["Hoãn sang lần giao sau", "Số lượng chưa hợp lý", "Đã đặt ngoài hệ thống"],
  MARKDOWN: ["Còn bán được, giữ giá", "Mức giảm chưa hợp lý"],
  RETURN: ["NCC không nhận trả", "Tự xử lý tại cửa hàng"],
  DISPOSE: ["Số lượng chưa đúng, cần đếm lại"],
};
const OTHER = "__other__";

export default function ProposalCard({ p: initial, compact = false, expanded, onToggle }: {
  p: Proposal; compact?: boolean; expanded?: boolean; onToggle?: () => void;
}) {
  const [p, setP] = useState(initial);
  const qc = useQueryClient();
  const user = getUser();
  const nav = useNavigate();
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<{ today: string }>("/meta") });
  const canDecide = user?.role === "manager" && (p.status === "PENDING" || p.status === "FAILED");
  const [openLocal, setOpenLocal] = useState(!compact);
  const open = expanded ?? openLocal;
  const toggle = onToggle ?? (() => setOpenLocal((o) => !o));
  const [qty, setQty] = useState<Record<string, number>>({});
  const [md, setMd] = useState<Record<string, number>>({});
  const [excluded, setExcluded] = useState<Record<string, boolean>>({});
  const [note, setNote] = useState("");
  const [ack, setAck] = useState<boolean | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [reasonPick, setReasonPick] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmNeg, setConfirmNeg] = useState(false);
  const [filter, setFilter] = useState<LineFilter | null>(null);
  const [search, setSearch] = useState("");

  const edits = useMemo<Edits | undefined>(() => {
    const e: Edits = {};
    if (p.type === "PURCHASE_ORDER") {
      const lines = Object.entries(qty).map(([pid, q]) => ({ product_id: Number(pid), qty: q }));
      if (lines.length) e.lines = lines;
      if (note) e.note = note;
      if (ack !== null) e.min_order_ack = ack;
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
  }, [p.type, qty, md, excluded, note, ack]);

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
  const isPO = p.type === "PURCHASE_ORDER";
  // Dòng bù đơn cho mặt hàng chưa có trong đơn: phải hiện ra (và tính vào tổng) thì SM mới thấy mình duyệt gì
  const poLines = (isPO ? pl.lines : []) as PoLine[];
  const topUpNew = isPO && pl.min_order
    ? (pl.min_order as MinOrder).top_up.lines
        .filter((t) => !poLines.some((l) => l.product_id === t.product_id) && qty[t.product_id] !== undefined)
    : [];
  const poTotal = poLines.reduce((s, l) => s + (qty[l.product_id] ?? l.qty) * l.unit_cost, 0)
    + topUpNew.reduce((s, t) => s + (qty[t.product_id] ?? 0) * t.unit_cost, 0);
  const poEdited = isPO && Object.keys(qty).length > 0 && Math.round(poTotal) !== Math.round(p.est_value ?? 0);

  // Lọc dòng cho đơn dài (L-13): mặc định chỉ hiện dòng cần xem
  const isEdited = (l: PoLine) => qty[l.product_id] !== undefined && qty[l.product_id] !== l.suggested_qty;
  const nAttention = poLines.filter(needsAttention).length;
  const nEdited = poLines.filter(isEdited).length;
  const long = poLines.length > LONG_ORDER;
  const activeFilter: LineFilter = !long ? "all" : filter ?? (nAttention > 0 ? "attention" : "all");
  const needle = search.trim().toLowerCase();
  const shownLines = poLines.filter((l) =>
    (activeFilter === "all" || (activeFilter === "attention" ? needsAttention(l) || isEdited(l) : isEdited(l)))
    && (!needle || l.sku.toLowerCase().includes(needle) || l.name.toLowerCase().includes(needle)));
  const methods = poLines.reduce<Record<string, number>>((acc, l) => {
    const m = l.explain?.forecast_method ?? "ewma";
    acc[m] = (acc[m] ?? 0) + 1;
    return acc;
  }, {});

  // Giảm giá mà thu về ít hơn giữ nguyên giá: phải cảnh báo và bấm xác nhận lần hai (L-06)
  const mdItems = (p.type === "MARKDOWN" ? pl.items : []) as { lot_id: number; est_gain?: number; include?: boolean }[];
  const negGain = p.type === "MARKDOWN" && ((p.est_value ?? 0) < 0
    || mdItems.some((it) => (it.est_gain ?? 0) < 0 && !(excluded[String(it.lot_id)] ?? it.include === false)));

  const expiresToday = p.status === "PENDING" && p.expires_at && meta.data?.today && p.expires_at.slice(0, 10) <= meta.data.today.slice(0, 10);
  const valueText = p.est_value == null ? null : isPO ? money(p.est_value) : p.est_value >= 0 ? `+${money(p.est_value)}` : money(p.est_value);
  const hasDetail = ["PURCHASE_ORDER", "MARKDOWN", "RETURN", "DISPOSE", "DELIST", "DEMAND_HYPOTHESIS", "STOCK_ADJUST"].includes(p.type);

  return (
    <article className={`card proposal st-${p.status} ${open ? "is-open" : ""}`}>
      <div className="prop-head">
        <div className="prop-title">
          <div className="row prop-tags">
            <span className="badge accent">{TYPE_LABEL[p.type]}</span>
            <StatusBadge status={p.status} />
            {expiresToday && <span className="badge warn" title={`Hết hiệu lực lúc ${dateTimeVi(p.expires_at)}`}>Hết hiệu lực hôm nay</span>}
          </div>
          <h3>{p.title} {p.rationale && <InfoTip text={p.rationale} />}</h3>
          <div className="meta" title={p.expires_at && p.status === "PENDING" ? `Hiệu lực đến ${dateTimeVi(p.expires_at)}` : undefined}>
            #{p.id} · {actorLabel(p.created_by)} · {dateTimeVi(p.created_at)}
          </div>
        </div>
        <div className="prop-value">
          {valueText && (
            poEdited ? (
              <b className="num"><s className="muted">{valueText}</s> → {money(poTotal)}</b>
            ) : (
              <b className={`num ${p.type === "MARKDOWN" && (p.est_value ?? 0) < 0 ? "neg" : ""}`}>{valueText}</b>
            )
          )}
          <button className="icon sm ghost" onClick={ask} aria-label="Hỏi Ops Chest về đề xuất này" title="Hỏi Ops Chest"><Icon name="chat" /></button>
        </div>
      </div>
      {negGain && (
        <div className="alert error mb-3">
          <b>Thu về ít hơn giữ giá</b>
          {p.est_value != null && p.est_value < 0 ? ` (${money(p.est_value)})` : ""}
        </div>
      )}
      {warnings.map((w) => (
        <div key={w} className="alert warn mb-3">⚠ {w}</div>
      ))}
      {compact && hasDetail && (
        <button className="sm prop-toggle" onClick={toggle} aria-expanded={open}>
          <Icon name={open ? "down" : "chevron"} />
          {open ? "Thu gọn" : isPO ? `${poLines.length} dòng hàng` : "Chi tiết"}
        </button>
      )}

      {open && isPO && (
        <div className="prop-detail">
          <div className="facts">
            <span><Icon name="truck" /> Giao <b>{dateVi(pl.expected_date)}</b></span>
            <span>Tối thiểu <b>{money(pl.min_order_value)}</b></span>
            <InfoTip text={<>Gửi tới {pl.supplier_name} ({pl.supplier_email}). Dự báo: {Object.entries(methods).map(([m, n]) => `${METHOD_LABEL[m] ?? m} ${n} dòng`).join(", ")}.</>} />
          </div>
          {long && (
            <div className="row line-filter">
              <Segmented<LineFilter> label="Lọc dòng hàng" value={activeFilter} onChange={setFilter} options={[
                { value: "attention", label: "Cần xem", count: nAttention },
                { value: "edited", label: "Đã sửa", count: nEdited },
                { value: "all", label: "Tất cả", count: poLines.length },
              ]} />
              <input className="grow" type="search" placeholder="Tìm SKU hoặc tên hàng" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Tìm dòng hàng" />
            </div>
          )}
          <div className="table-wrap">
            <table className="stack-sm">
              <thead>
                <tr>
                  <th>Tên hàng</th>
                  <th className="num">Tồn</th>
                  <th className="num" title="Nhu cầu dự báo trong khoảng hàng về phải phủ">Dự báo</th>
                  <th className="num">Số lượng</th>
                  <th className="num">Thành tiền</th>
                </tr>
              </thead>
              <tbody>
                {shownLines.map((l) => {
                  const q = qty[l.product_id] ?? l.qty;
                  const changed = q !== l.suggested_qty;
                  const e = l.explain ?? {};
                  return (
                    <tr key={l.product_id} className={changed ? "row-edited" : undefined}>
                      <td className="cell-main" title={`${l.sku}${l.abc_xyz ? ` · ${l.abc_xyz}` : ""}${(e.service_floor ?? 0) >= 0.9 ? ` · giữ mức phục vụ ≥${pct(e.service_floor, 0)}` : ""}`}>
                        {l.name}
                        <span className="badges">
                          {e.capped_by_shelf_life && <span className="badge" title="Bị chặn theo hạn sử dụng">trần HSD</span>}
                          {e.capped_by_capacity && <span className="badge" title="Bị chặn theo sức chứa kệ/tủ">sức chứa</span>}
                          {(e.hypotheses ?? []).map((h) => (
                            <span key={h.hypothesis_id} className="badge accent" title="Dự báo đã áp dụng giả thuyết của Store Manager">giả thuyết ×{num(h.factor, 2)}</span>
                          ))}
                          {e.order_adjustment && <span className="badge accent" title="Hệ số học từ cách Store Manager hay sửa đơn">hệ số ×{num(e.order_adjustment, 2)}</span>}
                        </span>
                      </td>
                      <td data-label="Tồn" className="num">{num(l.on_hand)}</td>
                      <td data-label="Dự báo" className="num">{num(l.forecast_cover, 1)}</td>
                      <td data-label="Số lượng" className="num">
                        {editable ? (
                          <span className="qty-cell">
                            {changed && (
                              <button className="linklike small" title="Trả về số đề xuất"
                                onClick={() => { const n = { ...qty }; delete n[l.product_id]; setQty(n); }}>↺ {num(l.suggested_qty)}</button>
                            )}
                            <Stepper value={q} step={l.pack_size || 1} changed={changed} label={`Số lượng ${l.name}`}
                              onChange={(v) => setQty({ ...qty, [l.product_id]: v === "" ? 0 : v })} />
                          </span>
                        ) : (
                          <span className={changed ? "edited" : ""}>{num(q)}</span>
                        )}
                      </td>
                      <td data-label="Thành tiền" className="num">{money(q * l.unit_cost)}</td>
                    </tr>
                  );
                })}
                {shownLines.length === 0 && (
                  <tr><td colSpan={5} className="muted">Không có dòng nào.</td></tr>
                )}
                {topUpNew.map((t) => {
                  const q = qty[t.product_id] ?? 0;
                  return (
                    <tr key={`new-${t.product_id}`} className="row-edited">
                      <td className="cell-main" title={t.sku}>
                        {t.name}
                        <span className="badges"><span className="badge accent" title="Dòng thêm từ phương án bù đơn tối thiểu">bù đơn</span></span>
                      </td>
                      <td data-label="Tồn" className="num">—</td>
                      <td data-label="Dự báo" className="num">—</td>
                      <td data-label="Số lượng" className="num">
                        {editable ? (
                          <Stepper value={q} changed label={`Số lượng ${t.name}`} onChange={(v) => setQty({ ...qty, [t.product_id]: v === "" ? 0 : v })} />
                        ) : (
                          <span className="edited">{num(q)}</span>
                        )}
                      </td>
                      <td data-label="Thành tiền" className="num">{money(q * t.unit_cost)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {pl.min_order && (
            <MinOrderPanel mo={pl.min_order as MinOrder} lines={pl.lines} editable={editable} ack={ack ?? !!pl.min_order_ack} setAck={setAck}
              applyTopUp={() => {
                const cur: Record<string, number> = { ...qty };
                for (const t of (pl.min_order as MinOrder).top_up.lines) {
                  const existing = (pl.lines as { product_id: number; qty: number }[]).find((l) => l.product_id === t.product_id);
                  cur[t.product_id] = (cur[t.product_id] ?? existing?.qty ?? 0) + t.add_qty;
                }
                setQty(cur);
              }} />
          )}
          {editable && (noteOpen || note ? (
            <input className="mt-2" style={{ width: "100%" }} autoFocus placeholder="Ghi chú gửi nhà cung cấp" value={note} onChange={(e) => setNote(e.target.value)}
              aria-label="Ghi chú gửi nhà cung cấp" />
          ) : (
            <button className="sm ghost mt-2" onClick={() => setNoteOpen(true)}><Icon name="note" /> Ghi chú cho NCC</button>
          ))}
        </div>
      )}

      {open && ["MARKDOWN", "RETURN", "DISPOSE"].includes(p.type) && (
        <div className="prop-detail table-wrap">
          <table className="stack-sm">
            <thead>
              <tr>
                {p.type === "MARKDOWN" && <th aria-label="Chọn" />}
                <th>Hàng</th>
                <th>HSD</th>
                {p.type === "DISPOSE" && p.subtype === "EXPIRED" && <th className="num">Trên sổ</th>}
                <th className="num">{p.type === "MARKDOWN" ? "Tồn lô" : p.type === "DISPOSE" && p.subtype === "EXPIRED" ? "Thực gỡ / hủy" : "Số lượng"}</th>
                {p.type === "DISPOSE" && <th>Lý do</th>}
                {p.type === "MARKDOWN" && <th>Mức giảm</th>}
                {p.type === "MARKDOWN" && <th className="num">Thu thêm (ước tính)</th>}
              </tr>
            </thead>
            <tbody>
              {(pl.items as Record<string, any>[]).map((it) => { // eslint-disable-line @typescript-eslint/no-explicit-any
                const id = String(it.lot_id);
                const exc = excluded[id] ?? it.include === false;
                const qtyLabel = p.type === "MARKDOWN" ? "Tồn lô" : p.type === "DISPOSE" && p.subtype === "EXPIRED" ? "Thực gỡ" : "Số lượng";
                return (
                  <tr key={id} className={exc ? "row-excluded" : undefined}>
                    {p.type === "MARKDOWN" && (
                      <td data-label="Áp dụng">
                        <input type="checkbox" checked={!exc} disabled={!editable} aria-label={`Chọn lô ${id}`}
                          onChange={(e) => setExcluded({ ...excluded, [id]: !e.target.checked })} />
                      </td>
                    )}
                    <td className="cell-main" title={`${it.sku} · lô #${id}`}>{it.name}</td>
                    <td data-label="HSD">{dateVi(it.expiry_date)}</td>
                    {p.type === "DISPOSE" && p.subtype === "EXPIRED" && <td data-label="Trên sổ" className="num muted">{num(it.book_qty ?? it.qty)}</td>}
                    <td data-label={qtyLabel} className="num">
                      {editable && p.type !== "MARKDOWN" ? (
                        <Stepper value={qty[id] ?? it.qty} max={it.lot_qty ?? it.qty} changed={qty[id] !== undefined && qty[id] !== it.qty}
                          label={`${qtyLabel} lô ${id}`} onChange={(v) => setQty({ ...qty, [id]: v === "" ? 0 : v })} />
                      ) : (
                        num(it.qty)
                      )}
                    </td>
                    {p.type === "DISPOSE" && (
                      <td data-label="Lý do" className="small">
                        {WASTE_REASON_LABEL[it.reason ?? "EXPIRED"] ?? it.reason}
                        {it.close_lot && !it.pulled && <span className="badges"><span className="badge st-FAILED">chưa xác nhận gỡ kệ</span></span>}
                      </td>
                    )}
                    {p.type === "MARKDOWN" && (
                      <td data-label="Mức giảm">
                        {editable ? (
                          <PctSlider value={md[id] ?? it.markdown_pct} max={it.max_markdown_pct ?? 0.7} label={`Mức giảm lô ${id}`}
                            disabled={exc} onChange={(v) => setMd({ ...md, [id]: v })} />
                        ) : (
                          <b>{pct(it.markdown_pct, 0)}</b>
                        )}
                        {it.timing === "EVENING" && <span className="badges"><span className="badge">{markdownTimeLabel(it.markdown_hour)}</span></span>}
                      </td>
                    )}
                    {p.type === "MARKDOWN" && (
                      <td data-label="Thu thêm" className={`num ${(it.est_gain ?? 0) < 0 ? "neg" : ""}`}>{money(it.est_gain)}</td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {p.type === "RETURN" && (
            <div className="facts mt-2">
              <span>{pl.return_mode === "EXCHANGE" ? "Đổi hàng mới" : <>Hoàn <b>{money(pl.est_credit)}</b></>}</span>
              <InfoTip text={`${pl.return_mode === "EXCHANGE" ? "Đổi hàng mới (đổi date)" : `Hoàn ${pct(pl.credit_pct, 0)} giá vốn`}. Email gửi ${pl.supplier_email}. Duyệt chỉ tách hàng chờ NCC lấy; tiền hoặc hàng đổi ghi nhận khi NCC thực lấy hàng.`} />
            </div>
          )}
          {p.type === "DISPOSE" && p.subtype === "EXPIRED" && (
            <div className="facts mt-2">
              {pl.shrink_cost ? <span>Hao hụt <b>{money(pl.shrink_cost)}</b></span> : null}
              <InfoTip text="Duyệt thì lô được đóng hẳn: hủy theo số thực gỡ, phần chênh với sổ ghi là hao hụt." />
            </div>
          )}
        </div>
      )}

      {open && p.type === "DELIST" && (
        <div className="prop-detail">
          <ul className="small secondary">
            {((p.evidence?.reasons as string[]) ?? []).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          {p.evidence?.sell_down != null && <SellDown plan={p.evidence.sell_down as SellDownPlan} />}
        </div>
      )}

      {open && p.type === "DEMAND_HYPOTHESIS" && (
        <div className="prop-detail table-wrap">
          <p className="small secondary">Dự báo {num(pl.sku_count)} mặt hàng từ {dateVi(pl.start_date)} đến {dateVi(pl.end_date)}: {num(pl.baseline_total, 1)} thành {num(pl.adjusted_total, 1)} đơn vị.</p>
          <table className="stack-sm">
            <thead><tr><th>Tên hàng</th><th className="num">Dự báo hiện tại</th><th className="num">Nếu duyệt</th></tr></thead>
            <tbody>
              {(pl.lines as { sku: string; name: string; baseline: number; adjusted: number }[]).map((l) => (
                <tr key={l.sku}>
                  <td className="cell-main">{l.name} <span className="muted small">{l.sku}</span></td>
                  <td data-label="Dự báo hiện tại" className="num">{num(l.baseline, 1)}</td>
                  <td data-label="Nếu duyệt" className="num">{num(l.adjusted, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open && p.type === "STOCK_ADJUST" && (
        <div className="prop-detail table-wrap">
          <table className="stack-sm">
            <thead><tr><th>Tên hàng</th>{p.subtype === "LOT" && <th>HSD</th>}<th className="num">Trên sổ</th><th className="num">Đếm được</th><th className="num">Lệch</th><th className="num">Giá trị</th></tr></thead>
            <tbody>
              {(pl.items as { sku: string; name: string; expiry_date?: string; new_date?: boolean; system_qty: number; counted_qty: number; diff: number; value: number }[]).map((it) => (
                <tr key={`${it.sku}-${it.expiry_date ?? ""}`}>
                  <td className="cell-main">{it.name} <span className="muted small">{it.sku}</span></td>
                  {p.subtype === "LOT" && <td data-label="HSD">{dateVi(it.expiry_date)}{it.new_date && <span className="badges"><span className="badge accent">sổ chưa có</span></span>}</td>}
                  <td data-label="Trên sổ" className="num">{num(it.system_qty)}</td>
                  <td data-label="Đếm được" className="num">{num(it.counted_qty)}</td>
                  <td data-label="Lệch" className="num">{it.diff > 0 ? "+" : ""}{num(it.diff)}</td>
                  <td data-label="Giá trị" className="num">{money(it.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {p.sm_edits?.length > 0 && (
        <p className="small muted mt-2">
          SM đã sửa: {p.sm_edits.flatMap((e) => e.changes).map((c) => `${c.field}: ${String(c.from)} → ${String(c.to)}`).join("; ")}
        </p>
      )}
      {p.decided_by && (
        <p className="small muted">
          {STATUS_LABEL[p.status]} bởi {actorLabel(p.decided_by)} lúc {dateTimeVi(p.decided_at)}
          {p.decision_note ? ` · "${p.decision_note}"` : ""}
        </p>
      )}
      {p.status === "EXECUTED" && p.execution_result && <ExecResult p={p} />}
      {error && <div className="alert error mt-2">{error}</div>}

      {canDecide && (
        <div className="row prop-actions">
          {!rejecting ? (
            <>
              <button className={negGain ? "danger-solid lg" : "ok lg"} disabled={approve.isPending}
                onClick={() => (negGain && !confirmNeg ? setConfirmNeg(true) : approve.mutate())}>
                <Icon name="check" />
                {approve.isPending ? "Đang thực hiện…"
                  : p.status === "FAILED" ? "Thử lại"
                  : negGain ? (confirmNeg ? "Bấm lần nữa để duyệt" : "Vẫn duyệt")
                  : edits ? "Duyệt (đã sửa)" : "Duyệt"}
              </button>
              <button className="danger lg" onClick={() => setRejecting(true)}>
                <Icon name="x" /> Từ chối
              </button>
              {confirmNeg && <button className="ghost" onClick={() => setConfirmNeg(false)}>Huỷ</button>}
              <InfoTip text={isPO ? "Khi duyệt, hệ thống gửi email + PDF cho nhà cung cấp." : "Chỉ thực hiện sau khi anh/chị duyệt."} />
              <span className="spacer" />
              {isPO && open && <b className="num nowrap prop-total">{money(poTotal)}</b>}
            </>
          ) : (
            <div className="reject-box">
              <Chips label="Lý do từ chối" value={reasonPick} onChange={(v) => { setReasonPick(v); setReason(v === OTHER ? "" : v); }}
                options={[...(REJECT_REASONS[p.type] ?? ["Chưa cần", "Thông tin chưa đúng"]).map((r) => ({ value: r, label: r, tone: "bad" as const })),
                  { value: OTHER, label: "Khác…", tone: "bad" as const }]} />
              {reasonPick === OTHER && (
                <input autoFocus placeholder="Lý do" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Lý do từ chối" />
              )}
              <div className="row">
                <button className="danger-solid" disabled={!reason.trim() || reject.isPending} onClick={() => reject.mutate()}>
                  <Icon name="x" /> Xác nhận từ chối
                </button>
                <button className="ghost" onClick={() => { setRejecting(false); setReasonPick(""); setReason(""); }}>Huỷ</button>
              </div>
            </div>
          )}
        </div>
      )}
      {!canDecide && p.status === "PENDING" && user?.role !== "manager" && (
        <p className="small muted mt-2">Chờ Store Manager duyệt.</p>
      )}
    </article>
  );
}

type SellDownPlan = { on_hand: number; open_po_qty: number; days_to_sell_out: number | null; units_at_risk: number; open_pos: { code: string; qty: number; expected_date: string }[] };

// Ngừng nhập: tồn còn lại bán tới khi hết; nếu không kịp trước HSD thì gợi ý xả hàng.
function SellDown({ plan }: { plan: SellDownPlan }) {
  return (
    <div className={`alert ${plan.units_at_risk >= 1 ? "warn" : ""} mt-1`}>
      Còn {num(plan.on_hand)} đơn vị trên kệ{plan.open_pos.length > 0 ? `, ${plan.open_pos.length} đơn đang về (${num(plan.open_po_qty)} đơn vị: ${plan.open_pos.map((o) => o.code).join(", ")})` : ""}.
      {" "}{plan.days_to_sell_out != null ? `Dự kiến bán hết sau khoảng ${plan.days_to_sell_out} ngày.` : "Gần như không còn bán được."}
      {plan.units_at_risk >= 1 && ` Khoảng ${num(plan.units_at_risk, 1)} đơn vị không bán kịp trước HSD: nên xả hàng (đề xuất giảm giá) và cân nhắc huỷ đơn đang về.`}
    </div>
  );
}

// Đơn dưới giá trị tối thiểu: engine tính sẵn hai phương án, Store Manager chọn.
function MinOrderPanel({ mo, lines, editable, ack, setAck, applyTopUp }: {
  mo: MinOrder; lines: { product_id: number }[]; editable: boolean; ack: boolean; setAck: (v: boolean) => void; applyTopUp: () => void;
}) {
  const topUp = mo.top_up.lines.map((l) => `${l.name} +${l.add_qty}${lines.some((x) => x.product_id === l.product_id) ? "" : " (dòng mới)"}`).join("; ");
  return (
    <div className="alert warn mt-2">
      <b>Đơn thiếu {money(mo.shortfall)} so với giá trị tối thiểu.</b>
      <div className="small mt-1">
        <b>Bù đơn:</b> kéo sớm {mo.top_up.lines.length} mặt hàng bền nhóm A/B ít ngày tồn nhất (+{money(mo.top_up.added_value)})
        {mo.top_up.reaches_min ? "" : ", vẫn chưa đủ mức tối thiểu"}: {topUp || "không có mặt hàng phù hợp"}.{" "}
        {editable && mo.top_up.lines.length > 0 && <button className="sm" onClick={applyTopUp}>Áp dụng bù đơn</button>}
      </div>
      <div className="small mt-1">
        <b>Hoãn:</b>{" "}
        {mo.defer.feasible
          ? "được, không mặt hàng nào hết trước lần giao sau (theo dự báo). Từ chối đề xuất với lý do hoãn."
          : `không nên, ${mo.defer.at_risk.length} mặt hàng sẽ hết trước lần giao sau (${mo.defer.at_risk.slice(0, 5).join(", ")}).`}
      </div>
      <label className="small mt-2" style={{ display: "block" }}>
        <input type="checkbox" checked={ack} disabled={!editable} onChange={(e) => setAck(e.target.checked)} /> Đã thỏa thuận với NCC về đơn dưới mức tối thiểu (bắt buộc nếu duyệt khi đơn chưa đủ mức)
      </label>
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
  else if (p.type === "RETURN") text = `Đã gửi phiếu trả ${r.code} tới ${r.email_to} và tách hàng chờ NCC lấy. ${r.mode === "EXCHANGE" ? "Hàng đổi" : `Tiền hoàn (dự kiến ${money(Number(r.est_credit))})`} chỉ ghi nhận khi NCC lấy hàng.`;
  else if (p.type === "DISPOSE") text = `Đã ghi hủy ${r.lots_disposed} lô, giá vốn ${money(Number(r.waste_cost))}.${Number(r.shrink_value) ? ` Hao hụt so với sổ ${money(Number(r.shrink_value))}.` : ""}`;
  else if (p.type === "DELIST" || p.type === "DEMAND_HYPOTHESIS" || p.type === "ORDER_ADJUST") text = String(r.note);
  else if (p.type === "STOCK_ADJUST") text = `Đã điều chỉnh tồn ${r.items} mặt hàng theo số đếm, giá trị lệch ròng ${money(Number(r.net_value))}.`;
  return <div className="alert ok mt-2">✓ {text}</div>;
}
