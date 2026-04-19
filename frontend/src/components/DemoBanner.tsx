import { useAuth } from "../contexts/AuthContext";

export function DemoBanner() {
  const { isDemo } = useAuth();

  if (!isDemo) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        background: "#1565c0",
        color: "white",
        padding: "0.5rem 1rem",
        textAlign: "center",
        zIndex: 1000,
        fontSize: "0.875rem",
      }}
    >
      Demo mode — generate plans, cook and rate meals. Your session and all changes are auto-deleted in 2 hours.
    </div>
  );
}
