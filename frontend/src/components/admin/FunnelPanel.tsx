import { BarChart, type Bar } from "./BarChart";
import type { FunnelStatsResponse } from "../../types";

/** Short chart labels keyed by stage; the table below carries the full ones. */
const SHORT_LABEL: Record<string, string> = {
  signed_up: "Signup",
  generated: "Generated",
  confirmed: "Confirmed",
  cooked: "Cooked",
  paid: "Subscribed",
};

function pct(part: number, whole: number): string {
  if (whole === 0) return "—";
  return `${Math.round((part / whole) * 1000) / 10}%`;
}

/**
 * Activation funnel: the overall signup→subscribed steps as a bar chart, the two
 * headline conversion rates, and a per-source breakdown table.
 *
 * Rendered inside AdminDashboard, which pins its own light surface, so explicit
 * colors here are safe in both OS colour schemes.
 */
export function FunnelPanel({ stats }: { stats: FunnelStatsResponse }) {
  const byKey = Object.fromEntries(stats.stages.map((s) => [s.key, s.count]));
  const signups = byKey.signed_up ?? 0;

  const bars: Bar[] = stats.stages.map((s) => ({
    label: SHORT_LABEL[s.key] ?? s.label,
    value: s.count,
  }));

  return (
    <div>
      <BarChart data={bars} color="#0d9488" height={140} />

      {/* The two numbers acquisition actually turns on. */}
      <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", marginTop: "1rem" }}>
        <ConversionStat
          label="Signup → activated"
          value={pct(byKey.generated ?? 0, signups)}
          sub="generated a recipe"
        />
        <ConversionStat
          label="Signup → subscribed"
          value={pct(byKey.paid ?? 0, signups)}
          sub="reached a paid plan"
        />
      </div>

      <div style={{ fontSize: 13, color: "#374151", margin: "1.5rem 0 0.5rem" }}>
        By acquisition source
      </div>
      {stats.by_source.length === 0 ? (
        <div style={{ color: "#9ca3af", fontSize: 13 }}>No signups yet.</div>
      ) : (
        // Wide table scrolls in its own container so the page body never does.
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13, minWidth: 480 }}>
            <thead>
              <tr>
                {["Source", "Signed up", "Generated", "Confirmed", "Cooked", "Subscribed"].map(
                  (h, i) => (
                    <th
                      key={h}
                      style={{
                        textAlign: i === 0 ? "left" : "right",
                        padding: "0.4rem 0.6rem",
                        borderBottom: "1px solid #e5e7eb",
                        color: "#6b7280",
                        fontWeight: 600,
                        whiteSpace: "nowrap",
                      }}
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {stats.by_source.map((row) => (
                <tr key={row.source}>
                  <td style={{ ...cellStyle, textAlign: "left", fontWeight: 600 }}>
                    {row.source}
                  </td>
                  <td style={cellStyle}>{row.signed_up}</td>
                  <td style={cellStyle}>{row.generated}</td>
                  <td style={cellStyle}>{row.confirmed}</td>
                  <td style={cellStyle}>{row.cooked}</td>
                  <td style={{ ...cellStyle, fontWeight: 600, color: "#0d9488" }}>
                    {row.paid}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const cellStyle: React.CSSProperties = {
  textAlign: "right",
  padding: "0.4rem 0.6rem",
  borderBottom: "1px solid #f3f4f6",
  color: "#111827",
  whiteSpace: "nowrap",
};

function ConversionStat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: "#6b7280", textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color: "#0d9488", marginTop: 2 }}>{value}</div>
      <div style={{ fontSize: 12, color: "#9ca3af" }}>{sub}</div>
    </div>
  );
}
