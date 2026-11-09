import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type CountLine, type Proposal } from "../api";

// Đếm mù: phiếu không hiện số trên sổ. Nhìn thấy số thì người đếm có xu hướng đếm cho khớp.
export default function StockCountForm({ lines, title, note }: { lines: CountLine[]; title: string; note?: string | null }) {
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
      <div className="widget-title">{title}</div>
      <div className="widget-scroll">
        <table>
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
                <td>{l.sku} · {l.name}</td>
                <td className="muted small">{l.category}</td>
                <td className="num">
                  <input
                    className="qty"
                    type="number"
                    min={0}
                    value={counts[l.sku] ?? ""}
                    onChange={(e) => setCounts({ ...counts, [l.sku]: e.target.value })}
                    aria-label={`Số đếm ${l.name}`}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {note && <div className="small muted" style={{ marginTop: 6 }}>{note}</div>}
      {msg && <div className={`alert ${msg.ok ? "ok" : "error"}`} style={{ marginTop: 8 }}>{msg.text}</div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="primary" disabled={filled.length === 0 || m.isPending} onClick={() => m.mutate()}>
          {m.isPending ? "Đang ghi…" : `Xác nhận số đếm (${filled.length})`}
        </button>
      </div>
    </div>
  );
}
