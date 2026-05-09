import { Link, Outlet, useNavigate, useLocation } from "react-router-dom";
import { logout } from "../api/auth";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";

function NAV_ITEMS_FROM_T(t: { nav_upload: string; nav_history: string; nav_batch: string; nav_rules: string; nav_monitor: string }) {
  return [
    { to: "/upload", label: t.nav_upload },
    { to: "/history", label: t.nav_history },
    { to: "/batch", label: t.nav_batch },
    { to: "/rules", label: t.nav_rules },
    { to: "/monitor", label: t.nav_monitor },
  ];
}

export default function Layout() {
  const nav = useNavigate();
  const { pathname } = useLocation();
  const { user, setUser } = useAuth();
  const { t, lang, toggleLang } = useI18n();

  const actualUser = user;

  const handleLogout = async () => {
    try { await logout(); } catch { /* ignore */ }
    setUser(null);
    nav("/login");
  };

  const displayName = actualUser?.nickname || actualUser?.username || "";
  const initial = displayName.charAt(0).toUpperCase();
  const avatarUrl = actualUser?.avatar;

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: "system-ui, sans-serif" }}>
      {/* 侧边栏 */}
      <nav
        style={{
          width: 200, background: "#1e293b", color: "#e2e8f0",
          padding: "24px 0", display: "flex", flexDirection: "column",
          flexShrink: 0,
        }}
      >
        <div style={{ padding: "0 20px 20px", fontWeight: 700, fontSize: 15, color: "#f8fafc", borderBottom: "1px solid #334155", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span>{t.app_title}</span>
          <button
            onClick={toggleLang}
            title={lang === "zh" ? "Switch to English" : "切换到中文"}
            style={{
              background: "#334155", border: "none", borderRadius: 4,
              color: "#94a3b8", cursor: "pointer", fontSize: 12,
              padding: "2px 6px", fontWeight: 600,
            }}
          >
            {lang === "zh" ? "EN" : "中"}
          </button>
        </div>
        <div style={{ flex: 1, paddingTop: 12 }}>
          {NAV_ITEMS_FROM_T(t).map(({ to, label }) => (
            <Link
              key={to}
              to={to}
              style={{
                display: "block", padding: "10px 20px", fontSize: 14,
                color: pathname.startsWith(to) && (to !== "/" || pathname === "/") ? "#60a5fa" : "#94a3b8",
                background: pathname.startsWith(to) && (to !== "/" || pathname === "/") ? "#1e3a5f" : "transparent",
                textDecoration: "none", transition: "all 0.15s",
                borderLeft: pathname.startsWith(to) && (to !== "/" || pathname === "/") ? "3px solid #3b82f6" : "3px solid transparent",
              }}
            >
              {label}
            </Link>
          ))}
        </div>
        {/* 用户信息区 */}
        {actualUser && (
          <div style={{ padding: "12px 20px", borderTop: "1px solid #334155", display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ width: 32, height: 32, borderRadius: "50%", background: "#3b82f6", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 600, flexShrink: 0, overflow: "hidden" }}>
              {avatarUrl ? (
                <img src={avatarUrl} alt="" style={{ width: 32, height: 32, objectFit: "cover" }} onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
              ) : (
                initial
              )}
            </div>
            <div style={{ overflow: "hidden" }}>
              <div style={{ color: "#f1f5f9", fontSize: 13, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{displayName}</div>
              <div style={{ color: "#64748b", fontSize: 11 }}>{t.logged_in}</div>
            </div>
          </div>
        )}
        <div style={{ padding: "12px 20px", borderTop: actualUser ? "1px solid #334155" : "none" }}>
          <button
            onClick={handleLogout}
            style={{
              width: "100%", background: "none", border: "1px solid #475569",
              color: "#94a3b8", padding: "8px 12px", borderRadius: 6,
              cursor: "pointer", fontSize: 13,
            }}
          >
            {t.logout}
          </button>
        </div>
      </nav>

      {/* 主内容 */}
      <main style={{ flex: 1, padding: 32, background: "#f8fafc", overflow: "auto" }}>
        <Outlet />
      </main>
    </div>
  );
}