import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, clearSession, getToken, getUser, saveSession, type User } from "./api";
import ErrorBoundary from "./components/ErrorBoundary";
import InboxPanel from "./components/InboxPanel";
import { dateVi } from "./format";
import Approvals from "./pages/Approvals";
import Audit from "./pages/Audit";
import Catalog from "./pages/Catalog";
import Dashboard from "./pages/Dashboard";
import Expiring from "./pages/Expiring";
import Home from "./pages/Home";
import Orders from "./pages/Orders";
import Reports from "./pages/Reports";
import StockCount from "./pages/StockCount";

type Meta = { today: string; store_name: string; llm_model: string; llm_model_fallback: string | null; llm_configured: boolean };

function useTheme() {
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem("opschest_theme") || "auto";
    } catch {
      return "auto";
    }
  });
  useEffect(() => {
    const el = document.documentElement;
    if (theme === "auto") el.removeAttribute("data-theme");
    else el.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("opschest_theme", theme);
    } catch {
      /* bo qua */
    }
  }, [theme]);
  return [theme, setTheme] as const;
}

// Logo: chiếc rương 3D nhìn theo góc đẳng cự, màu cố định để giống nhau ở cả hai giao diện
export function Logo({ size = 40 }: { size?: number }) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const g = (n: string) => `${n}${uid}`;
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden>
      <defs>
        <linearGradient id={g("bl")} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#0E4A5E" /><stop offset="1" stopColor="#033142" /></linearGradient>
        <linearGradient id={g("br")} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#2A93A8" /><stop offset="1" stopColor="#16616F" /></linearGradient>
        <linearGradient id={g("gl")} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#E1E5F2" /><stop offset="1" stopColor="#7FC4D6" /></linearGradient>
        <linearGradient id={g("ll")} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#5FB6C8" /><stop offset="1" stopColor="#1F7A8C" /></linearGradient>
        <linearGradient id={g("lr")} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#2E97AB" /><stop offset="1" stopColor="#145C6B" /></linearGradient>
        <linearGradient id={g("lt")} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#FFFFFF" /><stop offset="1" stopColor="#BFDBF7" /></linearGradient>
      </defs>
      <ellipse cx="24" cy="45" rx="15" ry="2.6" fill="#022B3A" opacity=".28" />
      <polygon points="10,27 24,34 24,44 10,37" fill={`url(#${g("bl")})`} />
      <polygon points="24,34 38,27 38,37 24,44" fill={`url(#${g("br")})`} />
      <polygon points="24,20 38,27 24,34 10,27" fill={`url(#${g("gl")})`} />
      <polygon points="10,14 24,21 24,28 10,21" fill={`url(#${g("ll")})`} />
      <polygon points="24,21 38,14 38,21 24,28" fill={`url(#${g("lr")})`} />
      <polygon points="24,7 38,14 24,21 10,14" fill={`url(#${g("lt")})`} />
      <polyline points="10,14 24,21 38,14" fill="none" stroke="#fff" strokeOpacity=".55" strokeWidth=".8" strokeLinejoin="round" />
      <polyline points="10,27 24,34 38,27" fill="none" stroke="#fff" strokeOpacity=".25" strokeWidth=".8" strokeLinejoin="round" />
      <polygon points="28,33.5 32,31.5 32,36.5 28,38.5" fill="#E1E5F2" />
      <polygon points="28,33.5 32,31.5 32,32.6 28,34.6" fill="#fff" opacity=".7" />
      <path d="M24 1.5l1.1 2.6 2.6 1.1-2.6 1.1L24 8.9l-1.1-2.6-2.6-1.1 2.6-1.1z" fill="#BFDBF7" />
    </svg>
  );
}

function Wordmark() {
  return (
    <span className="wm">
      Ops<b>Chest</b>
    </span>
  );
}

function Login() {
  const nav = useNavigate();
  const [u, setU] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api<{ token: string; user: User }>("/auth/login", { method: "POST", body: { username: u, password: pw } });
      saveSession(r.token, r.user);
      nav("/");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <div className="brand" style={{ marginBottom: 18 }}>
          <Logo />
          <div>
            <Wordmark />
            <small>Trợ lý kho &amp; hạn sử dụng</small>
          </div>
        </div>
        <label>
          Tên đăng nhập
          <input value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" autoFocus />
        </label>
        <label>
          Mật khẩu
          <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" />
        </label>
        {err && <div className="alert error" style={{ marginBottom: 12 }}>{err}</div>}
        <button className="primary" style={{ width: "100%", height: 38 }} disabled={busy || !u || !pw}>
          {busy ? "Đang đăng nhập…" : "Đăng nhập"}
        </button>
        <p className="small muted" style={{ marginTop: 12 }}>Tài khoản demo nằm trong file .env.example của dự án.</p>
      </form>
    </div>
  );
}

// Biểu tượng nét đơn giản cho thanh bên
const ICON: Record<string, string> = {
  "/": "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z",
  "/approvals": "M4 13l2.5-7h11L20 13v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-5ZM4 13h4.5l1 2h5l1-2H20",
  "/stats": "M3 12h4l3-8 4 16 3-8h4",
  "/expiring": "M12 5a8 8 0 1 0 0 16 8 8 0 0 0 0-16ZM12 9v4l2.5 2M9.5 2.5h5",
  "/orders": "M3 7l9-4 9 4-9 4-9-4ZM3 12l9 4 9-4M3 17l9 4 9-4",
  "/stockcount": "M9 5h6v3H9zM6 6h3M15 6h3v15H6V6M9 13l2 2 4-4",
  "/reports": "M4 20V10M10 20V4M16 20v-7M22 20H2",
  "/catalog": "M4 7h16v13H4zM8 7V4h8v3",
  "/audit": "M6 3h12v18H6zM9 8h6M9 12h6M9 16h3",
};

function NavIcon({ to }: { to: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden>
      <path d={ICON[to]} />
    </svg>
  );
}

function weekdayDate(iso?: string): string {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return dateVi(iso);
  const wd = d.toLocaleDateString("vi-VN", { weekday: "long" });
  return `${wd.charAt(0).toUpperCase()}${wd.slice(1)}, ${dateVi(iso)}`;
}

function UserMenu({ user, meta, theme, setTheme }: { user: User; meta?: Meta; theme: string; setTheme: (t: string) => void }) {
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const initials = user.full_name.split(/\s+/).slice(-2).map((w) => w.charAt(0)).join("").toUpperCase();
  return (
    <div className="menu-wrap" ref={ref}>
      <button className="avatar" onClick={() => setOpen((o) => !o)} aria-label="Tài khoản" aria-expanded={open}>
        {initials}
      </button>
      {open && (
        <div className="menu">
          <div>
            <b>{user.full_name}</b>
            <span className="muted">{user.role === "manager" ? "Store Manager" : "Nhân viên"}</span>
          </div>
          <label className="secondary">
            Giao diện
            <select value={theme} onChange={(e) => setTheme(e.target.value)} aria-label="Giao diện">
              <option value="auto">Theo hệ thống</option>
              <option value="light">Sáng</option>
              <option value="dark">Tối</option>
            </select>
          </label>
          <div className="muted small">
            LLM: {meta?.llm_model}
            {meta?.llm_model_fallback ? ` (phụ: ${meta.llm_model_fallback})` : ""} {meta && !meta.llm_configured && <span className="badge">chưa cấu hình</span>}
          </div>
          <button onClick={() => { clearSession(); nav("/login"); }}>Đăng xuất</button>
        </div>
      )}
    </div>
  );
}

function Shell({ user }: { user: User }) {
  const location = useLocation();
  const [theme, setTheme] = useTheme();
  const [drawer, setDrawer] = useState(false);
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta") });
  const pending = useQuery({
    queryKey: ["pending-count"],
    queryFn: () => api<unknown[]>("/proposals?status=PENDING&limit=200"),
    refetchInterval: 30_000,
  });
  const pendingN = pending.data?.length ?? 0;
  // Chat là cửa vào; các trang dữ liệu là đường dự phòng và để xem tổng quan
  const main: [string, string, number?][] = [
    ["/", "Trợ lý", undefined],
    ["/approvals", "Hộp duyệt", pendingN],
  ];
  const data: [string, string][] = [
    ["/stats", "Số liệu tổng quan"],
    ["/expiring", "Hàng cận date"],
    ["/orders", "Đặt & nhận hàng"],
    ["/stockcount", "Kiểm kê"],
    ["/reports", "Phân tích"],
    ["/catalog", "Hàng hóa & NCC"],
    ["/audit", "Nhật ký"],
  ];
  const onAssistant = location.pathname === "/" || location.pathname.startsWith("/chat");
  useEffect(() => setDrawer(false), [location.pathname]);
  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer]);

  const link = (to: string, label: string, count?: number) => (
    <NavLink key={to} to={to} end={to === "/"} className={to === "/" ? (onAssistant ? "active" : "") : undefined} title={label}>
      <NavIcon to={to} />
      <span className="nav-label">{label}</span>
      {count ? <span className="count">{count}</span> : null}
    </NavLink>
  );

  const routes = (
    <ErrorBoundary resetKey={location.pathname}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/chat" element={<Home />} />
        <Route path="/chat/:sid" element={<Home />} />
        <Route path="/stats" element={<Dashboard />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/expiring" element={<Expiring />} />
        <Route path="/orders" element={<Orders />} />
        <Route path="/stockcount" element={<StockCount />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/catalog" element={<Catalog />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </ErrorBoundary>
  );

  return (
    <div className="app">
      <aside className="rail" aria-label="Điều hướng">
        <div className="brand">
          <Logo />
          <div className="nav-label">
            <Wordmark />
            <small>{meta.data?.store_name ?? "…"}</small>
          </div>
        </div>
        <nav className="nav">
          {main.map(([to, label, count]) => link(to, label, count))}
          <div className="nav-section">Dữ liệu</div>
          {data.map(([to, label]) => link(to, label))}
        </nav>
      </aside>
      <div className="stage">
        <header className="topbar">
          <div className="crumb">
            {meta.data?.store_name ?? "Ops Chest"}
            <span className="hide-xs">{weekdayDate(meta.data?.today)}</span>
          </div>
          <span className="spacer" />
          <button onClick={() => setDrawer(true)} aria-haspopup="dialog">
            Hộp duyệt {pendingN > 0 && <span className="count-pill">{pendingN}</span>}
          </button>
          <UserMenu user={user} meta={meta.data} theme={theme} setTheme={setTheme} />
        </header>
        <main className={`main ${onAssistant ? "chat-mode" : ""}`}>{onAssistant ? routes : <div className="page">{routes}</div>}</main>
      </div>

      <div className={`scrim ${drawer ? "on" : ""}`} onClick={() => setDrawer(false)} />
      <aside className={`drawer ${drawer ? "on" : ""}`} aria-label="Hộp duyệt" aria-hidden={!drawer}>
        <div className="drawer-head">
          <h2>Hộp duyệt</h2>
          <span className="spacer" />
          <button className="icon ghost" onClick={() => setDrawer(false)} aria-label="Đóng">
            <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
        <div className="drawer-body">
          <InboxPanel onNavigate={() => setDrawer(false)} />
        </div>
      </aside>
    </div>
  );
}

// Doc lai phien moi lan route render (khong cache o App, neu khong sau dang nhap van thay user = null)
function Protected() {
  const user = getUser();
  return getToken() && user ? <Shell user={user} /> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={<Protected />} />
    </Routes>
  );
}
