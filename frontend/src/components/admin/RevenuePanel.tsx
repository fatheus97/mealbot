import type { CSSProperties } from "react";
import type { RevenueStats, ThresholdProgress } from "../../types";

// Sits inside AdminDashboard's explicit light surface; every colour here is an
// explicit light-theme value paired with dark text, so it reads correctly in
// both OS colour schemes (.claude/rules/frontend.md).

function money(cents: number, currency = "eur"): string {
  const v = (cents / 100).toFixed(2);
  return currency === "eur" ? `€${v}` : `${v} ${currency.toUpperCase()}`;
}

function fmtThreshold(v: number, unit: string): string {
  const n = v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (unit === "EUR") return `€${n}`;
  if (unit === "CZK") return `${n} Kč`;
  return `${n} ${unit}`;
}

// Darkened shades so the fill has ≥3:1 contrast against the #e5e7eb track
// (WCAG 1.4.11 non-text contrast) in both OS colour schemes.
function barColor(pct: number): string {
  if (pct >= 1) return "#b91c1c"; // over the threshold
  if (pct >= 0.7) return "#b45309"; // approaching (≥70%)
  return "#15803d"; // comfortable
}

const th: CSSProperties = {
  textAlign: "left",
  padding: "0.3rem 0.75rem 0.3rem 0",
  color: "#6b7280",
  fontWeight: 600,
  borderBottom: "1px solid #e5e7eb",
};
const thR: CSSProperties = { ...th, textAlign: "right" };
const td: CSSProperties = { padding: "0.3rem 0.75rem 0.3rem 0", color: "#374151" };
const tdR: CSSProperties = { ...td, textAlign: "right" };

function ThresholdBar({ t }: { t: ThresholdProgress }) {
  const fill = Math.min(1, Math.max(0, t.pct));
  return (
    <div style={{ marginBottom: "0.9rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", fontSize: 13, marginBottom: 4 }}>
        <span style={{ fontWeight: 600, color: "#111827" }}>{t.label}</span>
        <span style={{ color: "#374151", whiteSpace: "nowrap" }}>
          {fmtThreshold(t.current, t.unit)} / {fmtThreshold(t.threshold, t.unit)} ({Math.round(t.pct * 100)}%)
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={Math.min(100, Math.round(t.pct * 100))}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={t.label}
        style={{ height: 10, background: "#e5e7eb", borderRadius: 6, overflow: "hidden" }}
      >
        <div style={{ width: `${fill * 100}%`, height: "100%", background: barColor(t.pct) }} />
      </div>
      <div style={{ fontSize: 11, color: "#6b7280", marginTop: 3 }}>{t.note}</div>
    </div>
  );
}

export function RevenuePanel({ stats }: { stats: RevenueStats }) {
  if (stats.sales_count === 0 && stats.non_eur_sales_count === 0) {
    return <div style={{ color: "#6b7280", fontSize: 13 }}>No sales recorded yet.</div>;
  }

  return (
    <div style={{ color: "#1f2937" }}>
      <div style={{ marginBottom: "1rem", maxWidth: 520 }}>
        {stats.thresholds.map((t) => (
          <ThresholdBar key={t.key} t={t} />
        ))}
      </div>

      <div style={{ display: "flex", gap: "1.25rem", flexWrap: "wrap", fontSize: 13, marginBottom: "1rem" }}>
        <span>
          <strong>{money(stats.total_cents)}</strong> total · {stats.sales_count} sales
        </span>
        <span>
          <strong>{money(stats.eu_cross_border_b2c_cents)}</strong> EU cross-border B2C
        </span>
        <span>
          <strong>{money(stats.cz_domestic_cents)}</strong> CZ domestic
        </span>
        {stats.non_eur_sales_count > 0 && (
          <span style={{ color: "#b45309" }}>
            {stats.non_eur_sales_count} non-EUR sale(s) excluded from totals
          </span>
        )}
      </div>

      {stats.by_country.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 13, marginBottom: "1rem" }}>
            <thead>
              <tr>
                <th style={th}>Country</th>
                <th style={th}>EU</th>
                <th style={thR}>Revenue</th>
                <th style={thR}>Sales</th>
              </tr>
            </thead>
            <tbody>
              {stats.by_country.map((c) => (
                <tr key={c.country ?? "unknown"}>
                  <td style={td}>{c.country ?? "—"}</td>
                  <td style={td}>{c.is_eu ? "🇪🇺" : ""}</td>
                  <td style={tdR}>{money(c.amount_cents)}</td>
                  <td style={tdR}>{c.sales}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {stats.recent.length > 0 && (
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          Recent:{" "}
          {stats.recent.map((r, i) => (
            <span key={i}>
              {r.country ?? "—"} {money(r.amount_cents, r.currency)}
              {r.is_business ? " (B2B)" : ""}
              {i < stats.recent.length - 1 ? " · " : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
