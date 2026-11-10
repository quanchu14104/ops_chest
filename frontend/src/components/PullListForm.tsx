import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Proposal, type PullLine } from "../api";
import { dateVi } from "../format";

// Rút kệ cuối ngày: việc bắt buộc của ca làm, không chờ duyệt. Nhân viên ghi số THỰC gỡ (phiếu không hiện số trên sổ).
// Store Manager chỉ duyệt bút toán ghi hủy được tạo sau đó.
export default function PullListForm({ lines, title, note }: { lines: PullLine[]; title: string; note?: string | null }) {
  const qc = useQueryClient();
  const [qty, setQty] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const filled = lines.filter((l) => (qty[l.lot_id] ?? "") !== "");
  const m = useMutation({
    mutationFn: () =>
      api<{ pulled: unknown[]; proposal: Proposal | null }>("/shelf/pull", {
        method: "POST",
        body: { lines: filled.map((l) => ({ lot_id: l.lot_id, pulled_qty: Number(qty[l.lot_id]) })) },
      }),
    onSuccess: (r) => {
      setQty({});
      setMsg({
        ok: true,
        text: `Đã ghi nhận gỡ ${r.pulled.length} lô khỏi kệ.${r.proposal ? ` Đề xuất ghi hủy #${r.proposal.id} chờ Store Manager duyệt.` : ""}`,
      });
      qc.invalidateQueries();
    },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  return (
    <div className="card tight widget">
      <div className="widget-title">{title}</div>
      {lines.length === 0 ? (
        <p className="muted small">Không có lô nào cần rút kệ.</p>
      ) : (
        <div className="widget-scroll">
          <table>
            <thead>
              <tr>
                <th>Hàng</th>
                <th>HSD</th>
                <th>Ngày bán cuối</th>
                <th className="num">Số thực gỡ</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.lot_id}>
                  <td>{l.sku} · {l.name} <span className="muted small">lô #{l.lot_id}</span></td>
                  <td>{dateVi(l.expiry_date)}</td>
                  <td>
                    {dateVi(l.sell_by)}
                    {l.overdue_days > 0 && <span className="badge st-FAILED" style={{ marginLeft: 6 }}>quá {l.overdue_days} ngày</span>}
                  </td>
                  <td className="num">
                    <input className="qty" type="number" min={0} value={qty[l.lot_id] ?? ""}
                      onChange={(e) => setQty({ ...qty, [l.lot_id]: e.target.value })} aria-label={`Số gỡ ${l.name}`} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {note && <div className="small muted" style={{ marginTop: 6 }}>{note}</div>}
      {msg && <div className={`alert ${msg.ok ? "ok" : "error"}`} style={{ marginTop: 8 }}>{msg.text}</div>}
      {lines.length > 0 && (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="primary" disabled={filled.length === 0 || m.isPending} onClick={() => m.mutate()}>
            {m.isPending ? "Đang ghi…" : `Xác nhận đã gỡ (${filled.length} lô)`}
          </button>
        </div>
      )}
    </div>
  );
}
