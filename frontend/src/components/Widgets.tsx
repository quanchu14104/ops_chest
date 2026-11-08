import type { WidgetFmt, WidgetSpec } from "../api";
import { STATUS_LABEL, TYPE_LABEL, dateVi, money, num, pct } from "../format";

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

export default function Widget({ spec }: { spec: WidgetSpec }) {
  return spec.kind === "table" ? <TableWidget w={spec} /> : <KpiWidget w={spec} />;
}
