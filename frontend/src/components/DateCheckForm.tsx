import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type DateCheckLine, type Proposal } from "../api";
import { dateVi } from "../format";
import DateField from "./ui/DateField";
import { Icon, InfoTip, Stepper } from "./ui/controls";

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
  // Ô thêm HSD chỉ mở cho mặt hàng người đếm bấm "+ HSD khác", để mỗi mặt hàng gọn một dòng
  const [adding, setAdding] = useState<string | null>(null);
  const addDate = (sku: string) => {
    const d = newDate[sku];
    if (!d) return;
    setExtra({ ...extra, [sku]: [...new Set([...(extra[sku] ?? []), d])] });
    setNewDate({ ...newDate, [sku]: "" });
    setAdding(null);
  };
  return (
    <div className="card tight widget">
      <div className="widget-title row">{title}{note && <InfoTip text={note} />}</div>
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
            {lines.map((l) => {
              const ds = datesOf(l);
              const rows = ds.map((d, i) => (
                <tr key={key(l.sku, d)} className={i === 0 ? "group-start" : "group-cont"}>
                  <td>
                    {i === 0 && (
                      <>
                        <span title={l.sku}>{l.name}</span>
                        {adding !== l.sku && (
                          <button className="icon sm ghost add-date" onClick={() => setAdding(l.sku)} aria-label={`Thêm HSD khác cho ${l.name}`} title="Thêm HSD khác"><Icon name="plus" /></button>
                        )}
                      </>
                    )}
                  </td>
                  <td>
                    {dateVi(d)}
                    {!l.dates.includes(d) && <span className="badges"><span className="badge accent">mới thêm</span></span>}
                  </td>
                  <td className="num">
                    <Stepper value={(counts[key(l.sku, d)] ?? "") === "" ? "" : Number(counts[key(l.sku, d)])} placeholder="–"
                      onChange={(v) => setCounts({ ...counts, [key(l.sku, d)]: v === "" ? "" : String(v) })} label={`Số đếm ${l.name} HSD ${dateVi(d)}`} />
                  </td>
                </tr>
              ));
              if (adding === l.sku) {
                rows.push(
                  <tr key={`${l.sku}-add`} className="group-cont">
                    <td />
                    <td colSpan={2} className="small">
                      <span className="row">
                        <DateField value={newDate[l.sku] ?? ""} onChange={(v) => setNewDate({ ...newDate, [l.sku]: v })} label={`Thêm HSD ${l.name}`} />
                        <button className="sm" disabled={!newDate[l.sku]} onClick={() => addDate(l.sku)}>Thêm</button>
                        <button className="sm ghost" onClick={() => setAdding(null)}>Huỷ</button>
                      </span>
                    </td>
                  </tr>,
                );
              }
              return rows;
            })}
          </tbody>
        </table>
      </div>
      {msg && <div className={`alert ${msg.ok ? "ok" : "error"} mt-2`}>{msg.text}</div>}
      <div className="row mt-3">
        <button className="primary lg" disabled={touched.length === 0 || m.isPending} onClick={() => m.mutate()}>
          <Icon name="check" /> {m.isPending ? "Đang ghi…" : `Xác nhận ${touched.length} mặt hàng`}
        </button>
      </div>
    </div>
  );
}
