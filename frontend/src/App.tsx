import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, clearSession, getToken, getUser, saveSession, type User } from "./api";
import ErrorBoundary from "./components/ErrorBoundary";
import InboxPanel, { OPEN_INBOX_EVENT, openInbox } from "./components/InboxPanel";
import SettingsDialog from "./components/Settings";
import { TaskDialog } from "./components/Tasks";
import { useMediaQuery, useStoredState } from "./components/ui/hooks";
import { dateVi } from "./format";
import Audit from "./pages/Audit";
import ModelReport from "./pages/ModelReport";
import Catalog from "./pages/Catalog";
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
        <linearGradient id={g("bl")} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#16307a" /><stop offset="1" stopColor="#0a1a4a" /></linearGradient>
        <linearGradient id={g("br")} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#4f74f0" /><stop offset="1" stopColor="#1f4fe0" /></linearGradient>
        <linearGradient id={g("gl")} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#E1E5F2" /><stop offset="1" stopColor="#8fa8ff" /></linearGradient>
        <linearGradient id={g("ll")} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#7391ff" /><stop offset="1" stopColor="#2f5ef0" /></linearGradient>
        <linearGradient id={g("lr")} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#4f74f0" /><stop offset="1" stopColor="#1a3fb8" /></linearGradient>
        <linearGradient id={g("lt")} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#FFFFFF" /><stop offset="1" stopColor="#c7d4ff" /></linearGradient>
      </defs>
      <ellipse cx="24" cy="45" rx="15" ry="2.6" fill="#0c1424" opacity=".28" />
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
      <path d="M24 1.5l1.1 2.6 2.6 1.1-2.6 1.1L24 8.9l-1.1-2.6-2.6-1.1 2.6-1.1z" fill="#c7d4ff" />
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
  more: "M5 12h.01M12 12h.01M19 12h.01",
  down: "M6 9l6 6 6-6",
  collapse: "M15 6l-6 6 6 6M20 4v16",
  expand: "M9 6l6 6-6 6M4 4v16",
};

// Chat là nơi làm mọi việc (thẻ tác vụ trong luồng chat). Các trang dữ liệu chỉ để tra cứu / dự phòng khi LLM lỗi,
// nên nằm trong nhóm "Tra cứu" thu gọn.
const NAV: { section: string; items: [string, string][]; lookup?: boolean }[] = [
  // Hộp duyệt không nằm ở thanh bên: mở bằng nút ở thanh trên (máy tính) hoặc ô "Duyệt" ở thanh đáy (điện thoại)
  { section: "Làm việc", items: [["/", "Trợ lý"]] },
  { section: "Tra cứu", lookup: true, items: [["/expiring", "Hàng cận date"], ["/orders", "Đặt & nhận hàng"], ["/stockcount", "Kiểm kê"],
    ["/reports", "Phân tích"], ["/catalog", "Hàng hóa & NCC"], ["/audit", "Nhật ký"]] },
];
// Điện thoại: Trợ lý và Duyệt ở thanh đáy, trang tra cứu trong "Thêm"
const TABBAR: [string, string][] = [["/", "Trợ lý"], ["/approvals", "Duyệt"]];
// /model: báo cáo kỹ thuật (mô hình, mô phỏng), không nằm trong menu; mở từ menu tài khoản
const PAGE_TITLE: Record<string, string> = { ...Object.fromEntries(NAV.flatMap((g) => g.items)), "/model": "Báo cáo mô hình" };

function NavIcon({ to }: { to: keyof typeof ICON }) {
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
  const [settings, setSettings] = useState(false);
  const closeSettings = useCallback(() => setSettings(false), []);
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
          <button className="ghost menu-item" onClick={() => { setOpen(false); setSettings(true); }}>
            <svg viewBox="0 0 24 24" aria-hidden><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></svg>
            Cài đặt
          </button>
          <button onClick={() => { clearSession(); nav("/login"); }}>Đăng xuất</button>
        </div>
      )}
      <SettingsDialog open={settings} onClose={closeSettings} theme={theme} setTheme={setTheme} meta={meta} />
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
    queryFn: () => api<unknown[]>("/proposals?status=PENDING,FAILED&limit=200"),
    refetchInterval: 30_000,
  });
  const pendingN = pending.data?.length ?? 0;
  const [more, setMore] = useState(false);
  // Thanh bên: màn rộng (>=1280px) mở sẵn có chữ, màn hẹp hơn chỉ còn icon; người dùng bấm thu/mở thì nhớ lựa chọn
  const wide = useMediaQuery("(min-width: 1280px)");
  const [railPref, setRailPref] = useStoredState<"open" | "closed">("opschest_rail");
  const railOpen = railPref ? railPref === "open" : wide;
  const [lookupOpen, setLookupOpen] = useStoredState<"open" | "closed">("opschest_lookup");
  const onAssistant = location.pathname === "/" || location.pathname.startsWith("/chat");
  const pageTitle = onAssistant ? null : PAGE_TITLE[location.pathname];
  useEffect(() => {
    setDrawer(false);
    setMore(false);
  }, [location.pathname]);
  useEffect(() => {
    if (!drawer && !more) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setDrawer(false);
      setMore(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer, more]);
  // Mọi lối "duyệt" (menu, thanh đáy, menu Công việc, bản tin, địa chỉ cũ /approvals) đều mở ngăn này
  const [inbox, setInbox] = useState({ n: 0, type: "" });
  const openDrawer = (type = "") => {
    setInbox((s) => ({ n: s.n + 1, type }));
    setDrawer(true);
  };
  useEffect(() => {
    const open = (e: Event) => openDrawer((e as CustomEvent<{ type?: string }>).detail?.type ?? "");
    window.addEventListener(OPEN_INBOX_EVENT, open);
    return () => window.removeEventListener(OPEN_INBOX_EVENT, open);
  }, []);

  const link = (to: string, label: string, cls = "") => {
    const count = to === "/approvals" ? pendingN : 0;
    // Hộp duyệt không còn là trang riêng: mục menu này mở ngăn kéo, giữ nguyên trang đang xem
    if (to === "/approvals") {
      return (
        <button key={to} type="button" className={`nav-link ${cls} ${drawer ? "active" : ""}`} onClick={() => openDrawer()} aria-haspopup="dialog"
          title={railOpen ? undefined : label} aria-label={count ? `${label} (${count} chờ duyệt)` : label}>
          <NavIcon to={to} />
          <span className="nav-label">{label}</span>
          {count > 0 && <span className="count">{count}</span>}
        </button>
      );
    }
    return (
      <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `${cls} ${(to === "/" ? onAssistant : isActive) ? "active" : ""}`}
        title={railOpen ? undefined : label} aria-label={count ? `${label} (${count} chờ duyệt)` : label}>
        <NavIcon to={to} />
        <span className="nav-label">{label}</span>
        {count > 0 && <span className="count">{count}</span>}
      </NavLink>
    );
  };
  const moreActive = !onAssistant && !TABBAR.some(([to]) => to === location.pathname);

  const routes = (
    <ErrorBoundary resetKey={location.pathname}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/chat" element={<Home />} />
        <Route path="/chat/:sid" element={<Home />} />
        {/* Trang Tổng quan cũ chỉ lặp lại thông tin trang khác: địa chỉ cũ chuyển sang Phân tích */}
        <Route path="/stats" element={<Navigate to="/reports" replace />} />
        {/* Trang Hộp duyệt cũ: chuyển về Trợ lý và mở ngăn Hộp duyệt (giữ bộ lọc ?type=) */}
        <Route path="/approvals" element={<ApprovalsRedirect />} />
        <Route path="/expiring" element={<Expiring />} />
        <Route path="/orders" element={<Orders />} />
        <Route path="/stockcount" element={<StockCount />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/catalog" element={<Catalog />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/model" element={<ModelReport />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </ErrorBoundary>
  );

  return (
    <div className={`app ${railOpen ? "rail-open" : "rail-closed"}`}>
      <aside className="rail" aria-label="Điều hướng">
        <div className="brand">
          <Logo size={36} />
          <div className="nav-label">
            <Wordmark />
            <small>{meta.data?.store_name ?? "…"}</small>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((g) => {
            // Nhóm "Tra cứu" gập sẵn; tự mở khi đang ở một trang trong nhóm
            const inGroup = g.items.some(([to]) => to === location.pathname);
            const shown = !g.lookup || lookupOpen === "open" || inGroup;
            return (
              <div key={g.section} className={`nav-group ${g.lookup ? "lookup" : ""}`} role="group" aria-label={g.section}>
                {g.lookup ? (
                  <button className="nav-section nav-fold" onClick={() => setLookupOpen(shown ? "closed" : "open")} aria-expanded={shown}
                    title={shown ? "Thu gọn trang tra cứu" : "Mở trang tra cứu"}>
                    <NavIcon to={shown ? "down" : "more"} /><span className="nav-label">{g.section}</span>
                  </button>
                ) : (
                  <div className="nav-section">{g.section}</div>
                )}
                {shown && g.items.map(([to, label]) => link(to, label))}
              </div>
            );
          })}
        </nav>
        <button className="ghost rail-toggle" onClick={() => setRailPref(railOpen ? "closed" : "open")}
          aria-label={railOpen ? "Thu gọn thanh bên" : "Mở rộng thanh bên"} title={railOpen ? "Thu gọn" : "Mở rộng"}>
          <NavIcon to={railOpen ? "collapse" : "expand"} />
          <span className="nav-label">Thu gọn</span>
        </button>
      </aside>
      <div className="stage">
        <header className="topbar">
          <div className="crumb">
            <span className="crumb-store">{meta.data?.store_name ?? "Ops Chest"}</span>
            {pageTitle && <span className="crumb-page">{pageTitle}</span>}
            <span className="crumb-date hide-xs">{weekdayDate(meta.data?.today)}</span>
          </div>
          <span className="spacer" />
          <button onClick={() => setDrawer(true)} aria-haspopup="dialog" className="inbox-btn">
            Hộp duyệt {pendingN > 0 && <span className="count-pill">{pendingN}</span>}
          </button>
          <UserMenu user={user} meta={meta.data} theme={theme} setTheme={setTheme} />
        </header>
        <main className={`main ${onAssistant ? "chat-mode" : ""}`}>{onAssistant ? routes : <div className="page">{routes}</div>}</main>
      </div>

      <nav className="tabbar" aria-label="Điều hướng nhanh">
        {TABBAR.map(([to, label]) => link(to, label, "tab"))}
        <button className={`tab ${moreActive || more ? "active" : ""}`} onClick={() => setMore((m) => !m)} aria-expanded={more} aria-haspopup="dialog">
          <NavIcon to="more" />
          <span className="nav-label">Thêm</span>
        </button>
      </nav>
      <div className={`sheet ${more ? "on" : ""}`} role="dialog" aria-label="Các trang khác" aria-hidden={!more}>
        {NAV.map((g) => {
          const rest = g.items.filter(([to]) => !TABBAR.some(([t]) => t === to));
          return rest.length ? (
            <div key={g.section} className="nav-group">
              <div className="nav-section">{g.section}</div>
              {rest.map(([to, label]) => link(to, label, "sheet-link"))}
            </div>
          ) : null;
        })}
      </div>

      <TaskDialog />
      <div className={`scrim ${drawer || more ? "on" : ""}`} onClick={() => { setDrawer(false); setMore(false); }} />
      <aside className={`drawer ${drawer ? "on" : ""}`} aria-label="Hộp duyệt" aria-hidden={!drawer}>
        <div className="drawer-head">
          <h2>Hộp duyệt</h2>
          <span className="spacer" />
          <button className="icon ghost" onClick={() => setDrawer(false)} aria-label="Đóng">
            <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
        <div className="drawer-body">
          <InboxPanel key={inbox.n} initialType={inbox.type} />
        </div>
      </aside>
    </div>
  );
}

// Địa chỉ cũ /approvals[?type=...]: về trang Trợ lý rồi mở ngăn Hộp duyệt. Mở sau khi đổi trang,
// vì đổi trang thì Shell đóng ngăn kéo.
function ApprovalsRedirect() {
  const nav = useNavigate();
  const location = useLocation();
  useEffect(() => {
    const type = new URLSearchParams(location.search).get("type") ?? "";
    nav("/", { replace: true });
    // Không huỷ hẹn giờ khi gỡ: component này bị gỡ ngay khi đổi trang, huỷ thì ngăn kéo không bao giờ mở
    window.setTimeout(() => openInbox(type), 50);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
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
