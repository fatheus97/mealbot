import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../contexts/AuthContext";
import { useIsMobile } from "../../hooks/useIsMobile";
import { BarChart, type Bar } from "./BarChart";
import {
  fetchAdminActivity,
  fetchAdminOverview,
  fetchAdminUsage,
  fetchAdminUsageByUser,
} from "../../api";

const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmtDay(iso: string): string {
  // "2026-07-12" -> "Jul 12"
  const parts = iso.split("-");
  if (parts.length < 3) return iso;
  return `${MONTHS[Number(parts[1])] ?? parts[1]} ${Number(parts[2])}`;
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: "0.9rem 1rem",
        background: "#fff",
      }}
    >
      <div style={{ fontSize: 12, color: "#6b7280", textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, color: "#111827", marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: "#9ca3af", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ marginTop: "1.75rem" }}>
      <h3 style={{ margin: "0 0 0.75rem", fontSize: 16, color: "#111827" }}>{title}</h3>
      {children}
    </section>
  );
}

function QueryState({
  isLoading,
  error,
  children,
}: {
  isLoading: boolean;
  error: unknown;
  children: ReactNode;
}) {
  if (isLoading) return <div style={{ color: "#888", fontSize: 13 }}>Loading…</div>;
  if (error)
    return (
      <div style={{ color: "#b91c1c", fontSize: 13 }}>
        Failed to load. {error instanceof Error ? error.message : ""}
      </div>
    );
  return <>{children}</>;
}

export function AdminDashboard({ onExit }: { onExit: () => void }) {
  const { isAdmin } = useAuth();
  const isMobile = useIsMobile();

  const overview = useQuery({
    queryKey: ["admin", "overview"],
    queryFn: fetchAdminOverview,
    enabled: isAdmin,
  });
  const usage = useQuery({
    queryKey: ["admin", "usage", "day"],
    queryFn: () => fetchAdminUsage(undefined, undefined, "day"),
    enabled: isAdmin,
  });
  const byUser = useQuery({
    queryKey: ["admin", "byUser", 20],
    queryFn: () => fetchAdminUsageByUser(20),
    enabled: isAdmin,
  });
  const activity = useQuery({
    queryKey: ["admin", "activity", "day"],
    queryFn: () => fetchAdminActivity(undefined, undefined, "day"),
    enabled: isAdmin,
  });

  const backButton = (
    <button
      onClick={onExit}
      style={{
        padding: "0.4rem 0.9rem",
        border: "1px solid #d1d5db",
        borderRadius: 6,
        background: "#fff",
        color: "#111827",
        cursor: "pointer",
        fontSize: 14,
      }}
    >
      ← Back
    </button>
  );

  if (!isAdmin) {
    return (
      <div style={{ maxWidth: 600, margin: "3rem auto", padding: "0 1rem", textAlign: "center" }}>
        <p style={{ color: "#6b7280" }}>You don't have access to the admin dashboard.</p>
        {backButton}
      </div>
    );
  }

  const usageSeries: Bar[] =
    usage.data?.series.map((b) => ({ label: fmtDay(b.period), value: b.total_tokens })) ?? [];
  const activitySeries: Bar[] =
    activity.data?.series.map((b) => ({ label: fmtDay(b.period), value: b.generations })) ?? [];
  const surfaceBars: Bar[] =
    usage.data?.by_surface.map((s) => ({ label: s.surface, value: s.total_tokens })) ?? [];
  const providerBars: Bar[] =
    usage.data?.by_provider.map((p) => ({ label: p.provider, value: p.total_tokens })) ?? [];
  const genSurfaceBars: Bar[] =
    overview.data?.generations_by_surface.map((s) => ({ label: s.surface, value: s.count })) ??
    [];
  const activitySurfaceBars: Bar[] =
    activity.data?.by_surface.map((s) => ({ label: s.surface, value: s.count })) ?? [];

  return (
    // Self-contained light surface + explicit dark base text color, so the
    // dashboard reads correctly regardless of the OS/browser color scheme.
    // index.css is the Vite default (dark-by-default); the rest of the app leans
    // on the adaptive default text color, which these hardcoded colors don't —
    // pinning the surface here keeps every element legible in light AND dark mode.
    <div style={{ background: "#f9fafb", color: "#1f2937", minHeight: "100vh" }}>
      <div
        style={{
          maxWidth: 1100,
          margin: "0 auto",
          padding: isMobile ? "1rem 0.75rem 3rem" : "1.5rem 1rem 3rem",
          fontFamily: "sans-serif",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "1rem",
            borderBottom: "2px solid #333",
            paddingBottom: "0.6rem",
          }}
        >
          <h1 style={{ margin: 0, fontSize: isMobile ? 20 : 26 }}>🛠️ Admin Dashboard</h1>
          {backButton}
        </div>

      <Section title="Overview">
        <QueryState isLoading={overview.isLoading} error={overview.error}>
          {overview.data && (
            <>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: isMobile ? "1fr 1fr" : "repeat(4, 1fr)",
                  gap: "0.75rem",
                }}
              >
                <StatCard
                  label="Users"
                  value={overview.data.total_users.toLocaleString()}
                  sub={`${overview.data.active_users_30d} active (30d)`}
                />
                <StatCard
                  label="Demo / Admin"
                  value={`${overview.data.demo_users} / ${overview.data.admin_users}`}
                />
                <StatCard label="LLM calls" value={overview.data.llm_calls.toLocaleString()} />
                <StatCard
                  label="Total tokens"
                  value={overview.data.total_tokens.toLocaleString()}
                  sub={`${overview.data.prompt_tokens.toLocaleString()} in · ${overview.data.completion_tokens.toLocaleString()} out`}
                />
              </div>
              <div style={{ marginTop: "1.25rem" }}>
                <div style={{ fontSize: 13, color: "#374151", marginBottom: 6 }}>
                  Generations by feature (all-time)
                </div>
                <BarChart data={genSurfaceBars} color="#8b5cf6" height={120} maxLabels={6} />
              </div>
            </>
          )}
        </QueryState>
      </Section>

      <Section title="Token usage — last 30 days">
        <QueryState isLoading={usage.isLoading} error={usage.error}>
          <BarChart data={usageSeries} color="#4f46e5" />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
              gap: "1.25rem",
              marginTop: "1.25rem",
            }}
          >
            <div>
              <div style={{ fontSize: 13, color: "#374151", marginBottom: 6 }}>By feature</div>
              <BarChart data={surfaceBars} color="#0ea5e9" height={120} maxLabels={6} />
            </div>
            <div>
              <div style={{ fontSize: 13, color: "#374151", marginBottom: 6 }}>By provider</div>
              <BarChart data={providerBars} color="#10b981" height={120} maxLabels={6} />
            </div>
          </div>
        </QueryState>
      </Section>

      <Section title="Generation activity — last 30 days">
        <QueryState isLoading={activity.isLoading} error={activity.error}>
          <BarChart data={activitySeries} color="#f59e0b" />
          <div style={{ marginTop: "1.25rem" }}>
            <div style={{ fontSize: 13, color: "#374151", marginBottom: 6 }}>By feature</div>
            <BarChart data={activitySurfaceBars} color="#ef4444" height={120} maxLabels={6} />
          </div>
        </QueryState>
      </Section>

      <Section title="Top users by tokens">
        <QueryState isLoading={byUser.isLoading} error={byUser.error}>
          {byUser.data && (
            <>
              <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 8 }}>
                {byUser.data.users_with_usage} users ·{" "}
                {Math.round(byUser.data.avg_tokens_per_user).toLocaleString()} avg tokens/user
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                  <thead>
                    <tr style={{ textAlign: "left", color: "#6b7280", borderBottom: "1px solid #e5e7eb" }}>
                      <th style={{ padding: "6px 8px" }}>User</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>Calls</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>Total tokens</th>
                      <th style={{ padding: "6px 8px", textAlign: "right" }}>Avg/call</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byUser.data.top_users.map((u) => (
                      <tr key={u.user_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "6px 8px" }}>{u.email}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>
                          {u.calls.toLocaleString()}
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>
                          {u.total_tokens.toLocaleString()}
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>
                          {Math.round(u.avg_tokens_per_call).toLocaleString()}
                        </td>
                      </tr>
                    ))}
                    {byUser.data.top_users.length === 0 && (
                      <tr>
                        <td colSpan={4} style={{ padding: "12px 8px", color: "#9ca3af" }}>
                          No usage recorded yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </QueryState>
      </Section>
      </div>
    </div>
  );
}
