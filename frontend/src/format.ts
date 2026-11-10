const nf = new Intl.NumberFormat("vi-VN");

export const money = (v: number | null | undefined) => (v == null ? "—" : `${nf.format(Math.round(v))}đ`);
export const num = (v: number | null | undefined, digits = 0) =>
  v == null ? "—" : new Intl.NumberFormat("vi-VN", { maximumFractionDigits: digits }).format(v);
export const pct = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : `${(v * 100).toLocaleString("vi-VN", { maximumFractionDigits: digits })}%`;

export function compact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return `${num(v / 1e9, 1)} tỷ`;
  if (a >= 1e6) return `${num(v / 1e6, 1)} tr`;
  if (a >= 1e3) return `${num(v / 1e3, 0)}k`;
  return num(v, 1);
}

export function dateVi(iso: string | null | undefined): string {
  if (!iso) return "—";
  if (/^\d{4}-\d{2}$/.test(iso)) {
    const [y, m] = iso.split("-");
    return `${m}/${y}`;
  }
  const d = iso.slice(0, 10).split("-");
  return d.length === 3 ? `${d[2]}/${d[1]}/${d[0]}` : iso;
}

export function dateTimeVi(iso: string | null | undefined): string {
  if (!iso) return "—";
  return `${dateVi(iso)} ${iso.slice(11, 16)}`;
}

export const TYPE_LABEL: Record<string, string> = {
  PURCHASE_ORDER: "Đặt hàng",
  MARKDOWN: "Giảm giá",
  RETURN: "Trả NCC",
  DISPOSE: "Ghi hủy",
  DELIST: "Ngừng nhập",
  DEMAND_HYPOTHESIS: "Giả thuyết",
  ORDER_ADJUST: "Hệ số đặt hàng",
  STOCK_ADJUST: "Kiểm kê",
};

export const WASTE_REASON_LABEL: Record<string, string> = {
  EXPIRED: "Hết hạn",
  DAMAGED: "Vỡ, móp, rách bao bì",
  SPOILED: "Hỏng do bảo quản",
  SUPPLIER_DEFECT: "Lỗi từ nhà cung cấp",
  OTHER: "Lý do khác",
};

export const STATUS_LABEL: Record<string, string> = {
  PENDING: "Chờ duyệt",
  APPROVED: "Đã duyệt",
  EXECUTED: "Đã thực hiện",
  FAILED: "Lỗi khi thực hiện",
  REJECTED: "Đã từ chối",
  EXPIRED: "Hết hiệu lực",
  SUPERSEDED: "Đã có bản sửa",
};

export const WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
