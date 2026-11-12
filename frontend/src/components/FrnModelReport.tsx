import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api";
import { dateVi, num, pct } from "../format";

type Metric = {
  n: number; wape: number | null; bias: number | null; pinball50?: number | null;
  pinball10?: number | null; pinball90?: number | null; coverage80?: number | null;
};
type Mode = "obs" | "rec";
type MethodResult = Partial<Record<Mode, Record<string, Metric>>>;
type Board = Record<string, MethodResult>;
type ElastPoint = { e: number; n: number; ci90?: [number, number] };
type Elast = { all: ElastPoint; by_group?: Record<string, { e: number; n: number }> };
type FrnMeta = {
  features: string[]; k_scale: number; dates: [string, string]; cutoff_date: string; t0_date: string;
  demo_store: number; heldout_stores: number[]; n_heldout_stores: number; use_ml_segments: string[]; runtime_s: number;
};
export type FrnReport = {
  meta: FrnMeta | null;
  recovery_check: { n: number; wape_recovered: number; bias_recovered: number; wape_sales_as_demand: number; bias_sales_as_demand: number } | null;
  eval_week_heldout: Board | null;
  rolling_heldout_bt: Board | null;
  gate: Record<string, boolean> | null;
  importance_q50: Record<string, number> | null;
  elasticity: { train_stores?: Elast; heldout_stores?: Elast } | null;
};

const METHODS: [string, string][] = [
  ["lightgbm", "LightGBM (FRN)"],
  ["ewma_oc", "Engine EWMA của OC"],
  ["ewma_khong_co_het_hang", "EWMA bỏ cờ hết hàng"],
  ["cung_thu_tuan_truoc", "Cùng thứ tuần trước"],
  ["tb_28_ngay", "Trung bình 28 ngày"],
];
const GROUP_ORDER = ["ban_it|deu", "ban_it|lat_nhat", "ban_vua|deu", "ban_vua|lat_nhat", "ban_chay|deu", "ban_chay|lat_nhat"];
const VOLUME: Record<string, string> = { ban_it: "Bán ít", ban_vua: "Bán vừa", ban_chay: "Bán chạy" };
const PATTERN: Record<string, string> = { deu: "bán đều", lat_nhat: "lắt nhắt" };
const SOURCE = "FreshRetailNet-50K (Dingdong, CC BY 4.0) — kho giao hàng online, không phải cửa hàng tiện lợi";

const groupLabel = (g: string) => {
  const [v, p] = g.split("|");
  return `${VOLUME[v] ?? v}, ${PATTERN[p] ?? p ?? ""}`.replace(/, $/, "");
};
const signedPct = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${pct(v)}`);
const dec = (v: number | null | undefined, d = 2) => (v == null ? "—" : num(v, d));

function featureLabel(f: string): string | null {
  let m = f.match(/^lag_(\d+)$/);
  if (m) return `Nhu cầu ${m[1]} ngày trước`;
  m = f.match(/^roll_mean_(\d+)$/);
  if (m) return `Trung bình ${m[1]} ngày`;
  const fixed: Record<string, string> = {
    dow: "Thứ trong tuần", discount: "Mức giảm giá", holiday_flag: "Ngày lễ", activity_flag: "Có khuyến mãi",
    precpt: "Lượng mưa", avg_temperature: "Nhiệt độ TB", avg_humidity: "Độ ẩm TB", avg_wind_level: "Mức gió TB",
    store_id: "Mã điểm bán", product_id: "Mã sản phẩm", first_category_id: "Ngành hàng cấp 1",
  };
  return fixed[f] ?? null;
}

export default function FrnModelReport() {
  const q = useQuery({ queryKey: ["ml-frn"], queryFn: () => api<FrnReport>("/reports/ml/frn"), retry: false });
  const [board, setBoard] = useState<"eval" | "rolling">("eval");
  const [mode, setMode] = useState<Mode>("obs");

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h2>Dự báo nhu cầu bằng LightGBM trên dữ liệu thật</h2>
      <p className="small secondary" style={{ marginTop: -6 }}>Nguồn: {SOURCE}.</p>
      {q.isPending && <p className="muted">Đang tải…</p>}
      {q.error && (q.error instanceof ApiError && q.error.status === 404 ? (
        <p className="muted">
          Chưa có kết quả mô hình. Huấn luyện trên Kaggle, đặt <code>meta.json</code> vào <code>backend/app/ml/artifacts/</code> và
          chạy backtest FRN để sinh <code>backend/app/sim/data/frn/report.json</code>, rồi tải lại trang.
        </p>
      ) : <div className="alert error">{(q.error as Error).message}</div>)}
      {q.data && <Body d={q.data} board={board} setBoard={setBoard} mode={mode} setMode={setMode} />}
    </div>
  );
}

function Body({ d, board, setBoard, mode, setMode }: {
  d: FrnReport; board: "eval" | "rolling"; setBoard: (b: "eval" | "rolling") => void; mode: Mode; setMode: (m: Mode) => void;
}) {
  const m = d.meta;
  const data = board === "eval" ? d.eval_week_heldout : d.rolling_heldout_bt;
  return (
    <>
      {m && (
        <p className="small secondary">
          Mô hình chạy thật học trên {dateVi(m.dates[0])} – {dateVi(m.cutoff_date)} và được chấm trên tuần sau đó
          (đến {dateVi(m.dates[1])}); bảng "Cuốn chiếu" dùng mô hình backtest chỉ học đến {dateVi(m.t0_date)}.
          Mọi con số dưới đây chấm trên <b>{m.n_heldout_stores} điểm bán giữ lại</b>, không dùng khi huấn luyện.
          {" "}{m.features.length} đặc trưng; nhu cầu FRN nhân hệ số K = {num(m.k_scale, 2)} để ra đơn vị hàng của cửa hàng mô phỏng (điểm bán #{m.demo_store}).
        </p>
      )}

      <div className="row" style={{ margin: "8px 0", gap: 8, flexWrap: "wrap" }}>
        <div className="seg" role="tablist" aria-label="Giai đoạn đánh giá">
          <button className={board === "eval" ? "on" : ""} onClick={() => setBoard("eval")}>Tuần đánh giá</button>
          <button className={board === "rolling" ? "on" : ""} onClick={() => setBoard("rolling")}>Cuốn chiếu 37 ngày</button>
        </div>
        <div className="seg" role="tablist" aria-label="Chấm trên">
          <button className={mode === "obs" ? "on" : ""} onClick={() => setMode("obs")}>Ngày còn hàng đủ giờ</button>
          <button className={mode === "rec" ? "on" : ""} onClick={() => setMode("rec")}>Nhu cầu đã khôi phục</button>
        </div>
      </div>
      <p className="small muted" style={{ margin: "0 0 8px" }}>
        {mode === "obs"
          ? "Chỉ chấm những ngày mặt hàng còn hàng suốt giờ bán, nên số bán chính là nhu cầu. Không thiên vị, nhưng bỏ qua đúng những ngày khó nhất."
          : "Chấm trên nhu cầu đã khôi phục cho cả những ngày hết hàng giữa chừng. Phủ hết các ngày, nhưng bản thân đáp án cũng là ước lượng."}
      </p>

      {data ? <MethodTable data={data} mode={mode} /> : <p className="muted">Không có số liệu cho giai đoạn này.</p>}
      {data && <GroupTable data={data} mode={mode} gate={d.gate ?? {}} />}

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        {d.recovery_check && <Recovery r={d.recovery_check} />}
        {d.elasticity && <Elasticity e={d.elasticity} />}
      </div>

      {d.importance_q50 && <Importance imp={d.importance_q50} />}
    </>
  );
}

function MethodTable({ data, mode }: { data: Board; mode: Mode }) {
  const rows = METHODS.map(([k, label]) => ({ k, label, m: data[k]?.[mode]?.all })).filter((r) => r.m);
  if (!rows.length) return <p className="muted">Không có số liệu cho lựa chọn này.</p>;
  const best = Math.min(...rows.map((r) => r.m!.wape ?? Infinity));
  const ml = data.lightgbm?.[mode]?.all;
  const oc = data.ewma_oc?.[mode]?.all;
  const gain = ml?.wape != null && oc?.wape ? (oc.wape - ml.wape) / oc.wape : null;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>
          <th>Phương pháp</th><th className="num">Số dòng</th><th className="num">WAPE</th><th className="num">Độ lệch</th>
          <th className="num">Pinball q50</th><th className="num">Độ phủ 80%</th>
        </tr></thead>
        <tbody>{rows.map(({ k, label, m }) => (
          <tr key={k}>
            <td>{k === "lightgbm" ? <b>{label}</b> : label}</td>
            <td className="num">{num(m!.n)}</td>
            <td className="num">{m!.wape === best ? <b>{pct(m!.wape)}</b> : pct(m!.wape)}</td>
            <td className="num">{signedPct(m!.bias)}</td>
            <td className="num">{dec(m!.pinball50, 3)}</td>
            <td className="num">
              {m!.coverage80 == null ? "—" : <span className={Math.abs(m!.coverage80 - 0.8) > 0.05 ? "badge warn" : ""}>{pct(m!.coverage80)}</span>}
            </td>
          </tr>
        ))}</tbody>
      </table>
      <p className="small muted" style={{ marginTop: 6 }}>
        WAPE: tổng sai số tuyệt đối / tổng nhu cầu, càng thấp càng tốt (in đậm là thấp nhất). Độ lệch âm là dự báo thấp hơn thực tế (dễ hết hàng),
        dương là dự báo cao (dễ tồn, dễ hủy). Độ phủ 80%: tỷ lệ ngày nhu cầu thật nằm trong khoảng q10–q90, đúng ra phải gần 80%; lệch quá 5 điểm được đánh dấu.
        Hai mốc đơn giản cuối bảng chỉ có dự báo điểm nên không có độ phủ.
      </p>
      {gain != null && (gain > 0
        ? <div className="alert ok" style={{ marginTop: 8 }}>Tổng thể, LightGBM giảm WAPE {pct(gain)} so với engine EWMA của OC. Mức chênh khác nhau theo nhóm hàng, xem bảng dưới.</div>
        : <div className="alert warn" style={{ marginTop: 8 }}>Tổng thể, LightGBM <b>không tốt hơn</b> engine EWMA của OC (WAPE {pct(ml!.wape)} so với {pct(oc!.wape)}). Xem bảng theo nhóm để biết nhóm nào vẫn dùng engine cũ.</div>)}
    </div>
  );
}

function GroupTable({ data, mode, gate }: { data: Board; mode: Mode; gate: Record<string, boolean> }) {
  const ml = data.lightgbm?.[mode] ?? {};
  const oc = data.ewma_oc?.[mode] ?? {};
  const keys = new Set([...Object.keys(ml), ...Object.keys(oc), ...Object.keys(gate)]);
  keys.delete("all");
  const groups = [...GROUP_ORDER.filter((g) => keys.has(g)), ...[...keys].filter((g) => !GROUP_ORDER.includes(g)).sort()];
  if (!groups.length) return null;
  return (
    <div className="table-wrap" style={{ marginTop: 16 }}>
      <h3>Theo nhóm hàng: LightGBM hay engine cũ</h3>
      <p className="small secondary" style={{ marginTop: -4 }}>
        Cột "Theo sai số" là bộ chọn cũ: nhóm nào LightGBM sai ít hơn EWMA trên tuần eval. Số liệu theo đúng giai đoạn và cách chấm đang chọn ở trên.
        App hiện <b>không</b> dùng cột này mà chọn theo lãi trong backtest (decision_gate.json, xem mục Backtest A/B bên dưới): ở điểm bán lớn như
        cửa hàng demo, LightGBM chỉ dùng cho hàng bán ít và bán vừa; hàng bán chạy giữ EWMA.
      </p>
      <table>
        <thead><tr>
          <th>Nhóm hàng</th><th className="num">Số dòng</th><th className="num">WAPE LightGBM</th><th className="num">WAPE EWMA</th>
          <th className="num">Chênh lệch</th><th className="num">Độ phủ 80% (ML / EWMA)</th><th>Theo sai số</th>
        </tr></thead>
        <tbody>{groups.map((g) => {
          const a = ml[g], b = oc[g];
          const diff = a?.wape != null && b?.wape != null ? a.wape - b.wape : null;
          const useMl = gate[g];
          return (
            <tr key={g}>
              <td>{groupLabel(g)}</td>
              <td className="num">{a ? num(a.n) : b ? num(b.n) : "—"}</td>
              <td className="num">{pct(a?.wape)}</td>
              <td className="num">{pct(b?.wape)}</td>
              <td className="num">{diff == null ? "—" : <span className={`delta ${diff < 0 ? "good" : diff > 0 ? "bad" : ""}`}>{diff > 0 ? "+" : ""}{num(diff * 100, 1)} điểm</span>}</td>
              <td className="num">{pct(a?.coverage80)} / {pct(b?.coverage80)}</td>
              <td>{useMl == null ? <span className="badge">Chưa xếp</span> : useMl ? <span className="badge accent">Dùng ML</span> : <span className="badge warn">Giữ engine cũ</span>}</td>
            </tr>
          );
        })}</tbody>
      </table>
      <p className="small muted" style={{ marginTop: 6 }}>Chênh lệch âm (xanh) là LightGBM sai ít hơn. "Lắt nhắt" là hàng nhiều ngày không bán, khó dự báo với mọi phương pháp.</p>
    </div>
  );
}

function Recovery({ r }: { r: NonNullable<FrnReport["recovery_check"]> }) {
  const better = r.wape_recovered < r.wape_sales_as_demand;
  return (
    <div>
      <h3>Kiểm tra khôi phục nhu cầu</h3>
      <p className="small secondary">
        Ngày hết hàng giữa chừng, số bán thấp hơn nhu cầu thật. Kiểm tra trên {num(r.n)} mẫu đã biết đáp án: sai số khi dùng nhu cầu khôi phục
        so với khi coi luôn số bán là nhu cầu.
      </p>
      <table>
        <thead><tr><th>Cách làm</th><th className="num">WAPE</th><th className="num">Độ lệch</th></tr></thead>
        <tbody>
          <tr><td>Khôi phục nhu cầu</td><td className="num">{better ? <b>{pct(r.wape_recovered)}</b> : pct(r.wape_recovered)}</td><td className="num">{signedPct(r.bias_recovered)}</td></tr>
          <tr><td>Coi số bán là nhu cầu</td><td className="num">{!better ? <b>{pct(r.wape_sales_as_demand)}</b> : pct(r.wape_sales_as_demand)}</td><td className="num">{signedPct(r.bias_sales_as_demand)}</td></tr>
        </tbody>
      </table>
      <p className="small muted" style={{ marginTop: 6 }}>
        {better
          ? "Khôi phục sai ít hơn. Coi số bán là nhu cầu thường lệch âm: mô hình học theo sẽ đặt thiếu đúng những mặt hàng hay hết."
          : "Khôi phục chưa tốt hơn coi số bán là nhu cầu trên mẫu kiểm tra; các số chấm theo chế độ \"Nhu cầu đã khôi phục\" cần đọc thận trọng."}
      </p>
    </div>
  );
}

function Elasticity({ e }: { e: NonNullable<FrnReport["elasticity"]> }) {
  const rows: [string, Elast | undefined][] = [["Điểm huấn luyện", e.train_stores], ["Điểm giữ lại", e.heldout_stores]];
  const tr = e.train_stores?.all, ho = e.heldout_stores?.all;
  const consistent = tr && ho?.ci90 ? tr.e >= ho.ci90[0] && tr.e <= ho.ci90[1] : null;
  const groups = [...new Set([...Object.keys(e.train_stores?.by_group ?? {}), ...Object.keys(e.heldout_stores?.by_group ?? {})])].sort();
  return (
    <div>
      <h3>Độ co giãn theo giảm giá (ước lượng)</h3>
      <p className="small secondary">Theo dạng OC dùng: bán tăng ≈ 1 + e × mức giảm (giảm 10% giá thì bán tăng e × 10%). Ước lượng trên những ngày giảm giá không kèm quảng bá, so với ngày bán giá gốc cùng thứ.</p>
      <p className="small" style={{ marginTop: 4 }}>
        <strong>Không dùng trong OC.</strong> e ≈ 9 nghĩa là giảm 10% giá mà bán tăng ~90%: không hợp lý. Giá của Dingdong có vẻ
        nội sinh (giảm giá đúng lúc nhu cầu cao), nên so ngày giảm với ngày không giảm không đo được tác động của giá. Engine giữ
        giả định 3,0; muốn đo đúng phải thử nghiệm giá.
      </p>
      <table>
        <thead><tr><th>Tập điểm bán</th><th className="num">e</th><th className="num">Khoảng tin cậy 90%</th><th className="num">Số dòng</th></tr></thead>
        <tbody>{rows.map(([l, x]) => (
          <tr key={l}>
            <td>{l}</td><td className="num">{dec(x?.all.e)}</td>
            <td className="num">{x?.all.ci90 ? `${dec(x.all.ci90[0])} đến ${dec(x.all.ci90[1])}` : "—"}</td>
            <td className="num">{x ? num(x.all.n) : "—"}</td>
          </tr>
        ))}</tbody>
      </table>
      {consistent != null && (
        <p className="small muted" style={{ marginTop: 6 }}>
          {consistent
            ? "Hai tập điểm bán cho cùng một con số, nhưng ổn định không có nghĩa là đúng: cùng một cách đặt giá thì cùng một sai lệch."
            : "Ước lượng trên điểm huấn luyện nằm ngoài khoảng tin cậy của điểm giữ lại: độ co giãn không ổn định giữa các điểm bán, không nên dùng một con số chung."}
          {" "}Đây là kho online của Dingdong; khách cửa hàng tiện lợi có thể phản ứng với giảm giá khác.
        </p>
      )}
      {groups.length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary className="small secondary">Theo nhóm ({groups.length})</summary>
          <table>
            <thead><tr><th>Nhóm</th><th className="num">e (huấn luyện)</th><th className="num">e (giữ lại)</th></tr></thead>
            <tbody>{groups.map((g) => {
              const a = e.train_stores?.by_group?.[g], b = e.heldout_stores?.by_group?.[g];
              return (
                <tr key={g}>
                  <td>{GROUP_ORDER.includes(g) ? groupLabel(g) : `Nhóm ${g}`}</td>
                  <td className="num">{a ? `${dec(a.e)} (${num(a.n)})` : "—"}</td>
                  <td className="num">{b ? `${dec(b.e)} (${num(b.n)})` : "—"}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </details>
      )}
    </div>
  );
}

function Importance({ imp }: { imp: Record<string, number> }) {
  const all = Object.entries(imp).sort((a, b) => b[1] - a[1]);
  const total = all.reduce((s, [, v]) => s + v, 0) || 1;
  const top = all.slice(0, 8);
  const max = top[0]?.[1] || 1;
  return (
    <div style={{ marginTop: 16 }}>
      <h3>8 đặc trưng quan trọng nhất (mô hình q50, theo gain)</h3>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(140px, 220px) 1fr 56px", gap: "4px 10px", alignItems: "center" }}>
        {top.map(([f, v]) => {
          const label = featureLabel(f);
          return [
            <div key={`${f}-l`} className="small" title={f}>{label ?? <code>{f}</code>}{label && <span className="muted"> · {f}</span>}</div>,
            <div key={`${f}-b`} style={{ background: "var(--surface-2)", borderRadius: 3, height: 10 }}>
              <div style={{ width: `${(v / max) * 100}%`, background: "var(--accent)", height: "100%", borderRadius: 3 }} />
            </div>,
            <div key={`${f}-v`} className="small num">{pct(v / total)}</div>,
          ];
        })}
      </div>
      <p className="small muted" style={{ marginTop: 6 }}>Phần trăm là tỷ trọng gain trên tổng {all.length} đặc trưng. Gain cao không có nghĩa là quan hệ nhân quả.</p>
    </div>
  );
}
