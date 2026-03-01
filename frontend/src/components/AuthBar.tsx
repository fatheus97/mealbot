import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";

export function AuthBar() {
  const { userId, email, login, logout } = useAuth();
  const [inputEmail, setInputEmail] = useState(email);
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setLoading(true);
    try {
      await login(inputEmail);
    } catch (err) {
      console.error("Authentication error:", err);
      alert("Login failed. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section style={{ marginBottom: "1.5rem", padding: "1rem", backgroundColor: "#f0f8ff", color: "#111", borderRadius: "8px" }}>
      <h2>Authentication</h2>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <input
          value={inputEmail}
          onChange={e => setInputEmail(e.target.value)}
          placeholder="Enter email"
          style={{ padding: "0.5rem" }}
        />
        <button onClick={handleLogin} disabled={loading} style={{ padding: "0.5rem 1rem" }}>
          {loading ? "Working..." : "Login / Register"}
        </button>
        {userId && (
          <button onClick={logout} style={{ padding: "0.5rem 1rem", backgroundColor: "#ff4d4d", color: "white", border: "none" }}>
            Logout
          </button>
        )}
      </div>
      <p style={{ marginTop: "0.5rem", fontWeight: "bold" }}>
        Status: {userId ? `✅ Logged in as User #${userId} (${email})` : "❌ Logged out"}
      </p>
    </section>
  );
}