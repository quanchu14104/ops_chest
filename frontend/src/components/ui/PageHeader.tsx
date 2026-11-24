import type { ReactNode } from "react";
import { InfoTip } from "./controls";

// Đầu trang: chỉ tiêu đề và hành động. Câu mô tả không bắt buộc nên thu vào biểu tượng ⓘ.
export default function PageHeader({ title, desc, actions }: { title: ReactNode; desc?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="page-head-text">
        <h1>{title}</h1>
        {desc && <InfoTip text={desc} />}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}
