import { type CSSProperties, useState } from "react";
import { ConfirmDialog } from "../ConfirmDialog";
import { ModalShell } from "../ModalShell";
import { useCreateInvite, useInvites, useRevokeInvite } from "../../hooks/useServerState";
import type { InviteCreateResponse, InviteListItem, InviteStatus } from "../../types";
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

  const invites = invitesQuery.data?.invites ?? [];

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

      {showGenerate && <GenerateInviteModal onClose={() => setShowGenerate(false)} />}

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

function GenerateInviteModal({ onClose }: { onClose: () => void }) {
  const createMut = useCreateInvite();
  const [note, setNote] = useState("");
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
        onSuccess: (r) => setResult(r),
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
