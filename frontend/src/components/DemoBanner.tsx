import { useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";

export function DemoBanner() {
  const { isDemo } = useAuth();
  const [blocked, setBlocked] = useState(false);
  const [fading, setFading] = useState(false);

  useEffect(() => {
    const handler = () => {
      setBlocked(true);
      setFading(false);
      setTimeout(() => setFading(true), 2000);
      setTimeout(() => { setBlocked(false); setFading(false); }, 2500);
    };
    window.addEventListener("mealbot:demo-blocked", handler);
    return () => window.removeEventListener("mealbot:demo-blocked", handler);
  }, []);

  if (!isDemo) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        background: blocked ? "#e65100" : "#1565c0",
        color: "white",
        padding: "0.5rem 1rem",
        textAlign: "center",
        zIndex: 1000,
        fontSize: "0.875rem",
        transition: "background 0.3s, opacity 0.5s",
        opacity: fading ? 0.4 : 1,
      }}
    >
      {blocked
        ? "Editing is disabled in demo mode"
        : "Demo mode — generate plans, cook meals, and rate them. Saving changes is disabled."}
    </div>
  );
}
