import { type CSSProperties, useState } from "react";
import { ConfirmDialog } from "../ConfirmDialog";
import { ModalShell } from "../ModalShell";
import {
  useAccessRequests,
  useCreateInvite,
  useDeleteAccessRequest,
  useInvites,
  useRevokeInvite,
  useUpdateAccessRequest,
} from "../../hooks/useServerState";
import type {
  AccessRequestItem,
  AccessRequestStatus,
  InviteCreateResponse,
  InviteListItem,
  InviteStatus,
} from "../../types";
import { colors, radius } from "./theme";

const EXPIRY_OPTIONS = [
  { label: "24 hours", hours: 24 },
  { label: "48 hours", hours: 48 },
  { label: "7 days", hours: 168 },
];

/** The Invites admin tab: generate single-use invite links and manage
 *  outstanding ones (status + revoke). Lives on the isAdmin-gated dashboard. */
export function InvitePanel() {
  const invitesQuery = useInvites(true);
  const revokeMut = useRevokeInvite();
  const [showGenerate, setShowGenerate] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<InviteListItem | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  // Set when "Generate invite" was launched FROM a request row — on success we
  // also close that request out as handled.
  const [inviteForRequest, setInviteForRequest] = useState<AccessRequestItem | null>(null);
  const updateRequestMut = useUpdateAccessRequest();

  const invites = invitesQuery.data?.invites ?? [];

  function onInviteGenerated(): void {
    const request = inviteForRequest;
    if (!request) return;
    // Clear any stale banner first (mirrors doRevoke) so an old failure can't
    // stay on screen attached to this successful action.
    setBanner(null);
    // Bookkeeping, deliberately AFTER the invite exists: the link is the
    // valuable artifact and it's already been minted, so a failure here must
    // not read as "the invite failed". Surface it and leave the row pending —
    // the admin can mark it handled by hand, and re-running is harmless.
    updateRequestMut.mutate(
      { id: request.id, status: "handled" },
      {
        onError: () =>
          setBanner(
            `Invite created, but ${request.email}'s request couldn't be marked handled. Mark it manually.`,
          ),
      },
    );
  }

  function doRevoke(): void {
    const target = revokeTarget;
    if (!target) return;
    setBanner(null);
    revokeMut.mutate(target.id, {
      onSuccess: () => setRevokeTarget(null),
      onError: (e) => {
        setBanner(e instanceof Error ? e.message : "Could not revoke the invite.");
        setRevokeTarget(null);
      },
    });
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
          Generate a single-use link a prospective user can open to create their own
          account — even while public registration is closed. Copy it and send it to
          them yourself.
        </p>
        <button type="button" onClick={() => setShowGenerate(true)} style={primaryBtn}>
          + Generate invite link
        </button>
      </div>

      {banner && (
        <div role="alert" style={bannerStyle}>
          {banner}
        </div>
      )}

      <AccessRequestsSection
        onGenerateInvite={(request) => {
          setInviteForRequest(request);
          setShowGenerate(true);
        }}
      />

      <h3 style={{ margin: "1.75rem 0 0.75rem", fontSize: "1rem" }}>Invite links</h3>

      {invitesQuery.isLoading && (
        <div style={{ color: colors.textMuted, fontSize: 13 }}>Loading…</div>
      )}
      {invitesQuery.error && (
        <div style={{ color: colors.danger, fontSize: 13 }}>
          Failed to load invites.{" "}
          {invitesQuery.error instanceof Error ? invitesQuery.error.message : ""}
        </div>
      )}

      {invitesQuery.data && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14, minWidth: 640 }}>
            <thead>
              <tr style={{ textAlign: "left", color: colors.textMuted, borderBottom: `1px solid ${colors.border}` }}>
                <th style={th}>Note</th>
                <th style={th}>Status</th>
                <th style={th}>Comp</th>
                <th style={th}>Created</th>
                <th style={th}>Expires</th>
                <th style={th}>Redeemed by</th>
                <th style={{ ...th, textAlign: "right" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {invites.map((inv) => (
                <tr key={inv.id} style={{ borderBottom: `1px solid ${colors.borderSubtle}` }}>
                  <td style={td}>
                    {inv.note || <span style={{ color: colors.textFaint }}>—</span>}
                  </td>
                  <td style={td}>
                    <StatusBadge status={inv.status} />
                  </td>
                  <td style={td}>{inv.is_comped ? "Yes" : "No"}</td>
                  <td style={{ ...td, whiteSpace: "nowrap", color: colors.textBody }}>
                    {fmt(inv.created_at)}
                  </td>
                  <td style={{ ...td, whiteSpace: "nowrap", color: colors.textBody }}>
                    {fmt(inv.expires_at)}
                  </td>
                  <td style={td}>
                    {inv.redeemed_by_email || <span style={{ color: colors.textFaint }}>—</span>}
                  </td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {inv.status === "live" ? (
                      <button type="button" onClick={() => setRevokeTarget(inv)} style={dangerRowBtn}>
                        Revoke
                      </button>
                    ) : (
                      <span style={{ fontSize: 12, color: colors.textFaint }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
              {invites.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ ...td, color: colors.textFaint }}>
                    No invites yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showGenerate && (
        <GenerateInviteModal
          defaultNote={inviteForRequest ? `Access request #${inviteForRequest.id}` : ""}
          onGenerated={onInviteGenerated}
          onClose={() => {
            setShowGenerate(false);
            setInviteForRequest(null);
          }}
        />
      )}

      {revokeTarget && (
        <ConfirmDialog
          title="Revoke invite link?"
          message={`This immediately disables the invite${
            revokeTarget.note ? ` "${revokeTarget.note}"` : ""
          }. Anyone who still has the link won't be able to use it.`}
          confirmLabel="Revoke"
          onConfirm={doRevoke}
          onCancel={() => setRevokeTarget(null)}
          loading={revokeMut.isPending}
          loadingLabel="Revoking…"
          destructive
        />
      )}
    </div>
  );
}

function GenerateInviteModal({
  onClose,
  defaultNote = "",
  onGenerated,
}: {
  onClose: () => void;
  /** Prefilled when launched from an access request, so the resulting invite
   *  is traceable back to who asked. */
  defaultNote?: string;
  onGenerated?: () => void;
}) {
  const createMut = useCreateInvite();
  const [note, setNote] = useState(defaultNote);
  const [isComped, setIsComped] = useState(true);
  const [hours, setHours] = useState(48);
  const [result, setResult] = useState<InviteCreateResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function submit(e: React.FormEvent): void {
    e.preventDefault();
    setError(null);
    createMut.mutate(
      { note: note.trim() || null, is_comped: isComped, expires_in_hours: hours },
      {
        onSuccess: (r) => {
          setResult(r);
          onGenerated?.();
        },
        onError: (err) =>
          setError(err instanceof Error ? err.message : "Could not generate the invite."),
      },
    );
  }

  function copy(): void {
    if (!result) return;
    // Best-effort — if the clipboard API is blocked, the link is still selectable
    // in the read-only field.
    void navigator.clipboard?.writeText(result.invite_url).then(
      () => setCopied(true),
      () => undefined,
    );
  }

  return (
    <ModalShell onClose={onClose} ariaLabel="Generate invite link" zIndex={1200}>
      <div style={modalCard}>
        {result ? (
          <>
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1.15rem" }}>Invite link ready</h3>
            <p style={{ margin: "0 0 0.75rem", fontSize: 14, color: colors.textBody }}>
              Copy it now and send it to the person —{" "}
              <strong>you won't be able to see it again.</strong> The link works once and
              expires {fmt(result.expires_at)}.
            </p>
            <input
              readOnly
              value={result.invite_url}
              aria-label="Invite link"
              onFocus={(e) => e.currentTarget.select()}
              style={inputStyle}
            />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1rem" }}>
              <button type="button" onClick={copy} style={secondaryBtn}>
                {copied ? "Copied ✓" : "Copy link"}
              </button>
              <button type="button" onClick={onClose} style={primaryBtn}>
                Done
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={submit}>
            <h3 style={{ margin: "0 0 1rem", fontSize: "1.15rem" }}>Generate invite link</h3>
            <label style={formLabel}>
              Note (optional — only you see this)
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. for Alice"
                maxLength={200}
                style={inputStyle}
              />
            </label>
            <label style={formLabel}>
              Expires after
              <select value={hours} onChange={(e) => setHours(Number(e.target.value))} style={inputStyle}>
                {EXPIRY_OPTIONS.map((o) => (
                  <option key={o.hours} value={o.hours}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label style={checkboxRow}>
              <input
                type="checkbox"
                checked={isComped}
                onChange={(e) => setIsComped(e.target.checked)}
              />
              Comp this account (bypass the paywall) — recommended for testers
            </label>
            {error && (
              <div role="alert" style={bannerStyle}>
                {error}
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1.25rem" }}>
              <button type="button" onClick={onClose} style={secondaryBtn}>
                Cancel
              </button>
              <button type="submit" disabled={createMut.isPending} style={primaryBtn}>
                {createMut.isPending ? "Generating…" : "Generate"}
              </button>
            </div>
          </form>
        )}
      </div>
    </ModalShell>
  );
}

/** The access-request queue: what the public landing form produced, and the
 *  one-click path from a request to the invite that answers it. */
function AccessRequestsSection({
  onGenerateInvite,
}: {
  onGenerateInvite: (request: AccessRequestItem) => void;
}) {
  const [filter, setFilter] = useState<AccessRequestStatus>("pending");
  const query = useAccessRequests(true, filter);
  const updateMut = useUpdateAccessRequest();
  const deleteMut = useDeleteAccessRequest();
  const [deleteTarget, setDeleteTarget] = useState<AccessRequestItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  const requests = query.data?.requests ?? [];
  const pending = query.data?.pending_count ?? 0;

  /** Scope the disabled state to the row actually in flight — one shared
   *  mutation instance would otherwise disable the action on EVERY row. */
  function isRowBusy(id: number): boolean {
    return updateMut.isPending && updateMut.variables?.id === id;
  }

  function close(request: AccessRequestItem, status: "handled" | "dismissed"): void {
    setError(null);
    updateMut.mutate(
      { id: request.id, status },
      { onError: (e) => setError(e instanceof Error ? e.message : "Could not update it.") },
    );
  }

  function doDelete(): void {
    const target = deleteTarget;
    if (!target) return;
    setError(null);
    deleteMut.mutate(target.id, {
      onSuccess: () => setDeleteTarget(null),
      onError: (e) => {
        setError(e instanceof Error ? e.message : "Could not delete it.");
        setDeleteTarget(null);
      },
    });
  }

  return (
    <section style={{ marginBottom: "1.5rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "0.75rem",
          flexWrap: "wrap",
          marginBottom: "0.6rem",
        }}
      >
        <h3 style={{ margin: 0, fontSize: "1rem" }}>
          Access requests
          {pending > 0 && (
            <span
              style={{
                marginLeft: 8,
                background: colors.accent,
                color: "#fff",
                borderRadius: 999,
                padding: "1px 8px",
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              {pending}
            </span>
          )}
        </h3>
        <div style={{ display: "flex", gap: 4 }}>
          {(["pending", "handled", "dismissed"] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setFilter(s)}
              aria-pressed={filter === s}
              style={{
                ...filterBtn,
                background: filter === s ? colors.accent : "transparent",
                color: filter === s ? "#fff" : colors.textBody,
                borderColor: filter === s ? colors.accent : colors.border,
              }}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <p style={{ margin: "0 0 0.75rem", color: colors.textMuted, fontSize: 13, maxWidth: 640 }}>
        Submitted from the landing page while registration is closed. Answer one by generating
        an invite — that marks the request handled automatically.
      </p>

      {error && (
        <div role="alert" style={bannerStyle}>
          {error}
        </div>
      )}

      {query.isLoading && <div style={{ color: colors.textMuted, fontSize: 13 }}>Loading…</div>}
      {query.error && (
        <div style={{ color: colors.danger, fontSize: 13 }}>Failed to load access requests.</div>
      )}

      {query.data && (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{ width: "100%", borderCollapse: "collapse", fontSize: 14, minWidth: 640 }}
          >
            <thead>
              <tr
                style={{
                  textAlign: "left",
                  color: colors.textMuted,
                  borderBottom: `1px solid ${colors.border}`,
                }}
              >
                <th style={th}>Email</th>
                <th style={th}>Message</th>
                <th style={th}>Requested</th>
                <th style={{ ...th, textAlign: "right" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {requests.map((r) => (
                <tr key={r.id} style={{ borderBottom: `1px solid ${colors.borderSubtle}` }}>
                  <td style={{ ...td, overflowWrap: "anywhere" }}>
                    {/* Rendered as escaped React text — this is anonymous input. */}
                    {r.email}
                    {r.has_account && (
                      <div style={{ fontSize: 11, color: colors.textMuted }}>
                        already has an account
                      </div>
                    )}
                  </td>
                  {/* overflowWrap: a single unbroken token from an anonymous
                      submitter would otherwise blow out the table width. */}
                  <td
                    style={{
                      ...td,
                      maxWidth: 320,
                      whiteSpace: "pre-wrap",
                      overflowWrap: "anywhere",
                    }}
                  >
                    {r.message || <span style={{ color: colors.textFaint }}>—</span>}
                  </td>
                  <td style={{ ...td, whiteSpace: "nowrap", color: colors.textBody }}>
                    {fmt(r.created_at)}
                  </td>
                  <td style={{ ...td, textAlign: "right", whiteSpace: "nowrap" }}>
                    {r.status === "pending" && (
                      <>
                        <button
                          type="button"
                          onClick={() => onGenerateInvite(r)}
                          style={rowBtn}
                        >
                          Generate invite
                        </button>{" "}
                        {/* The manual close-out the "couldn't be marked
                            handled" banner tells the admin to use — without
                            it that instruction has no control to act on. */}
                        <button
                          type="button"
                          onClick={() => close(r, "handled")}
                          disabled={isRowBusy(r.id)}
                          style={rowBtn}
                        >
                          Mark handled
                        </button>{" "}
                        <button
                          type="button"
                          onClick={() => close(r, "dismissed")}
                          disabled={isRowBusy(r.id)}
                          style={rowBtn}
                        >
                          Dismiss
                        </button>{" "}
                      </>
                    )}
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(r)}
                      style={dangerRowBtn}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {requests.length === 0 && (
                <tr>
                  <td colSpan={4} style={{ ...td, color: colors.textFaint }}>
                    No {filter} requests.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Delete this request?"
          message={`Permanently erases ${deleteTarget.email}'s request and message. This is the GDPR erasure path — it cannot be undone.`}
          confirmLabel="Delete"
          onConfirm={doDelete}
          onCancel={() => setDeleteTarget(null)}
          loading={deleteMut.isPending}
          loadingLabel="Deleting…"
          destructive
        />
      )}
    </section>
  );
}

function StatusBadge({ status }: { status: InviteStatus }) {
  const map: Record<InviteStatus, { bg: string; fg: string; label: string }> = {
    live: { bg: "#dcfce7", fg: "#166534", label: "Live" },
    used: { bg: "#dbeafe", fg: "#1d4ed8", label: "Used" },
    expired: { bg: "#f3f4f6", fg: "#4b5563", label: "Expired" },
    revoked: { bg: "#fee2e2", fg: "#b91c1c", label: "Revoked" },
  };
  const s = map[status];
  return (
    <span
      style={{
        padding: "0.1rem 0.45rem",
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        background: s.bg,
        color: s.fg,
        whiteSpace: "nowrap",
      }}
    >
      {s.label}
    </span>
  );
}

function fmt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const th: CSSProperties = { padding: "6px 8px", fontWeight: 600 };
const td: CSSProperties = { padding: "8px 8px", verticalAlign: "top" };

const modalCard: CSSProperties = {
  background: colors.card,
  color: colors.text,
  borderRadius: 12,
  padding: "1.5rem",
  width: "min(92vw, 460px)",
  boxShadow: "0 4px 24px rgba(0,0,0,0.25)",
  border: `1px solid ${colors.border}`,
};

const inputStyle: CSSProperties = {
  padding: "0.45rem 0.6rem",
  border: `1px solid ${colors.borderStrong}`,
  borderRadius: 6,
  fontSize: 14,
  background: colors.card,
  color: colors.text,
  width: "100%",
  boxSizing: "border-box",
};

const formLabel: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.3rem",
  fontSize: 13,
  color: colors.textBody,
  marginBottom: "0.75rem",
};

const checkboxRow: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "0.5rem",
  fontSize: 14,
  color: colors.text,
  marginBottom: "0.5rem",
};

const primaryBtn: CSSProperties = {
  padding: "0.45rem 0.9rem",
  border: "none",
  borderRadius: 6,
  background: colors.accent,
  color: "#ffffff",
  cursor: "pointer",
  fontSize: 14,
  fontWeight: 600,
};

const secondaryBtn: CSSProperties = {
  padding: "0.4rem 0.85rem",
  border: `1px solid ${colors.borderStrong}`,
  borderRadius: 6,
  background: colors.card,
  color: colors.text,
  cursor: "pointer",
  fontSize: 14,
};

const dangerRowBtn: CSSProperties = {
  padding: "0.25rem 0.55rem",
  border: "1px solid #fecaca",
  borderRadius: 6,
  background: colors.card,
  color: colors.danger,
  cursor: "pointer",
  fontSize: 12,
  fontWeight: 600,
  whiteSpace: "nowrap",
};

const bannerStyle: CSSProperties = {
  padding: "0.5rem 0.75rem",
  borderRadius: radius,
  background: "#fef2f2",
  color: colors.danger,
  border: "1px solid #fecaca",
  fontSize: 13,
  marginBottom: "0.75rem",
};

const rowBtn: CSSProperties = {
  padding: "3px 8px",
  fontSize: 12,
  borderRadius: 6,
  border: `1px solid ${colors.border}`,
  background: "transparent",
  color: colors.textBody,
  cursor: "pointer",
};

const filterBtn: CSSProperties = {
  padding: "3px 10px",
  fontSize: 12,
  borderRadius: 6,
  border: "1px solid",
  cursor: "pointer",
  textTransform: "capitalize",
};
