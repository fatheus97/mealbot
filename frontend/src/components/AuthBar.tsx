import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import {authFetch} from "../api.ts";

export function AuthBar() {
  const { userId, email, login, logout } = useAuth();
  const [inputEmail, setInputEmail] = useState(email);
  const [inputPassword, setInputPassword] = useState("");
  const [isRegistering, setIsRegistering] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleAuth = async () => {
    setLoading(true);
    try {
      // FIX: Use the 'endpoint' variable in the fetch call below
      const endpoint = isRegistering ? "register" : "login";

      if (isRegistering) {
        const regResp = await authFetch(`/users/${endpoint}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: inputEmail, password: inputPassword })
        });
        if (!regResp.ok) {
           alert("Registration failed. Email might already be in use.");
           setLoading(false);
           return;
        }
        alert("Registered! Now logging you in...");
      }

      await login(inputEmail, inputPassword);
      setInputPassword("");
    } catch (error) {
      console.error(error);
      alert("Auth failed. Check credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section style={{ marginBottom: "1.5rem", padding: "1rem", backgroundColor: "#f0f8ff", color: "#111", borderRadius: "8px" }}>
      <h2>{userId ? "Welcome" : isRegistering ? "Create Account" : "Login"}</h2>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        {!userId && (
          <>
            <input value={inputEmail} onChange={e => setInputEmail(e.target.value)} placeholder="Email" style={{ padding: "0.5rem" }} />
            <input type="password" value={inputPassword} onChange={e => setInputPassword(e.target.value)} placeholder="Password" style={{ padding: "0.5rem" }} />
            <button onClick={handleAuth} disabled={loading} style={{ padding: "0.5rem 1rem" }}>
              {loading ? "..." : isRegistering ? "Sign Up" : "Sign In"}
            </button>
            <button onClick={() => setIsRegistering(!isRegistering)} style={{ fontSize: "0.8rem", color: "#111", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
              {isRegistering ? "Back to Login" : "Need an Account?"}
            </button>
          </>
        )}
        {userId && (
          <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
             <span>✅ {email}</span>
             <button onClick={logout} style={{ padding: "0.5rem 1rem", backgroundColor: "#ff4d4d", color: "white", border: "none", borderRadius: "4px" }}>Logout</button>
          </div>
        )}
      </div>
    </section>
  );
}