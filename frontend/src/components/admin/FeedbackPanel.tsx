import { type CSSProperties, useState } from "react";
import { ModalShell } from "../ModalShell";
import { ConfirmDialog } from "../ConfirmDialog";
import {
  useAcceptFeedback,
  useAdminFeedback,
  useAdminFeedbackDetail,
  useModerateFeedback,
  useRetriageFeedback,
} from "../../hooks/useServerState";
import type {
  AdminFeedbackItem,
  FeedbackModerationStatus,
  FeedbackStatusFilter,
} from "../../types";
import { colors, radius } from "./theme";

const PAGE_SIZE = 25;

const STATUS_FILTERS: { value: FeedbackStatusFilter; label: string }[] = [
  { value: "new", label: "New" },
  { value: "reviewing", label: "Reviewing" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
  { value: "spam", label: "Spam" },
  { value: "all", label: "All" },
];

// Moderation transitions offered in the detail drawer (the 6a-settable set; the
// money-moving Accept is deliberately absent).
const MODERATION_ACTIONS: { status: FeedbackModerationStatus; label: string }[] = [
  { status: "reviewing", label: "Reviewing" },
  { status: "rejected", label: "Reject" },
  { status: "spam", label: "Spam" },
  { status: "new", label: "Reopen" },
];

/** The Feedback admin tab: the bug-report / feature-request moderation queue.
 *  Lists reports with their advisory LLM triage, and opens a detail drawer with
 *  the full body + moderation actions. No money/ticket here (that's 6b). */
export function FeedbackPanel() {
  const [statusFilter, setStatusFilter] = useState<FeedbackStatusFilter>("new");
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const query = { status: statusFilter, limit: PAGE_SIZE, offset };
  const listQuery = useAdminFeedback(query, true);
  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? 0;

  // Pull `offset` back onto a populated page when `total` shrinks under it — e.g.
  // moderating the last report on the last page (which drops it out of the current
  // filter) would otherwise strand the admin on an empty page with a reversed
  // "N+1–N of N" range label. Adjust-state-during-render (the React "reset on prop
  // change" pattern used in App.tsx AuthRoot): the guard flips false after the
  // setState, so it re-renders once with the clamped offset and doesn't loop.
  if (total > 0 && offset >= total) {
    setOffset(Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE);
  }

  function changeFilter(next: FeedbackStatusFilter): void {
    setStatusFilter(next);
    setOffset(0); // a new filter starts from the first page
  }

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "0.75rem",
          flexWrap: "wrap",
          marginBottom: "1rem",
        }}
      >
        <p style={{ margin: 0, color: colors.textMuted, fontSize: 13, maxWidth: 540 }}>
          User bug reports & feature requests. The AI triage is advisory — it pre-sorts
          the queue, but you decide. Reject/spam obvious noise; leave real ones for
          follow-up.
        </p>
        <label style={{ fontSize: 13, color: colors.textBody, display: "flex", gap: "0.4rem", alignItems: "center" }}>
          Status
          <select
            value={statusFilter}
            onChange={(e) => changeFilter(e.target.value as FeedbackStatusFilter)}
            style={selectStyle}
          >
            {STATUS_FILTERS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {listQuery.isLoading && (
        <div style={{ color: colors.textMuted, fontSize: 13 }}>Loading…</div>
      )}
      {listQuery.error && (
        <div style={{ color: colors.danger, fontSize: 13 }}>
          Failed to load feedback.{" "}
          {listQuery.error instanceof Error ? listQuery.error.message : ""}
        </div>
      )}

      {listQuery.data && (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14, minWidth: 720 }}>
              <thead>
                <tr style={{ textAlign: "left", color: colors.textMuted, borderBottom: `1px solid ${colors.border}` }}>
                  <th style={th}>When</th>
                  <th style={th}>User</th>
                  <th style={th}>Kind</th>
                  <th style={th}>AI triage</th>
                  <th style={th}>Status</th>
                  <th style={th}>Preview</th>
                  <th style={{ ...th, textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <FeedbackRow key={it.id} item={it} onView={() => setSelectedId(it.id)} />
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={7} style={{ ...td, color: colors.textFaint }}>
                      No reports {statusFilter === "all" ? "yet" : `in "${statusFilter}"`}.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginTop: "0.75rem",
              fontSize: 13,
              color: colors.textMuted,
            }}
          >
            <span>
              {total === 0
                ? "0 reports"
                : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
            </span>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                type="button"
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                disabled={offset === 0}
                style={{ ...pagerBtn, opacity: offset === 0 ? 0.5 : 1 }}
              >
                ← Prev
              </button>
              <button
                type="button"
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= total}
                style={{ ...pagerBtn, opacity: offset + PAGE_SIZE >= total ? 0.5 : 1 }}
              >
                Next →
              </button>
            </div>
          </div>
        </>
      )}

      {selectedId !== null && (
        <FeedbackDetailModal id={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </div>
  );
}

function FeedbackRow({ item, onView }: { item: AdminFeedbackItem; onView: () => void }) {
  return (
    <tr style={{ borderBottom: `1px solid ${colors.borderSubtle}` }}>
      <td style={{ ...td, whiteSpace: "nowrap", color: colors.textBody }}>{fmt(item.created_at)}</td>
      <td style={{ ...td, maxWidth: 160, overflowWrap: "anywhere" }}>
        {item.user_email || <span style={{ color: colors.textFaint }}>—</span>}
      </td>
      <td style={td}>{item.kind}</td>
      <td style={td}>
        {item.triage_status === "done" ? (
          <TriageBadges type={item.triage_type} severity={item.triage_severity} actionable={item.triage_is_actionable} />
        ) : (
          <span style={{ fontSize: 12, color: colors.textFaint }}>
            {item.triage_status === "pending"
              ? "pending…"
              : item.triage_status === "failed"
                ? "failed"
                : "—"}
          </span>
        )}
      </td>
      <td style={td}>
        <StatusBadge status={item.status} />
      </td>
      <td style={{ ...td, maxWidth: 280, color: colors.textBody }}>
        <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {item.triage_title || item.preview}
        </span>
      </td>
      <td style={{ ...td, textAlign: "right" }}>
        <button type="button" onClick={onView} style={secondaryBtn}>
          View
        </button>
      </td>
    </tr>
  );
}

function FeedbackDetailModal({ id, onClose }: { id: number; onClose: () => void }) {
  const detailQuery = useAdminFeedbackDetail(id);
  const moderate = useModerateFeedback();
  const retriage = useRetriageFeedback();
  const accept = useAcceptFeedback();
  const [error, setError] = useState<string | null>(null);
  const [confirmAccept, setConfirmAccept] = useState(false);
  const d = detailQuery.data;

  function doModerate(status: FeedbackModerationStatus): void {
    setError(null);
    moderate.mutate(
      { id, status },
      { onError: (e) => setError(e instanceof Error ? e.message : "Could not update.") },
    );
  }

  function doRetriage(): void {
    setError(null);
    retriage.mutate(id, {
      onError: (e) => setError(e instanceof Error ? e.message : "Could not re-run triage."),
    });
  }

  function doAccept(): void {
    setError(null);
    accept.mutate(id, {
      onSuccess: () => setConfirmAccept(false),
      onError: (e) => {
        setError(e instanceof Error ? e.message : "Could not accept the report.");
        setConfirmAccept(false);
      },
    });
  }

  return (
    <ModalShell onClose={onClose} ariaLabel="Feedback detail" zIndex={1200}>
      <div style={detailCard}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
          <h3 style={{ margin: 0, fontSize: "1.15rem", color: colors.text }}>Report #{id}</h3>
          <button type="button" onClick={onClose} aria-label="Close" style={closeBtn}>
            ✕
          </button>
        </div>

        {detailQuery.isLoading && <p style={{ color: colors.textMuted }}>Loading…</p>}
        {detailQuery.error && (
          <p style={{ color: colors.danger }}>
            Failed to load. {detailQuery.error instanceof Error ? detailQuery.error.message : ""}
          </p>
        )}

        {d && (
          <>
            <div style={{ fontSize: 12, color: colors.textMuted, marginBottom: "0.75rem" }}>
              {d.kind} · {d.user_email ?? "unknown user"} · {fmt(d.created_at)}
              {d.page ? ` · from ${d.page}` : ""}
            </div>

            <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center", marginBottom: "0.5rem" }}>
              <StatusBadge status={d.status} />
              {d.credit_granted_at ? (
                <Pill text={`€${((d.credit_cents ?? 0) / 100).toFixed(2)} credited`} bg="#dcfce7" fg="#166534" />
              ) : d.status === "accepted" ? (
                <Pill text="no credit" bg="#f3f4f6" fg="#6b7280" />
              ) : null}
              {d.ticket_url ? (
                <a href={d.ticket_url} target="_blank" rel="noreferrer" style={ticketLink}>
                  🎫 Ticket
                </a>
              ) : d.status === "accepted" ? (
                <Pill text="no ticket" bg="#f3f4f6" fg="#6b7280" />
              ) : null}
            </div>

            <div style={messageBox}>{d.message}</div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "1rem 0 0.4rem" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: colors.text }}>AI triage (advisory)</div>
              <button
                type="button"
                onClick={doRetriage}
                disabled={retriage.isPending}
                style={secondaryBtn}
              >
                {retriage.isPending ? "Re-running…" : "Re-run"}
              </button>
            </div>
            {d.triage ? (
              <div style={triageBox}>
                <div style={{ marginBottom: 6 }}>
                  <TriageBadges
                    type={d.triage.type}
                    severity={d.triage.severity}
                    actionable={d.triage.is_actionable}
                  />
                </div>
                <div style={{ fontWeight: 600, color: colors.text }}>{d.triage.title}</div>
                <div style={{ fontSize: 13, color: colors.textBody, marginTop: 2 }}>{d.triage.summary}</div>
                {d.triage.repro && (
                  <div style={{ fontSize: 13, color: colors.textBody, marginTop: 6 }}>
                    <strong>Repro:</strong> {d.triage.repro}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 13, color: colors.textFaint }}>
                {d.triage_status === "failed"
                  ? "Triage failed — re-run to retry."
                  : d.triage_status === "pending"
                    ? "Triage pending…"
                    : "No triage."}
              </div>
            )}

            {/* Accept — the money-mover: €1 credit + private-repo ticket. Kept apart
                from the (free) moderation actions and gated behind a confirm. */}
            <div style={{ marginTop: "1.25rem" }}>
              <button
                type="button"
                onClick={() => setConfirmAccept(true)}
                disabled={accept.isPending || d.status === "rejected" || d.status === "spam"}
                title={
                  d.status === "rejected" || d.status === "spam"
                    ? "Reopen before accepting"
                    : undefined
                }
                style={{
                  ...acceptBtn,
                  opacity:
                    accept.isPending || d.status === "rejected" || d.status === "spam" ? 0.5 : 1,
                }}
              >
                {accept.isPending
                  ? "Accepting…"
                  : d.status === "accepted"
                    ? "Re-run credit / ticket"
                    : "✓ Accept — €1 credit + ticket"}
              </button>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginTop: "0.75rem" }}>
              {MODERATION_ACTIONS.map((a) => (
                <button
                  key={a.status}
                  type="button"
                  onClick={() => doModerate(a.status)}
                  disabled={moderate.isPending || d.status === a.status}
                  style={{
                    ...actionBtn,
                    ...(a.status === "rejected" || a.status === "spam" ? dangerTint : {}),
                    opacity: moderate.isPending || d.status === a.status ? 0.5 : 1,
                  }}
                >
                  {a.label}
                </button>
              ))}
            </div>

            {/* Banner sits BELOW the action buttons so a failed mutation grows the
                modal downward instead of shifting the buttons under the cursor (CLS
                — see .claude/rules/frontend.md). */}
            {error && (
              <div role="alert" style={bannerStyle}>
                {error}
              </div>
            )}

            {confirmAccept && (
              <ConfirmDialog
                title="Accept this report?"
                message="Grants the reporter a €1 credit (if eligible — monthly plan, under the cap) and opens a ticket in the private repo. Idempotent: re-accepting never double-credits."
                confirmLabel="Accept"
                // Admin is permanently out of the i18n scope, so pin the shared
                // dialog's now-translated Cancel back to English — otherwise this
                // prompt reads "Zrušit" beside an English confirm label forever.
                cancelLabel="Cancel"
                onConfirm={doAccept}
                onCancel={() => setConfirmAccept(false)}
                loading={accept.isPending}
                loadingLabel="Accepting…"
              />
            )}
          </>
        )}
      </div>
    </ModalShell>
  );
}

function TriageBadges({
  type,
  severity,
  actionable,
}: {
  type: string | null;
  severity: string | null;
  actionable: boolean | null;
}) {
  return (
    <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
      {type && <Pill text={type} bg="#eef2ff" fg="#4338ca" />}
      {severity && <Pill text={severity} bg={severityBg(severity)} fg={severityFg(severity)} />}
      {actionable === false && <Pill text="not actionable" bg="#f3f4f6" fg="#6b7280" />}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { bg: string; fg: string }> = {
    new: { bg: "#dbeafe", fg: "#1d4ed8" },
    reviewing: { bg: "#fef3c7", fg: "#92400e" },
    accepted: { bg: "#dcfce7", fg: "#166534" },
    rejected: { bg: "#f3f4f6", fg: "#4b5563" },
    spam: { bg: "#fee2e2", fg: "#b91c1c" },
  };
  const s = map[status] ?? { bg: "#f3f4f6", fg: "#4b5563" };
  return <Pill text={status} bg={s.bg} fg={s.fg} />;
}

function Pill({ text, bg, fg }: { text: string; bg: string; fg: string }) {
  return (
    <span
      style={{
        padding: "0.1rem 0.45rem",
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        background: bg,
        color: fg,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </span>
  );
}

function severityBg(sev: string): string {
  return sev === "high" ? "#fee2e2" : sev === "medium" ? "#fef3c7" : "#f3f4f6";
}
function severityFg(sev: string): string {
  return sev === "high" ? "#b91c1c" : sev === "medium" ? "#92400e" : "#4b5563";
}

function fmt(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const th: CSSProperties = { padding: "6px 8px", fontWeight: 600 };
const td: CSSProperties = { padding: "8px 8px", verticalAlign: "top" };

const selectStyle: CSSProperties = {
  padding: "0.35rem 0.5rem",
  border: `1px solid ${colors.borderStrong}`,
  borderRadius: 6,
  fontSize: 13,
  background: colors.card,
  color: colors.text,
};

const secondaryBtn: CSSProperties = {
  padding: "0.3rem 0.7rem",
  border: `1px solid ${colors.borderStrong}`,
  borderRadius: 6,
  background: colors.card,
  color: colors.text,
  cursor: "pointer",
  fontSize: 13,
};

const pagerBtn: CSSProperties = { ...secondaryBtn, fontSize: 13 };

const actionBtn: CSSProperties = {
  padding: "0.4rem 0.8rem",
  border: `1px solid ${colors.borderStrong}`,
  borderRadius: 6,
  background: colors.card,
  color: colors.text,
  cursor: "pointer",
  fontSize: 13,
  fontWeight: 600,
};

const dangerTint: CSSProperties = { border: "1px solid #fecaca", color: colors.danger };

const acceptBtn: CSSProperties = {
  padding: "0.5rem 0.9rem",
  border: "none",
  borderRadius: 6,
  background: "#15803d", // 5.02:1 with #ffffff (was #16a34a, 3.30:1)
  color: "#ffffff",
  cursor: "pointer",
  fontSize: 14,
  fontWeight: 600,
};

const ticketLink: CSSProperties = {
  padding: "0.1rem 0.45rem",
  borderRadius: 10,
  fontSize: 11,
  fontWeight: 600,
  background: "#dbeafe",
  color: "#1d4ed8",
  textDecoration: "none",
  whiteSpace: "nowrap",
};

const detailCard: CSSProperties = {
  background: colors.card,
  color: colors.text,
  borderRadius: 12,
  padding: "1.5rem",
  width: "min(94vw, 560px)",
  maxHeight: "88vh",
  overflowY: "auto",
  boxShadow: "0 4px 24px rgba(0,0,0,0.25)",
  border: `1px solid ${colors.border}`,
  boxSizing: "border-box",
};

const messageBox: CSSProperties = {
  background: colors.surface,
  border: `1px solid ${colors.border}`,
  borderRadius: radius,
  padding: "0.75rem",
  fontSize: 14,
  color: colors.textBody,
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
};

const triageBox: CSSProperties = {
  background: colors.surface,
  border: `1px solid ${colors.border}`,
  borderRadius: radius,
  padding: "0.75rem",
};

const closeBtn: CSSProperties = {
  background: "none",
  border: "none",
  fontSize: "1.15rem",
  cursor: "pointer",
  color: colors.textMuted,
  padding: "0.25rem",
};

const bannerStyle: CSSProperties = {
  padding: "0.5rem 0.75rem",
  borderRadius: radius,
  background: "#fef2f2",
  color: colors.danger,
  border: "1px solid #fecaca",
  fontSize: 13,
  marginTop: "0.75rem",
};
