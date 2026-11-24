import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type CountLine, type Proposal } from "../api";
import { Icon, InfoTip, Stepper } from "./ui/controls";

// Đếm mù: phiếu không hiện số trên sổ. Nhìn thấy số thì người đếm có xu hướng đếm cho khớp.
export default function StockCountForm({ lines, title, note }: { lines: (CountLine & { reason?: string })[]; title: string; note?: string | null }) {
  const qc = useQueryClient();
  const [counts, setCounts] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const filled = Object.entries(counts).filter(([, v]) => v !== "");
  const m = useMutation({
    mutationFn: () =>
      api<{ counted: number; proposal: Proposal | null }>("/stock-counts", {
        method: "POST",
        body: { lines: filled.map(([sku, v]) => ({ sku, counted_qty: Number(v) })) },
      }),
    onSuccess: (r) => {
      setCounts({});
      setMsg({
        ok: true,
        text: r.proposal
          ? `Đã đếm ${r.counted} mặt hàng, có chênh lệch. Đã tạo đề xuất #${r.proposal.id}, chờ Store Manager duyệt.`
          : `Đã đếm ${r.counted} mặt hàng, khớp với sổ.`,
      });
      qc.invalidateQueries();
    },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  return (
    <div className="card tight widget">
      <div className="widget-title row">{title}{note && <InfoTip text={note} />}</div>
      <div className="widget-scroll">
        <table className="stack-sm">
          <thead>
            <tr>
              <th>Hàng</th>
              <th>Nhóm</th>
              <th className="num">Số đếm</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.sku}>
                <td className="cell-main" title={l.sku}>{l.name}{l.reason && <span className="badges"><InfoTip text={l.reason} /></span>}</td>
                <td data-label="Nhóm" className="muted small">{l.category}</td>
                <td data-label="Số đếm" className="num">
                  <Stepper value={(counts[l.sku] ?? "") === "" ? "" : Number(counts[l.sku])} placeholder="–" label={`Số đếm ${l.name}`}
                    onChange={(v) => setCounts({ ...counts, [l.sku]: v === "" ? "" : String(v) })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {msg && <div className={`alert ${msg.ok ? "ok" : "error"} mt-2`}>{msg.text}</div>}
      <div className="row mt-3">
        <button className="primary lg" disabled={filled.length === 0 || m.isPending} onClick={() => m.mutate()}>
          <Icon name="check" /> {m.isPending ? "Đang ghi…" : `Xác nhận ${filled.length} mặt hàng`}
        </button>
      </div>
    </div>
  );
}
