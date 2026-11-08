import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, clearSession, getToken, getUser, saveSession, type User } from "./api";
import ErrorBoundary from "./components/ErrorBoundary";
import { dateVi } from "./format";
import Approvals from "./pages/Approvals";
import Audit from "./pages/Audit";
import Catalog from "./pages/Catalog";
import Dashboard from "./pages/Dashboard";
import Expiring from "./pages/Expiring";
import Home from "./pages/Home";
import Orders from "./pages/Orders";
import Reports from "./pages/Reports";

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
        <div className="brand" style={{ padding: "0 0 16px" }}>
          <Logo />
          <div>
            Ops Chest
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
        <button className="primary" style={{ width: "100%" }} disabled={busy || !u || !pw}>
          {busy ? "Đang đăng nhập…" : "Đăng nhập"}
        </button>
        <p className="small muted" style={{ marginTop: 12 }}>Tài khoản demo nằm trong file .env.example của dự án.</p>
      </form>
    </div>
  );
}

function Logo() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
      <rect x="4" y="9" width="24" height="18" rx="3" fill="var(--series-1)" />
      <rect x="4" y="5" width="24" height="7" rx="2" fill="var(--seq-550)" />
      <rect x="14" y="10" width="4" height="5" rx="1" fill="var(--surface-1)" />
    </svg>
  );
}

function Shell({ user }: { user: User }) {
  const nav = useNavigate();
  const location = useLocation();
  const [theme, setTheme] = useTheme();
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta") });
  const pending = useQuery({
    queryKey: ["pending-count"],
    queryFn: () => api<unknown[]>("/proposals?status=PENDING&limit=200"),
    refetchInterval: 30_000,
  });
  // Chat là cửa vào; các trang dữ liệu là đường dự phòng và để xem tổng quan
  const main: [string, string, number?][] = [
    ["/", "Trợ lý", undefined],
    ["/approvals", "Hộp duyệt", pending.data?.length],
  ];
  const data: [string, string][] = [
    ["/stats", "Số liệu tổng quan"],
    ["/expiring", "Hàng cận date"],
    ["/orders", "Đặt & nhận hàng"],
    ["/reports", "Phân tích"],
    ["/catalog", "Hàng hóa & NCC"],
    ["/audit", "Nhật ký"],
  ];
  const onAssistant = location.pathname === "/" || location.pathname.startsWith("/chat");
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <Logo />
          <div>
            Ops Chest
            <small>{meta.data?.store_name ?? "…"}</small>
          </div>
        </div>
        <nav className="nav">
          {main.map(([to, label, count]) => (
            <NavLink key={to} to={to} end={to === "/"} className={to === "/" ? (onAssistant ? "active" : "") : undefined}>
              {label}
              {count ? <span className="count">{count}</span> : null}
            </NavLink>
          ))}
          <div className="nav-section">Dữ liệu</div>
          {data.map(([to, label]) => (
            <NavLink key={to} to={to}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="foot">
          <div>
            Hôm nay: <b>{dateVi(meta.data?.today)}</b>
          </div>
          <div>
            LLM: {meta.data?.llm_model}{meta.data?.llm_model_fallback ? ` (phụ: ${meta.data.llm_model_fallback})` : ""} {meta.data && !meta.data.llm_configured && <span className="badge">chưa cấu hình</span>}
          </div>
          <div>
            {user.full_name} · {user.role === "manager" ? "Store Manager" : "Nhân viên"}
          </div>
          <div className="row">
            <select value={theme} onChange={(e) => setTheme(e.target.value)} aria-label="Giao diện">
              <option value="auto">Theo hệ thống</option>
              <option value="light">Sáng</option>
              <option value="dark">Tối</option>
            </select>
            <button className="sm" onClick={() => { clearSession(); nav("/login"); }}>
              Đăng xuất
            </button>
          </div>
        </div>
      </aside>
      <main className="main">
        <ErrorBoundary resetKey={location.pathname}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/chat" element={<Home />} />
          <Route path="/chat/:sid" element={<Home />} />
          <Route path="/stats" element={<Dashboard />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/expiring" element={<Expiring />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/catalog" element={<Catalog />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
        </ErrorBoundary>
      </main>
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
