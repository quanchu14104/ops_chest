import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiError, type ChartSpec } from "../api";
import ChartView from "../components/ChartView";
import FrnBacktest, { type FrnBt } from "../components/FrnBacktest";
import FrnModelReport from "../components/FrnModelReport";
import PageHeader from "../components/ui/PageHeader";
import { dateVi, money, pct } from "../format";

type BT = { start: string; days: number; results: Record<string, Record<string, number>>; delta: Record<string, number> };
type SensRow = {
  key: string; label: string; note: string; gain: number; gain_pct: number; waste_a: number; waste_b: number; oos_a: number; oos_b: number;
  oos_traffic_a?: number; oos_traffic_b?: number; oos_class_a_a?: number; oos_class_a_b?: number;
};
type Sens = { start: string; days: number; rows: SensRow[] };

// Báo cáo kỹ thuật (người làm dữ liệu / đánh giá dự án): phân nhóm ABC-XYZ, độ chính xác dự báo LightGBM, mô phỏng A/B.
// Không nằm trong menu của Store Manager; mở từ menu tài khoản.
export default function ModelReport() {
  const abc = useQuery({ queryKey: ["chart-abc"], queryFn: () => api<ChartSpec>(`/charts?metric=abc_xyz`) });
  const bt = useMutation({ mutationFn: (d: number) => api<BT>(`/reports/backtest?days=${d}`) });
  const frnBt = useQuery({ queryKey: ["bt-frn"], queryFn: () => api<FrnBt>("/reports/backtest/frn"), retry: false });
  // Bang do nhay cu chi can khi chua co backtest FRN
  const sens = useQuery({ enabled: frnBt.isError, queryKey: ["bt-sensitivity"], queryFn: () => api<Sens>("/reports/backtest/sensitivity"), retry: false });

  return (
    <>
      <PageHeader title="Báo cáo mô hình"
        desc="Phần kỹ thuật cho người làm dữ liệu và đánh giá dự án: phân nhóm ABC-XYZ, độ chính xác dự báo, mô phỏng so sánh cách đặt hàng. Không cần cho việc vận hành hằng ngày." />
      {abc.data && <div className="mb-4"><ChartView spec={abc.data} /></div>}
      <FrnModelReport />

      {frnBt.data ? (
        <div className="card mt-3"><FrnBacktest d={frnBt.data} /></div>
      ) : frnBt.isPending ? (
        <div className="card mt-3"><p className="muted">Đang tải kết quả mô phỏng…</p></div>
      ) : (
        <div className="card mt-3">
          <h2>Mô phỏng A/B (dữ liệu giả lập cũ)</h2>
          {!(frnBt.error instanceof ApiError && frnBt.error.status === 404) && (
            <div className="alert error mb-3">Không tải được backtest trên dữ liệu FRN: {(frnBt.error as Error).message}</div>
          )}
          <p className="small secondary">
            Chạy lại cùng cửa hàng với <b>cùng nhu cầu khách</b> (tất định) bằng 2 chính sách đặt hàng. A: mức tồn theo trung bình 4 tuần, cuối ngày giảm 30% hàng hết hạn hôm nay.
            B: dự báo + newsvendor/order-up-to có sàn mức phục vụ (kéo khách 95%, nhóm A 90%) + trần HSD và sức chứa + giảm giá giờ vàng theo khung bán của nhóm hàng/trả NCC (coi như SM duyệt hết). Trong mô phỏng, khách chỉ phản ứng với giảm giá bằng một nửa mức engine giả định. Mất khoảng 10-30 giây.
          </p>
          <div className="row">
            {[30, 60, 90].map((d) => <button key={d} disabled={bt.isPending} onClick={() => bt.mutate(d)}>Chạy {d} ngày</button>)}
            {bt.isPending && <span className="muted">Đang mô phỏng…</span>}
          </div>
          {bt.error && <div className="alert error">{(bt.error as Error).message}</div>}
          {bt.data && <Backtest d={bt.data} />}
          {sens.data && <Sensitivity d={sens.data} />}
        </div>
      )}
    </>
  );
}

function Sensitivity({ d }: { d: Sens }) {
  const signed = (v: number) => `${v >= 0 ? "+" : ""}${pct(v)}`;
  const core = d.rows.filter((r) => r.key === "reference" || r.key.startsWith("seed_")).map((r) => r.gain_pct);
  const oosWorse = d.rows.every((r) => r.oos_b > r.oos_a);
  const ref = d.rows.find((r) => r.key === "reference");
  return (
    <div className="table-wrap" style={{ marginTop: 16 }}>
      <h2>Kết quả phụ thuộc vào giả định đến đâu</h2>
      <p className="small secondary">
        Tính sẵn từ {dateVi(d.start)}, {d.days} ngày. Mỗi dòng chỉ đổi một điều so với dòng tham chiếu. Lợi nhuận gộp của B so với A ở kịch bản tham chiếu và các chuỗi nhu cầu khác: <b>{signed(Math.min(...core))} đến {signed(Math.max(...core))}</b>.
      </p>
      <table>
        <thead><tr><th>Kịch bản</th><th className="num">Lợi nhuận B so với A</th><th className="num">Tỷ lệ hủy A / B</th><th className="num">Hết hàng A / B</th><th className="num">Hàng kéo khách A / B</th><th className="num">Nhóm A A / B</th></tr></thead>
        <tbody>{d.rows.map((r) => (
          <tr key={r.key}>
            <td><b>{r.label}</b><div className="small muted">{r.note}</div></td>
            <td className="num">{signed(r.gain_pct)}</td>
            <td className="num">{pct(r.waste_a)} / {pct(r.waste_b)}</td>
            <td className="num">{pct(r.oos_a)} / {pct(r.oos_b)}</td>
            <td className="num">{r.oos_traffic_a == null ? "—" : `${pct(r.oos_traffic_a)} / ${pct(r.oos_traffic_b)}`}</td>
            <td className="num">{r.oos_class_a_a == null ? "—" : `${pct(r.oos_class_a_a)} / ${pct(r.oos_class_a_b)}`}</td>
          </tr>
        ))}</tbody>
      </table>
      {oosWorse && <div className="alert" style={{ marginTop: 10 }}>Đánh đổi: tỷ lệ hết hàng của B cao hơn A ở mọi kịch bản. Lợi nhuận tăng chủ yếu nhờ hủy ít hơn, không phải nhờ bán được nhiều hơn.</div>}
      {!oosWorse && ref && ref.oos_b <= ref.oos_a && (
        <div className="alert" style={{ marginTop: 10 }}>
          Ở kịch bản tham chiếu, B không hết hàng nhiều hơn A ({pct(ref.oos_b)} so với {pct(ref.oos_a)}) nhờ sàn mức phục vụ. Cái giá là phần lợi nhuận tăng thêm nhỏ hơn cách đặt cũ (dòng "B không có sàn mức phục vụ").
        </div>
      )}
    </div>
  );
}

function Backtest({ d }: { d: BT }) {
  const names = Object.keys(d.results);
  const rows: [string, string, (v: number) => string][] = [
    ["revenue", "Doanh thu", money], ["gross_profit", "Lợi nhuận gộp (sau hủy)", money], ["waste_cost", "Giá vốn hàng hủy", money],
    ["waste_rate", "Tỷ lệ hủy", (v) => pct(v)], ["oos_rate", "Tỷ lệ hết hàng", (v) => pct(v)], ["lost_margin", "Lãi mất do hết hàng", money],
    ["markdown_loss", "Giảm giá đã chi", money], ["return_credit", "NCC hoàn tiền", money], ["avg_inventory_value", "Tồn kho TB", money],
  ];
  return (
    <div className="table-wrap" style={{ marginTop: 12 }}>
      <p className="small muted">Từ {dateVi(d.start)}, {d.days} ngày.</p>
      <table>
        <thead><tr><th>Chỉ số</th>{names.map((n) => <th key={n} className="num">{n}</th>)}</tr></thead>
        <tbody>{rows.map(([k, l, f]) => <tr key={k}><td>{l}</td>{names.map((n) => <td key={n} className="num">{f(d.results[n][k])}</td>)}</tr>)}</tbody>
      </table>
      <div className="alert ok" style={{ marginTop: 10 }}>
        B so với A: lợi nhuận gộp <b>{d.delta.gross_profit_gain >= 0 ? "+" : ""}{money(d.delta.gross_profit_gain)}</b>, giảm hàng hủy <b>{money(d.delta.waste_cost_saved)}</b>,
        tồn kho TB {d.delta.inventory_value_reduction >= 0 ? "giảm" : "tăng"} {money(Math.abs(d.delta.inventory_value_reduction))}.
      </div>
    </div>
  );
}
