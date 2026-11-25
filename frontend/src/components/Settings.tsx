import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getUser } from "../api";
import { FastForward } from "./StoreControls";
import Segmented from "./ui/Segmented";
import { Icon } from "./ui/controls";

type Meta = { llm_model: string; llm_model_fallback: string | null; llm_configured: boolean };

// Cài đặt: gom những thứ không thuộc việc hằng ngày (giao diện, trợ lý, báo cáo kỹ thuật, công cụ demo) ra khỏi các trang
export default function SettingsDialog({ open, onClose, theme, setTheme, meta }: {
  open: boolean; onClose: () => void; theme: string; setTheme: (t: string) => void; meta?: Meta;
}) {
  const nav = useNavigate();
  const isManager = getUser()?.role === "manager";
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="task-dialog-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="task-dialog settings" role="dialog" aria-modal="true" aria-label="Cài đặt">
        <div className="task-dialog-head">
          <h2>Cài đặt</h2>
          <span className="spacer" />
          <button className="icon ghost" aria-label="Đóng" onClick={onClose}><Icon name="x" /></button>
        </div>
        <div className="task-dialog-body">
          <section className="settings-section">
            <h3>Giao diện</h3>
            <Segmented label="Giao diện" value={theme} onChange={setTheme}
              options={[{ value: "auto", label: "Theo hệ thống" }, { value: "light", label: "Sáng" }, { value: "dark", label: "Tối" }]} />
          </section>
          <section className="settings-section">
            <h3>Trợ lý</h3>
            <div className="facts">
              <span>Mô hình <b>{meta?.llm_model ?? "…"}</b></span>
              {meta?.llm_model_fallback && <span>Dự phòng <b>{meta.llm_model_fallback}</b></span>}
              {meta && !meta.llm_configured && <span className="badge bad">chưa cấu hình</span>}
            </div>
          </section>
          <section className="settings-section">
            <h3>Kỹ thuật</h3>
            <button onClick={() => { onClose(); nav("/model"); }}>Báo cáo mô hình <Icon name="chevron" /></button>
          </section>
          {isManager && <FastForward />}
        </div>
      </div>
    </div>
  );
}
