import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { AutoLoginAfterRegisterError } from "../contexts/authErrors";
import { SettingsPopup } from "./SettingsPopup";

export function AuthBar() {
  const { userId, email, login, logout, loginDemo, demoEnabled, register, registrationEnabled } = useAuth();
  const [inputEmail, setInputEmail] = useState(email);
  const [inputPassword, setInputPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const handleLogin = async () => {
    setLoading(true);
    setAuthError(null);
    try {
      await login(inputEmail, inputPassword);
      setInputPassword("");
    } catch (error) {
      console.error(error);
      setAuthError("Login failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async () => {
    // Surface a client-side guard before hitting the backend so the user
    // doesn't have to wait for a 422 to see "password too short".
    if (inputPassword.length < 8) {
      setAuthError("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    setAuthError(null);
    try {
      await register(inputEmail, inputPassword);
      setInputPassword("");
    } catch (error) {
      console.error(error);
      if (error instanceof AutoLoginAfterRegisterError) {
        // Crucial distinction: the account was created. Telling the user
        // "registration failed" here would get them to submit again and
        // hit a 409 on the duplicate email.
        setAuthError("Account created — please sign in to continue.");
      } else {
        // Neutral copy covers 403 (flag flipped), 409 (duplicate), 422
        // (weak password that passed the client guard), 5xx, etc.
        setAuthError("Registration failed. Please try again or contact info@trymealbot.com.");
      }
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
            <input
              value={inputEmail}
              onChange={e => { setInputEmail(e.target.value); setAuthError(null); }}
              placeholder="Email"
              style={{ padding: "0.5rem" }}
            />
            <input
              type="password"
              value={inputPassword}
              onChange={e => { setInputPassword(e.target.value); setAuthError(null); }}
              placeholder="Password"
              style={{ padding: "0.5rem" }}
            />
            <button onClick={handleLogin} disabled={loading} style={{ padding: "0.5rem 1rem" }}>
              {loading ? "..." : "Sign In"}
            </button>
            {registrationEnabled && (
              <button
                onClick={handleRegister}
                disabled={loading}
                style={{ padding: "0.5rem 1rem", backgroundColor: "#4a90d9", color: "white", border: "none", borderRadius: "4px" }}
              >
                {loading ? "..." : "Register"}
              </button>
            )}
            {demoEnabled && (
              <button
                onClick={async () => {
                  setLoading(true);
                  setAuthError(null);
                  try {
                    await loginDemo();
                  } catch {
                    setAuthError("Demo unavailable. Please try again.");
                  } finally {
                    setLoading(false);
                  }
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
      {!userId && authError && (
        <p role="alert" style={{ marginTop: "0.75rem", marginBottom: 0, color: "#b91c1c", fontSize: "0.85rem" }}>
          {authError}
        </p>
      )}
      {!userId && registrationEnabled === false && (
        <p style={{ marginTop: "0.75rem", fontSize: "0.85rem", color: "#555" }}>
          This is a closed alpha. For access, contact{" "}
          <a href="mailto:info@trymealbot.com" style={{ color: "#007bff" }}>info@trymealbot.com</a>.
        </p>
      )}
    </section>
  );
}
