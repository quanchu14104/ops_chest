import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type DateCheckLine, type Proposal } from "../api";
import { dateVi } from "../format";

// Kiểm date: đếm theo từng HSD nhìn thấy trên kệ. Phiếu chỉ hiện các HSD sổ đang có, KHÔNG hiện số lượng (đếm mù).
// Mặt hàng đã nhập ít nhất một số thì các HSD để trống được gửi là 0: người đếm đã xem hết kệ của mặt hàng đó.
export default function DateCheckForm({ lines, title, note }: { lines: DateCheckLine[]; title: string; note?: string | null }) {
  const qc = useQueryClient();
  const [counts, setCounts] = useState<Record<string, string>>({}); // key = sku|date
  const [extra, setExtra] = useState<Record<string, string[]>>({}); // HSD them moi theo sku
  const [newDate, setNewDate] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const key = (sku: string, d: string) => `${sku}|${d}`;
  const datesOf = (l: DateCheckLine) => [...l.dates, ...(extra[l.sku] ?? [])];
  const touched = lines.filter((l) => datesOf(l).some((d) => (counts[key(l.sku, d)] ?? "") !== ""));
  const body = touched.flatMap((l) => datesOf(l).map((d) => ({ sku: l.sku, expiry_date: d, counted_qty: Number(counts[key(l.sku, d)] || 0) })));
  const m = useMutation({
    mutationFn: () => api<{ counted: number; proposal: Proposal | null }>("/date-checks", { method: "POST", body: { lines: body } }),
    onSuccess: (r) => {
      setCounts({});
      setExtra({});
      setMsg({
        ok: true,
        text: r.proposal
          ? `Đã kiểm date ${r.counted} mặt hàng, có HSD lệch với sổ. Đã tạo đề xuất #${r.proposal.id}, chờ Store Manager duyệt.`
          : `Đã kiểm date ${r.counted} mặt hàng, khớp với sổ.`,
      });
      qc.invalidateQueries();
    },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  const addDate = (sku: string) => {
    const d = newDate[sku];
    if (!d) return;
    setExtra({ ...extra, [sku]: [...new Set([...(extra[sku] ?? []), d])] });
    setNewDate({ ...newDate, [sku]: "" });
  };
  return (
    <div className="card tight widget">
      <div className="widget-title">{title}</div>
      <div className="widget-scroll">
        <table>
          <thead>
            <tr>
              <th>Hàng</th>
              <th>HSD trên bao bì</th>
              <th className="num">Số đếm</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) =>
              datesOf(l).map((d, i) => (
                <tr key={key(l.sku, d)}>
                  <td>{i === 0 ? `${l.sku} · ${l.name}` : ""}</td>
                  <td>
                    {dateVi(d)}
                    {!l.dates.includes(d) && <span className="badge accent" style={{ marginLeft: 6 }}>mới thêm</span>}
                  </td>
                  <td className="num">
                    <input className="qty" type="number" min={0} value={counts[key(l.sku, d)] ?? ""}
                      onChange={(e) => setCounts({ ...counts, [key(l.sku, d)]: e.target.value })} aria-label={`Số đếm ${l.name} HSD ${dateVi(d)}`} />
                  </td>
                </tr>
              )).concat(
                <tr key={`${l.sku}-add`}>
                  <td />
                  <td colSpan={2} className="small">
                    <input type="date" value={newDate[l.sku] ?? ""} onChange={(e) => setNewDate({ ...newDate, [l.sku]: e.target.value })} aria-label={`Thêm HSD ${l.name}`} />{" "}
                    <button className="sm ghost" disabled={!newDate[l.sku]} onClick={() => addDate(l.sku)}>Thêm HSD</button>
                  </td>
                </tr>,
              ),
            )}
          </tbody>
        </table>
      </div>
      {note && <div className="small muted" style={{ marginTop: 6 }}>{note}</div>}
      {msg && <div className={`alert ${msg.ok ? "ok" : "error"}`} style={{ marginTop: 8 }}>{msg.text}</div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="primary" disabled={touched.length === 0 || m.isPending} onClick={() => m.mutate()}>
          {m.isPending ? "Đang ghi…" : `Xác nhận kiểm date (${touched.length} mặt hàng)`}
        </button>
      </div>
    </div>
  );
}
