import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login, register } from "../api/auth";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";

export default function LoginPage() {
  const nav = useNavigate();
  const { setUser } = useAuth();
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const fn = mode === "login" ? login : register;
      const res = await fn(username, password);
      setUser(res.data);
      nav("/upload");
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? t.operation_failed);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f3f4f6" }}>
      <div style={{ width: 380, padding: 40, background: "#fff", borderRadius: 12, boxShadow: "0 4px 24px rgba(0,0,0,0.08)" }}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>🏭</div>
          <h2 style={{ margin: 0, fontSize: 20, color: "#111827" }}>{t.login_title}</h2>
          <p style={{ margin: "8px 0 0", fontSize: 13, color: "#6b7280" }}>
            {mode === "login" ? t.login_subtitle_login : t.login_subtitle_register}
          </p>
        </div>

        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <label style={{ fontSize: 13, color: "#374151", fontWeight: 500 }}>{t.username}</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={2}
              placeholder={t.username_placeholder}
              style={{ display: "block", width: "100%", marginTop: 6, padding: "10px 12px", border: "1px solid #d1d5db", borderRadius: 6, fontSize: 14, boxSizing: "border-box" }}
            />
          </div>
          <div>
            <label style={{ fontSize: 13, color: "#374151", fontWeight: 500 }}>{t.password}</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              placeholder={t.password_placeholder}
              style={{ display: "block", width: "100%", marginTop: 6, padding: "10px 12px", border: "1px solid #d1d5db", borderRadius: 6, fontSize: 14, boxSizing: "border-box" }}
            />
          </div>

          {error && (
            <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 6, padding: "10px 14px", fontSize: 13, color: "#dc2626" }}>
              {error}
            </div>
          )}

          {mode === "register" && (
            <div style={{ background: "#f0f9ff", border: "1px solid #bae6fd", borderRadius: 6, padding: "8px 12px", fontSize: 12, color: "#0369a1" }}>
              <strong>{t.password_req}</strong>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              background: loading ? "#93c5fd" : "#2563eb",
              color: "#fff", border: "none",
              padding: "12px", borderRadius: 6,
              fontWeight: 600, fontSize: 15,
              cursor: loading ? "not-allowed" : "pointer",
              marginTop: 4,
            }}
          >
            {loading ? t.processing : mode === "login" ? t.login_btn : t.register_btn}
          </button>
        </form>

        <p style={{ marginTop: 24, textAlign: "center", fontSize: 13, color: "#6b7280" }}>
          {mode === "login" ? t.no_account : t.has_account}
          <button
            onClick={() => { setMode(m => (m === "login" ? "register" : "login")); setError(""); }}
            style={{ background: "none", border: "none", color: "#2563eb", cursor: "pointer", fontWeight: 600 }}
          >
            {mode === "login" ? t.go_register : t.go_login}
          </button>
        </p>
      </div>
    </div>
  );
}