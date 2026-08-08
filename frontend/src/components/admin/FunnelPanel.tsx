import { BarChart, type Bar } from "./BarChart";
import { chart, colors } from "./theme";
import type { FunnelStatsResponse } from "../../types";

/** Short chart labels keyed by stage; the table below carries the full ones. */
const SHORT_LABEL: Record<string, string> = {
  signed_up: "Signup",
  verified: "Verified",
  generated: "Generated",
  confirmed: "Confirmed",
  cooked: "Cooked",
  subscribed: "Subscribed",
  paid: "Paid",
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
      <BarChart data={bars} color={chart.funnel} height={140} />

      {/* The two numbers acquisition actually turns on. Subscription is read
          off `subscribed`, not `paid`: paid invoices cannot exist for a
          cohort's first 10 days (the trial-opening invoice is zero-amount and
          the ledger rejects it), so a headline rate keyed on `paid` would
          report 0% through exactly the window a launch is judged on. `paid`
          is still on the chart and in the table. */}
      <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", marginTop: "1rem" }}>
        <ConversionStat
          label="Signup → activated"
          value={pct(byKey.generated ?? 0, signups)}
          sub="generated a recipe"
        />
        <ConversionStat
          label="Signup → subscribed"
          value={pct(byKey.subscribed ?? 0, signups)}
          sub="started a subscription, trials included"
        />
      </div>

      <div style={{ fontSize: 13, color: colors.textBody, margin: "1.5rem 0 0.5rem" }}>
        By acquisition source
      </div>
      {stats.by_source.length === 0 ? (
        <div style={{ color: colors.textMuted, fontSize: 13 }}>No signups yet.</div>
      ) : (
        // Wide table scrolls in its own container so the page body never does.
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13, minWidth: 660 }}>
            <thead>
              <tr>
                {[
                  "Source",
                  "Signed up",
                  "Verified",
                  "Generated",
                  "Confirmed",
                  "Cooked",
                  "Subscribed",
                  "Paid",
                ].map((h, i) => (
                  <th
                    key={h}
                    style={{
                      textAlign: i === 0 ? "left" : "right",
                      padding: "0.4rem 0.6rem",
                      borderBottom: `1px solid ${colors.border}`,
                      color: colors.textMuted,
                      fontWeight: 600,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stats.by_source.map((row) => (
                <tr key={row.source}>
                  <td style={{ ...cellStyle, textAlign: "left", fontWeight: 600 }}>
                    {row.source}
                  </td>
                  <td style={cellStyle}>{row.signed_up}</td>
                  <td style={cellStyle}>{row.verified}</td>
                  <td style={cellStyle}>{row.generated}</td>
                  <td style={cellStyle}>{row.confirmed}</td>
                  <td style={cellStyle}>{row.cooked}</td>
                  <td style={{ ...cellStyle, fontWeight: 600, color: chart.funnel }}>
                    {row.subscribed}
                  </td>
                  <td style={cellStyle}>{row.paid}</td>
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
  borderBottom: `1px solid ${colors.borderSubtle}`,
  color: colors.text,
  whiteSpace: "nowrap",
};

function ConversionStat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: colors.textMuted, textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color: chart.funnel, marginTop: 2 }}>{value}</div>
      <div style={{ fontSize: 12, color: colors.textMuted }}>{sub}</div>
    </div>
  );
}
