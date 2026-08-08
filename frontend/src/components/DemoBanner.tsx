import { useAuth } from "../contexts/AuthContext";
import { useI18n } from "../i18n";

export function DemoBanner() {
  const { isDemo } = useAuth();
  const { t } = useI18n();

  if (!isDemo) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        boxSizing: "border-box",
        background: "#1565c0",
        color: "white",
        padding: "0.5rem 1rem",
        textAlign: "center",
        zIndex: 1000,
        fontSize: "0.875rem",
      }}
    >
      {t("demo.banner")}
    </div>
  );
}
