import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, type WidgetFmt, type WidgetSpec } from "../api";
import { STATUS_LABEL, TYPE_LABEL, dateVi, money, num, pct } from "../format";
import ExpiryPhoto from "./ExpiryPhoto";
import StockCountForm from "./StockCountForm";

// Nhan hien thi cho trang thai lo hang (backend tra ma tieng Anh)
const LOT_STATUS: Record<string, string> = {
  EXPIRED: "Đã quá hạn",
  URGENT: "Gấp",
  AT_RISK: "Có nguy cơ",
  WATCH: "Theo dõi",
  OK: "Ổn",
};

function fmtValue(v: string | number | null | undefined, fmt: WidgetFmt): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  switch (fmt) {
    case "num":
      return Number.isFinite(n) ? num(n, Number.isInteger(n) ? 0 : 1) : String(v);
    case "money":
      return Number.isFinite(n) ? money(n) : String(v);
    case "pct":
      return Number.isFinite(n) ? pct(n) : String(v);
    case "date":
      return dateVi(String(v));
    case "days":
      return Number.isFinite(n) ? (n < 0 ? `quá ${-n} ngày` : n === 0 ? "hôm nay" : `${n} ngày`) : String(v);
    case "ptype":
      return TYPE_LABEL[String(v)] ?? String(v);
    case "badge":
      return LOT_STATUS[String(v)] ?? STATUS_LABEL[String(v)] ?? String(v);
    default:
      return String(v);
  }
}

const NUMERIC: WidgetFmt[] = ["num", "money", "pct"];

function badgeClass(v: string | number | null): string {
  const s = String(v);
  if (s === "EXPIRED" || s === "URGENT" || s === "FAILED") return "badge bad";
  if (s === "AT_RISK" || s === "WATCH") return "badge warn";
  return "badge";
}

function TableWidget({ w }: { w: Extract<WidgetSpec, { kind: "table" }> }) {
  return (
    <div className="card tight widget">
      <div className="widget-title">{w.title}</div>
      {w.rows.length === 0 ? (
        <p className="muted small" style={{ margin: "8px 0 0" }}>{w.empty}</p>
      ) : (
        <div className="widget-scroll">
          <table>
            <thead>
              <tr>
                {w.columns.map((c) => (
                  <th key={c.key} className={NUMERIC.includes(c.fmt) ? "num" : ""}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {w.rows.map((r, i) => (
                <tr key={i}>
                  {w.columns.map((c) => (
                    <td key={c.key} className={NUMERIC.includes(c.fmt) ? "num" : ""}>
                      {c.fmt === "badge" && r[c.key] != null ? (
                        <span className={badgeClass(r[c.key])}>{fmtValue(r[c.key], c.fmt)}</span>
                      ) : (
                        fmtValue(r[c.key], c.fmt)
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {w.more > 0 && <div className="small muted" style={{ marginTop: 6 }}>… và {w.more} dòng nữa. Hãy hỏi thu hẹp (theo nhóm hàng, NCC…) để xem chi tiết.</div>}
      {w.note && <div className="small muted" style={{ marginTop: 6 }}>{w.note}</div>}
    </div>
  );
}

function KpiWidget({ w }: { w: Extract<WidgetSpec, { kind: "kpis" }> }) {
  return (
    <div className="card tight widget">
      <div className="widget-title">{w.title}</div>
      <div className="widget-kpis">
        {w.items.map((it) => {
          let delta = null;
          if (it.value != null && it.prev != null && it.prev !== 0) {
            const d = (it.value - it.prev) / Math.abs(it.prev);
            const good = it.lower_is_better ? d < 0 : d > 0;
            delta = (
              <div className={`delta ${Math.abs(d) < 0.005 ? "" : good ? "good" : "bad"}`}>
                {d > 0 ? "▲" : d < 0 ? "▼" : "•"} {pct(Math.abs(d))}
              </div>
            );
          }
          return (
            <div key={it.label} className="kpi">
              <div className="label">{it.label}</div>
              <div className="value">{fmtValue(it.value, it.fmt)}</div>
              {delta}
            </div>
          );
        })}
      </div>
      {w.note && <div className="small muted" style={{ marginTop: 6 }}>{w.note}</div>}
    </div>
  );
}

// Form nhan hang trong chat: LLM chi mo form, viec ghi do nguoi dung bam xac nhan -> endpoint receive co san
function ReceiveFormWidget({ w }: { w: Extract<WidgetSpec, { form: "receive_po" }> }) {
  const qc = useQueryClient();
  const [qty, setQty] = useState<Record<number, string>>({});
  const [exp, setExp] = useState<Record<number, string>>({});
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [done, setDone] = useState(false);
  const busy = useRef(false); // chan bam dup truoc khi React kip render lai nut

  // Tai lai lich su chat: neu don da duoc nhan o noi khac thi khoa form
  const po = useQuery({
    queryKey: ["po", w.meta.po_id],
    queryFn: () => api<{ status: string }>(`/purchase-orders/${w.meta.po_id}`),
    staleTime: 15_000,
  });
  const closed = done || (po.data != null && po.data.status !== "SENT");

  const m = useMutation({
    mutationFn: () =>
      api<{ code: string; lots: { sku: string; qty: number }[] }>(w.submit.path, {
        method: w.submit.method,
        body: {
          lines: w.lines.map((l) => ({
            line_id: l.line_id,
            received_qty: Number(qty[l.line_id] ?? l.received_qty ?? l.qty),
            expiry_date: exp[l.line_id] || l.default_expiry,
          })),
        },
      }),
    onSuccess: (r) => {
      setDone(true);
      setResult({ ok: true, text: `Đã nhận hàng đơn ${r.code}, ghi ${r.lots.length} lô vào kho.` });
      qc.invalidateQueries({ queryKey: ["pending-count"] });
      qc.invalidateQueries({ queryKey: ["briefing"] });
      qc.invalidateQueries({ queryKey: ["po"] });
      qc.invalidateQueries({ queryKey: ["pos"] });
    },
    onError: (e: Error) => setResult({ ok: false, text: e.message }),
    onSettled: () => {
      busy.current = false;
    },
  });

  function submit() {
    if (busy.current || closed) return;
    busy.current = true;
    setResult(null);
    m.mutate();
  }

  return (
    <div className="card tight widget">
      <div className="widget-title">{w.title}</div>
      <div className="widget-scroll">
        <table>
          <thead>
            <tr>
              <th>Hàng</th>
              <th className="num">Đặt</th>
              <th className="num">Nhận thực tế</th>
              <th>HSD trên bao bì</th>
            </tr>
          </thead>
          <tbody>
            {w.lines.map((l) => (
              <tr key={l.line_id}>
                <td>{l.sku} · {l.name}</td>
                <td className="num">{num(l.qty)}</td>
                <td className="num">
                  <input
                    className="qty"
                    type="number"
                    min={0}
                    disabled={closed}
                    value={qty[l.line_id] ?? String(l.received_qty ?? l.qty)}
                    onChange={(e) => setQty({ ...qty, [l.line_id]: e.target.value })}
                    aria-label={`Số lượng nhận ${l.name}`}
                  />
                </td>
                <td>
                  <input
                    type="date"
                    disabled={closed}
                    value={exp[l.line_id] ?? l.default_expiry}
                    onChange={(e) => setExp({ ...exp, [l.line_id]: e.target.value })}
                    aria-label={`HSD ${l.name}`}
                  />
                  <ExpiryPhoto sku={l.sku} disabled={closed} onRead={(iso) => setExp((cur) => ({ ...cur, [l.line_id]: iso }))} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {w.note && !closed && <div className="small muted" style={{ marginTop: 6 }}>{w.note}</div>}
      {result && <div className={`alert ${result.ok ? "ok" : "error"}`} style={{ marginTop: 8 }}>{result.text}</div>}
      {closed && !done && <div className="small muted" style={{ marginTop: 8 }}>Đơn này không còn ở trạng thái chờ giao (đã nhận hoặc đã huỷ).</div>}
      {!closed && (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="primary" disabled={m.isPending} onClick={submit}>
            {m.isPending ? "Đang ghi…" : "Xác nhận nhận hàng"}
          </button>
        </div>
      )}
    </div>
  );
}

export default function Widget({ spec }: { spec: WidgetSpec }) {
  if (spec.kind === "table") return <TableWidget w={spec} />;
  if (spec.kind === "form" && spec.form === "stock_count") return <StockCountForm lines={spec.lines} title={spec.title} note={spec.note} />;
  if (spec.kind === "form") return <ReceiveFormWidget w={spec} />;
  return <KpiWidget w={spec} />;
}
