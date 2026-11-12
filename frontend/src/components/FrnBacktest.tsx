import { dateVi, num, pct } from "../format";

type Stat = { median: number | null; q25: number | null; q75: number | null; min: number | null; max: number | null; n: number };
type StoreRow = {
  store_id: number; products: number; start: string; days: number;
  gp_a: number; gp_b_ewma: number; gp_b_ml: number; gain_ewma: number; gain_ml: number; ml_vs_ewma: number;
  waste_a: number; waste_b_ewma: number; waste_b_ml: number; oos_a: number; oos_b_ewma: number; oos_b_ml: number;
  oos_traffic_a: number | null; oos_traffic_b_ewma: number | null; oos_traffic_b_ml: number | null;
};
type Scenario = {
  key: string; label: string; note: string; stores: number | null; gain: number | null;
  waste_a: number | null; waste_b: number | null; oos_a: number | null; oos_b: number | null;
};
export type FrnBt = {
  source: string; t0_date: string; stores: number; runtime_s: number;
  summary: Partial<Record<string, Stat>> & {
    share_ml_better_than_a?: number | null; share_ml_better_than_ewma?: number | null; share_oos_ml_not_worse?: number | null;
  };
  per_store: StoreRow[];
  scenarios: Scenario[];
};

const signed = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${pct(v)}`);
const Gain = ({ v }: { v: number | null | undefined }) =>
  v == null ? <>—</> : <span className={`delta ${v > 0 ? "good" : v < 0 ? "bad" : ""}`}>{signed(v)}</span>;

function median(xs: (number | null | undefined)[]): number | null {
  const v = xs.filter((x): x is number => x != null).sort((a, b) => a - b);
  if (!v.length) return null;
  const h = Math.floor(v.length / 2);
  return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2;
}

export default function FrnBacktest({ d }: { d: FrnBt }) {
  const s = d.summary;
  const stat = (k: string) => s[k] as Stat | undefined;
  const nStores = stat("gain_ml")?.n ?? d.stores;
  // Tom tat khong co oos_traffic_b_ewma: lay trung vi tu bang theo diem
  const trafficEwma = median(d.per_store.map((r) => r.oos_traffic_b_ewma));
  const policies: { key: string; label: string; gain?: Stat; waste?: Stat; oos?: Stat; traffic: number | null | undefined }[] = [
    { key: "a", label: "A · Kinh nghiệm + giờ vàng", waste: stat("waste_a"), oos: stat("oos_a"), traffic: stat("oos_traffic_a")?.median },
    { key: "ewma", label: "B-EWMA · Ops Chest, engine EWMA", gain: stat("gain_ewma"), waste: stat("waste_b_ewma"), oos: stat("oos_b_ewma"), traffic: trafficEwma },
    { key: "ml", label: "B-ML · Ops Chest, LightGBM", gain: stat("gain_ml"), waste: stat("waste_b_ml"), oos: stat("oos_b_ml"), traffic: stat("oos_traffic_b_ml")?.median },
  ];
  const gml = stat("gain_ml")?.median, mve = stat("ml_vs_ewma"), oa = stat("oos_a")?.median, om = stat("oos_b_ml")?.median;
  const cards: [string, number | null | undefined][] = [
    ["Điểm bán B-ML lãi hơn A", s.share_ml_better_than_a],
    ["Điểm bán ML lãi hơn EWMA", s.share_ml_better_than_ewma],
    ["Điểm bán B-ML không hết hàng nhiều hơn A", s.share_oos_ml_not_worse],
  ];
  const stores = [...d.per_store].sort((a, b) => a.gain_ml - b.gain_ml);

  return (
    <>
      <h2>Mô phỏng A/B trên nhu cầu thật của {num(nStores)} điểm bán FRN</h2>
      <p className="small secondary">
        Nhu cầu thật của các điểm FRN giữ lại (không dùng để huấn luyện), từ ngày sau {dateVi(d.t0_date)}; giá, giá vốn, HSD, nhà cung cấp và phản ứng
        của khách với giảm giá vẫn là giả định. Nguồn: {d.source}. Mỗi điểm chạy cả ba chính sách trên cùng chuỗi nhu cầu; số dưới đây là trung vị qua các điểm.
      </p>

      <div className="grid kpis" style={{ margin: "12px 0" }}>
        {cards.map(([l, v]) => (
          <div className="card kpi" key={l}>
            <div className="label">{l}</div>
            <div className="value" style={{ fontSize: 20 }}>{pct(v, 0)}</div>
            <div className="small muted">trên {num(nStores)} điểm</div>
          </div>
        ))}
      </div>

      <div className="table-wrap">
        <table>
          <thead><tr>
            <th>Chính sách</th><th className="num">Lãi gộp so với A (trung vị)</th><th className="num">Khoảng q25 – q75</th>
            <th className="num">Tỷ lệ hủy</th><th className="num">Tỷ lệ hết hàng</th><th className="num">Hết hàng kéo khách</th>
          </tr></thead>
          <tbody>{policies.map((p) => (
            <tr key={p.key}>
              <td>{p.key === "ml" ? <b>{p.label}</b> : p.label}</td>
              <td className="num">{p.key === "a" ? <span className="muted">mốc so sánh</span> : <Gain v={p.gain?.median} />}</td>
              <td className="num">{p.gain ? `${signed(p.gain.q25)} đến ${signed(p.gain.q75)}` : "—"}</td>
              <td className="num">{pct(p.waste?.median)}</td>
              <td className="num">{pct(p.oos?.median)}</td>
              <td className="num">{pct(p.traffic)}</td>
            </tr>
          ))}</tbody>
        </table>
        {mve && (
          <p className="small secondary" style={{ marginTop: 6 }}>
            Riêng phần dự báo, B-ML so với B-EWMA: <Gain v={mve.median} /> lãi gộp (trung vị), khoảng {signed(mve.q25)} đến {signed(mve.q75)},
            thấp nhất {signed(mve.min)}, cao nhất {signed(mve.max)}.
          </p>
        )}
      </div>

      {gml != null && gml < 0 && (
        <div className="alert warn" style={{ marginTop: 8 }}>Ở điểm bán trung vị, B-ML lãi <b>thấp hơn</b> A ({signed(gml)}).</div>
      )}
      {mve?.median != null && mve.median < 0 && (
        <div className="alert warn" style={{ marginTop: 8 }}>
          Ở điểm bán trung vị, LightGBM chưa làm Ops Chest lãi hơn engine EWMA ({signed(mve.median)}). Lợi ích, nếu có, đến từ chính sách đặt hàng chứ không phải từ mô hình.
        </div>
      )}
      {oa != null && om != null && om > oa && (
        <div className="alert" style={{ marginTop: 8 }}>
          Đánh đổi: tỷ lệ hết hàng trung vị của B-ML ({pct(om)}) cao hơn A ({pct(oa)}).
        </div>
      )}

      {d.scenarios.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 16 }}>
          <h3>Kết quả phụ thuộc vào giả định đến đâu</h3>
          <p className="small secondary" style={{ marginTop: -4 }}>Mỗi dòng đổi một giả định; giá trị là trung vị qua các điểm bán, B ở đây là B-ML.</p>
          <table>
            <thead><tr><th>Kịch bản</th><th className="num">Số điểm</th><th className="num">Lãi gộp B so với A</th><th className="num">Tỷ lệ hủy A / B</th><th className="num">Hết hàng A / B</th></tr></thead>
            <tbody>{d.scenarios.map((r) => (
              <tr key={r.key}>
                <td><b>{r.label}</b>{r.note && <div className="small muted">{r.note}</div>}</td>
                <td className="num">{r.stores == null ? "—" : num(r.stores)}</td>
                <td className="num"><Gain v={r.gain} /></td>
                <td className="num">{pct(r.waste_a)} / {pct(r.waste_b)}</td>
                <td className="num">{pct(r.oos_a)} / {pct(r.oos_b)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {stores.length > 0 && (
        <details style={{ marginTop: 16 }}>
          <summary className="secondary">Theo từng điểm bán ({stores.length}), xếp từ lãi B-ML thấp nhất</summary>
          <div className="table-wrap" style={{ marginTop: 8 }}>
            <table>
              <thead><tr>
                <th>Điểm</th><th className="num">Mặt hàng</th><th>Giai đoạn</th>
                <th className="num">B-EWMA so với A</th><th className="num">B-ML so với A</th><th className="num">ML so với EWMA</th>
                <th className="num">Hủy A / EWMA / ML</th><th className="num">Hết hàng A / EWMA / ML</th>
              </tr></thead>
              <tbody>{stores.map((r) => (
                <tr key={r.store_id}>
                  <td>#{r.store_id}</td>
                  <td className="num">{num(r.products)}</td>
                  <td className="small">{dateVi(r.start)}, {r.days} ngày</td>
                  <td className="num"><Gain v={r.gain_ewma} /></td>
                  <td className="num"><Gain v={r.gain_ml} /></td>
                  <td className="num"><Gain v={r.ml_vs_ewma} /></td>
                  <td className="num">{pct(r.waste_a)} / {pct(r.waste_b_ewma)} / {pct(r.waste_b_ml)}</td>
                  <td className="num">{pct(r.oos_a)} / {pct(r.oos_b_ewma)} / {pct(r.oos_b_ml)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </details>
      )}
    </>
  );
}
