import { useState, type CSSProperties, type FormEvent } from "react";
import { useAuth } from "../contexts/AuthContext";
import { joinHousehold, leaveHousehold } from "../api";
import {
  useCreateHouseholdInvite,
  useHousehold,
  useRevokeHouseholdInvite,
} from "../hooks/useServerState";
import { useI18n } from "../i18n";
import { formatDate } from "../i18n/localeFormat";
import type { HouseholdInviteCreated } from "../types";
import { HouseholdProfile } from "./HouseholdProfile";
import { InfoHint } from "./InfoHint";

/**
 * The Settings section for sharing a kitchen (docs/household-design.md, "Join
 * and leave"): who is in it, invites, joining with a code, leaving. Hidden
 * unless the server says households are on, and for demo sessions, which can
 * never share one.
 *
 * A join or a leave moves this account into another household, so every cache
 * the page holds belongs to the old one: both reload the page instead of
 * patching caches one by one.
 *
 * A new invite's code is shown once, here, and exists nowhere else afterwards:
 * the server keeps only its hash.
 *
 * THEME: lives inside SettingsPopup's explicit light surface, so it pins its
 * own colours like the rows around it.
 */
export function HouseholdSettings() {
  const { userId, email, isDemo, householdsEnabled } = useAuth();
  const { t, locale } = useI18n();
  const shown = householdsEnabled && !isDemo;
  const { data: household, isError } = useHousehold(userId, shown);
  const createInvite = useCreateHouseholdInvite();
  const revokeInvite = useRevokeHouseholdInvite();
  const [inviteEmail, setInviteEmail] = useState("");
  const [created, setCreated] = useState<HouseholdInviteCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [code, setCode] = useState("");
  const [joining, setJoining] = useState(false);
  const [confirmingLeave, setConfirmingLeave] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!shown) return null;

  const copy = { rateLimited: t("household.rateLimited"), fallback: t("household.failed") };
  const messageOf = (err: unknown) => (err instanceof Error ? err.message : t("household.failed"));
  const members = household?.members ?? [];
  const full = household !== undefined && members.length >= household.max_members;

  const handleInvite = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setCopied(false);
    try {
      setCreated(await createInvite.mutateAsync({ email: inviteEmail.trim(), copy }));
      setInviteEmail("");
    } catch (err) {
      setError(messageOf(err));
    }
  };

  const handleCopy = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.code);
      setCopied(true);
    } catch {
      // The code stays on screen to copy by hand.
    }
  };

  const handleRevoke = async (id: number) => {
    setError(null);
    try {
      await revokeInvite.mutateAsync({ id, copy });
      if (created?.id === id) setCreated(null);
    } catch (err) {
      setError(messageOf(err));
    }
  };

  const handleJoin = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setJoining(true);
    try {
      await joinHousehold(code.trim(), copy);
      window.location.reload();
    } catch (err) {
      setError(messageOf(err));
      setJoining(false);
    }
  };

  const handleLeave = async () => {
    setError(null);
    setLeaving(true);
    try {
      await leaveHousehold(copy);
      window.location.reload();
    } catch (err) {
      setError(messageOf(err));
      setLeaving(false);
    }
  };

  return (
    <div style={{ marginTop: "1.25rem", borderTop: "1px solid #e5e7eb", paddingTop: "1rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginBottom: "0.5rem" }}>
        <span style={{ fontSize: 13, color: "#6b7280" }}>{t("household.title")}</span>
        <InfoHint label={t("household.hintLabel")} text={t("household.hint")} />
      </div>

      {isError && (
        <p role="alert" style={errorText}>
          {t("household.loadFailed")}
        </p>
      )}

      {household && (
        <>
          <ul aria-label={t("household.members")} style={{ margin: "0 0 0.75rem", padding: 0, listStyle: "none" }}>
            {members.map((member) => (
              <li key={member.id} style={{ fontSize: 13, color: "#111827", padding: "0.15rem 0" }}>
                {member.id === userId || member.email === email
                  ? t("household.you", { email: member.email })
                  : member.email}
              </li>
            ))}
          </ul>

          {full ? (
            <p style={note}>{t("household.full", { maximum: household.max_members })}</p>
          ) : (
            <form onSubmit={(e) => void handleInvite(e)} style={row}>
              <input
                type="email"
                required
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                aria-label={t("household.inviteEmail")}
                placeholder={t("household.inviteEmail")}
                style={input}
              />
              <button type="submit" disabled={createInvite.isPending} style={secondary}>
                {createInvite.isPending ? t("household.inviting") : t("household.inviteButton")}
              </button>
            </form>
          )}

          {created && (
            <div style={codeBox}>
              <div style={{ fontSize: 13, color: "#111827", marginBottom: "0.35rem" }}>
                {t("household.codeFor", { email: created.email })}
              </div>
              <div style={row}>
                <input
                  readOnly
                  value={created.code}
                  aria-label={t("household.codeLabel")}
                  onFocus={(e) => e.currentTarget.select()}
                  style={{ ...input, fontFamily: "monospace" }}
                />
                <button type="button" onClick={() => void handleCopy()} style={secondary}>
                  {copied ? t("household.copied") : t("household.copy")}
                </button>
              </div>
              <p style={{ ...note, margin: "0.35rem 0 0" }}>
                {t("household.codeNote", { date: formatDate(created.expires_at, locale) })}
              </p>
            </div>
          )}

          {household.invites.length > 0 && (
            <>
              <div style={{ fontSize: 13, color: "#6b7280", margin: "0.75rem 0 0.25rem" }}>
                {t("household.openInvites")}
              </div>
              <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                {household.invites.map((invite) => (
                  <li key={invite.id} style={{ ...row, justifyContent: "space-between", padding: "0.15rem 0" }}>
                    <span style={{ fontSize: 13, color: "#111827", overflowWrap: "anywhere" }}>
                      {t("household.inviteUntil", {
                        email: invite.email,
                        date: formatDate(invite.expires_at, locale),
                      })}
                    </span>
                    <button
                      type="button"
                      onClick={() => void handleRevoke(invite.id)}
                      disabled={revokeInvite.isPending}
                      style={secondary}
                    >
                      {t("household.revoke")}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          <HouseholdProfile />

          {members.length === 1 ? (
            <form onSubmit={(e) => void handleJoin(e)} style={{ marginTop: "1rem" }}>
              <div style={{ fontSize: 13, color: "#6b7280", marginBottom: "0.25rem" }}>
                {t("household.joinTitle")}
              </div>
              <p style={note}>{t("household.joinHint")}</p>
              <div style={row}>
                <input
                  required
                  maxLength={512}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  aria-label={t("household.joinCode")}
                  placeholder={t("household.joinCode")}
                  autoComplete="off"
                  style={{ ...input, fontFamily: "monospace" }}
                />
                <button type="submit" disabled={joining} style={secondary}>
                  {joining ? t("household.joining") : t("household.joinButton")}
                </button>
              </div>
            </form>
          ) : (
            <div style={{ marginTop: "1rem" }}>
              {/* The confirm REPLACES the button in place, so nothing the user
                  might click moves (CLS, .claude/rules/frontend.md). */}
              {!confirmingLeave ? (
                <button type="button" onClick={() => setConfirmingLeave(true)} style={danger}>
                  {t("household.leave")}
                </button>
              ) : (
                <div>
                  <p style={{ fontSize: 13, color: "#111827", margin: "0 0 0.5rem" }}>
                    {t("household.leaveConfirm")}
                  </p>
                  <div style={row}>
                    <button
                      type="button"
                      onClick={() => void handleLeave()}
                      disabled={leaving}
                      style={{ ...danger, opacity: leaving ? 0.6 : 1 }}
                    >
                      {leaving ? t("household.leaving") : t("household.leaveButton")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmingLeave(false)}
                      disabled={leaving}
                      style={secondary}
                    >
                      {t("household.cancel")}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {error && (
        <p role="alert" style={errorText}>
          {error}
        </p>
      )}
    </div>
  );
}

const row: CSSProperties = { display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" };

const input: CSSProperties = {
  flex: "1 1 12rem",
  minWidth: 0,
  padding: "0.5rem 0.6rem",
  border: "1px solid #d1d5db",
  borderRadius: 6,
  background: "#ffffff",
  color: "#111827",
  fontSize: 13,
};

const note: CSSProperties = { fontSize: 12, color: "#4b5563", margin: "0 0 0.5rem" };

const codeBox: CSSProperties = {
  marginTop: "0.75rem",
  padding: "0.6rem",
  border: "1px solid #d1d5db",
  borderRadius: 6,
  background: "#f9fafb",
};

const errorText: CSSProperties = { margin: "0.4rem 0 0", color: "#b91c1c", fontSize: 12 };

const secondary: CSSProperties = {
  padding: "0.5rem 0.75rem",
  border: "1px solid #d1d5db",
  borderRadius: 6,
  background: "#f9fafb",
  color: "#111827",
  cursor: "pointer",
  fontSize: 13,
};

const danger: CSSProperties = {
  padding: "0.5rem 0.75rem",
  border: "1px solid #fecaca",
  borderRadius: 6,
  background: "#fef2f2",
  color: "#b91c1c",
  cursor: "pointer",
  fontSize: 13,
};
