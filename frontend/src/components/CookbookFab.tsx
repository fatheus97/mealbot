import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useCookbookCount } from "../hooks/useServerState";
import { CookbookModal } from "./CookbookModal";

// Floating book icon, fixed bottom-right. Shows the favorites count as a
// badge so the user can tell at a glance how full their cookbook is.
export function CookbookFab() {
  const { userId } = useAuth();
  const { data: countData } = useCookbookCount(userId);
  const [open, setOpen] = useState(false);

  if (!userId) return null;
  const count = countData?.count ?? 0;

  return (
    <>
      <button
        type="button"
        aria-label="Open cookbook"
        onClick={() => setOpen(true)}
        style={{
          position: "fixed",
          bottom: "1.5rem",
          right: "1.5rem",
          width: "56px",
          height: "56px",
          borderRadius: "50%",
          backgroundColor: "#7c2d12",
          color: "white",
          border: "none",
          fontSize: "1.6rem",
          cursor: "pointer",
          boxShadow: "0 4px 14px rgba(0,0,0,0.25)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 50,
        }}
      >
        📖
        {count > 0 && (
          <span
            aria-hidden
            style={{
              position: "absolute",
              top: "-4px",
              right: "-4px",
              minWidth: "22px",
              height: "22px",
              padding: "0 6px",
              borderRadius: "11px",
              backgroundColor: "#f59e0b",
              color: "#1f2937",
              fontSize: "0.75rem",
              fontWeight: 700,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: "2px solid white",
            }}
          >
            {count}
          </span>
        )}
      </button>

      {open && <CookbookModal onClose={() => setOpen(false)} />}
    </>
  );
}
