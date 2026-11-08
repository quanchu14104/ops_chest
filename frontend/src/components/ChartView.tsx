import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "../api";
import { compact, dateVi, money, num } from "../format";

// Thu tu mau co dinh (da kiem dinh CVD), khong xoay vong; toi da 4 series moi bieu do.
const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

function fmtValue(v: number, unit: string) {
  return unit === "VND" ? money(v) : `${num(v, 1)} ${unit}`;
}

function fmtX(v: string) {
  return /^\d{4}-\d{2}(-\d{2})?$/.test(v) ? dateVi(v).slice(0, v.length === 7 ? 7 : 5) : v;
}

type TipProps = {
  active?: boolean;
  label?: string;
  payload?: { dataKey: string; value: number; color: string; name: string }[];
  unit: string;
};

function Tip({ active, label, payload, unit }: TipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tooltip">
      <div className="t">{/^\d{4}-/.test(String(label)) ? dateVi(String(label)) : label}</div>
      {payload.map((p) => (
        <div className="r" key={p.dataKey}>
          <span>
            <i style={{ background: p.color }} />
            {p.name}
          </span>
          <b className="num">{fmtValue(p.value, unit)}</b>
        </div>
      ))}
    </div>
  );
}

function Matrix({ spec }: { spec: ChartSpec }) {
  const max = Math.max(1, ...spec.data.map((d) => Number(d.skus)));
  const bg = (n: number) => {
    const t = n / max;
    if (n === 0) return "var(--surface-2)";
    if (t < 0.25) return "var(--seq-100)";
    if (t < 0.5) return "var(--seq-250)";
    if (t < 0.75) return "var(--seq-400)";
    return "var(--seq-550)";
  };
  const ink = (n: number) => (n / max >= 0.5 ? "#fff" : "#0b0b0b");
  const cell = (c: string) => spec.data.find((d) => d.cell === c) ?? { cell: c, skus: 0, margin_90d: 0, policy: "" };
  return (
    <div>
      <div className="matrix">
        <div />
        {["X · ổn định", "Y · dao động", "Z · thất thường"].map((x) => (
          <div key={x} className="ax" style={{ height: 24 }}>
            {x}
          </div>
        ))}
        {["A", "B", "C"].map((a) => (
          <Row key={a} a={a} cell={cell} bg={bg} ink={ink} />
        ))}
      </div>
      <p className="small muted" style={{ marginTop: 8 }}>
        A/B/C: nhóm tạo 80% / 15% / 5% lợi nhuận gộp sau hủy (90 ngày). X/Y/Z: độ biến động nhu cầu tuần (CV &lt; 0,5 /
        0,5–1 / &gt; 1). Màu đậm = nhiều SKU.
      </p>
    </div>
  );
}

function Row({ a, cell, bg, ink }: { a: string; cell: (c: string) => Record<string, unknown>; bg: (n: number) => string; ink: (n: number) => string }) {
  return (
    <>
      <div className="ax">{a}</div>
      {["X", "Y", "Z"].map((x) => {
        const d = cell(a + x);
        const n = Number(d.skus);
        return (
          <div key={x} className="cell" style={{ background: bg(n), color: ink(n) }} title={String(d.policy)}>
            <div className="c">{a + x}</div>
            <div className="n">{n}</div>
            <div className="small">lãi {compact(Number(d.margin_90d))}</div>
          </div>
        );
      })}
    </>
  );
}

export default function ChartView({ spec, height = 260 }: { spec: ChartSpec; height?: number }) {
  const [table, setTable] = useState(false);
  const series = spec.series.slice(0, 4);
  // Theo thoi gian ma qua nhieu moc -> duong (thay vi cot day dac)
  const type = spec.type === "bar" && spec.x_key === "period" && spec.data.length > 16 && !spec.stacked ? "line" : spec.type;
  const axisTick = { fill: "var(--text-muted)", fontSize: 11 };
  const yFmt = (v: number) => (spec.unit === "VND" ? compact(v) : num(v));

  let body: JSX.Element;
  if (table) {
    body = (
      <div className="table-wrap" style={{ maxHeight: height + 40, overflowY: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>{spec.x_key === "period" ? "Thời gian" : "Nhóm"}</th>
              {series.map((s) => (
                <th key={s.key} className="num">
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {spec.data.map((r, i) => (
              <tr key={i}>
                <td>{fmtX(String(r[spec.x_key]))}</td>
                {series.map((s) => (
                  <td key={s.key} className="num">
                    {fmtValue(Number(r[s.key] ?? 0), spec.unit)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  } else if (spec.type === "matrix") {
    body = <Matrix spec={spec} />;
  } else if (type === "line") {
    body = (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={spec.data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey={spec.x_key} tickFormatter={fmtX} tick={axisTick} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis tickFormatter={yFmt} tick={axisTick} axisLine={false} tickLine={false} width={52} />
          <Tooltip content={<Tip unit={spec.unit} />} cursor={{ stroke: "var(--text-muted)", strokeDasharray: "3 3" }} />
          {series.map((s, i) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={SERIES[i]} strokeWidth={2} dot={false}
              activeDot={{ r: 4, stroke: "var(--surface-1)", strokeWidth: 2 }} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  } else if (type === "hbar") {
    const h = Math.max(height, spec.data.length * 28 + 30);
    body = (
      <ResponsiveContainer width="100%" height={h}>
        <BarChart data={spec.data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 0 }} barCategoryGap={4}>
          <CartesianGrid horizontal={false} stroke="var(--grid)" />
          <XAxis type="number" tickFormatter={yFmt} tick={axisTick} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey={spec.x_key} width={170} tick={axisTick} axisLine={false} tickLine={false} />
          <Tooltip content={<Tip unit={spec.unit} />} cursor={{ fill: "var(--surface-2)" }} />
          {series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={SERIES[i]} radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  } else {
    body = (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={spec.data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} barGap={2}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey={spec.x_key} tickFormatter={fmtX} tick={axisTick} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={yFmt} tick={axisTick} axisLine={false} tickLine={false} width={52} />
          <Tooltip content={<Tip unit={spec.unit} />} cursor={{ fill: "var(--surface-2)" }} />
          {series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={SERIES[i]} stackId={spec.stacked ? "a" : undefined}
              radius={spec.stacked && i < series.length - 1 ? 0 : [4, 4, 0, 0]} maxBarSize={36}
              stroke="var(--surface-1)" strokeWidth={spec.stacked ? 1 : 0} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  return (
    <div className="card chart-card">
      <div className="head">
        <div>
          <div className="title">{spec.title}</div>
          <div className="period">
            {spec.period} · đơn vị: {spec.unit}
          </div>
        </div>
        <button className="sm ghost" onClick={() => setTable((t) => !t)} aria-pressed={table}>
          {table ? "Xem biểu đồ" : "Xem bảng"}
        </button>
      </div>
      {spec.type !== "matrix" && series.length > 1 && !table && (
        <div className="legend">
          {series.map((s, i) => (
            <span key={s.key}>
              <i style={{ background: SERIES[i] }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      {spec.data.length === 0 ? <p className="muted">Không có dữ liệu trong khoảng này.</p> : body}
    </div>
  );
}
