import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { SettingsPopup } from "./SettingsPopup";

export function AuthBar() {
  const { userId, email, login, logout, loginDemo, demoEnabled } = useAuth();
  const [inputEmail, setInputEmail] = useState(email);
  const [inputPassword, setInputPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const handleLogin = async () => {
    setLoading(true);
    try {
      await login(inputEmail, inputPassword);
      setInputPassword("");
    } catch (error) {
      console.error(error);
      alert("Login failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section style={{ marginBottom: "1.5rem", padding: "1rem", backgroundColor: "#f0f8ff", color: "#111", borderRadius: "8px" }}>
      <h2>{userId ? "Welcome" : "Login"}</h2>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        {!userId && (
          <>
            <input value={inputEmail} onChange={e => setInputEmail(e.target.value)} placeholder="Email" style={{ padding: "0.5rem" }} />
            <input type="password" value={inputPassword} onChange={e => setInputPassword(e.target.value)} placeholder="Password" style={{ padding: "0.5rem" }} />
            <button onClick={handleLogin} disabled={loading} style={{ padding: "0.5rem 1rem" }}>
              {loading ? "..." : "Sign In"}
            </button>
            {demoEnabled && (
              <button
                onClick={async () => {
                  setLoading(true);
                  try { await loginDemo(); }
                  catch { alert("Demo unavailable. Please try again."); }
                  finally { setLoading(false); }
                }}
                disabled={loading}
                title="No signup needed — explore with mocked data."
                style={{ padding: "0.5rem 1rem", backgroundColor: "#2e7d32", color: "white", border: "none", borderRadius: "4px" }}
              >
                {loading ? "..." : "Try Demo"}
              </button>
            )}
          </>
        )}
        {userId && (
          <div style={{ display: "flex", gap: "1rem", alignItems: "center", position: "relative" }}>
             <span>✅ {email}</span>
             <button
               onClick={() => setShowSettings(!showSettings)}
               style={{ background: "none", border: "none", fontSize: "1.3rem", cursor: "pointer", padding: "0.25rem" }}
               aria-label="Settings"
               title="Settings"
             >
               ⚙️
             </button>
             <button onClick={logout} style={{ padding: "0.5rem 1rem", backgroundColor: "#ff4d4d", color: "white", border: "none", borderRadius: "4px" }}>Logout</button>
             {showSettings && <SettingsPopup onClose={() => setShowSettings(false)} />}
          </div>
        )}
      </div>
      {!userId && (
        <p style={{ marginTop: "0.75rem", fontSize: "0.85rem", color: "#555" }}>
          This is a closed alpha. For access, contact{" "}
          <a href="mailto:info@trymealbot.com" style={{ color: "#007bff" }}>info@trymealbot.com</a>.
        </p>
      )}
    </section>
  );
}
