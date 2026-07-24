import { type CSSProperties, type ReactNode, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "../ConfirmDialog";
import { ModalShell } from "../ModalShell";
import { useAuth } from "../../contexts/AuthContext";
import {
  useCreateAdminUser,
  useDeleteAdminUser,
  useForceLogoutAdminUser,
  useResetAdminUserOnboarding,
  useUpdateAdminUser,
} from "../../hooks/useServerState";
import { deleteAdminUser, fetchAdminUsers, updateAdminUser } from "../../api";
import type { AdminUser, AdminUserRoleFilter, AdminUserStatusFilter } from "../../types";
import { colors, radius } from "./theme";

const PAGE_SIZE = 25;

// A destructive/consequential action awaiting confirmation. `run` fires the
// underlying mutation with the dialog's success/error callbacks so the dialog
// can show a spinner + surface a 409 (e.g. "Cannot remove the last active
// admin") in place rather than closing on failure.
interface PendingConfirm {
  title: string;
  message: string;
  confirmLabel: string;
  run: (cb: { onSuccess: () => void; onError: (e: Error) => void }) => void;
}

export function UserManagementPanel() {
  const [searchInput, setSearchInput] = useState("");
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<AdminUserStatusFilter>("all");
  const [roleFilter, setRoleFilter] = useState<AdminUserRoleFilter>("all");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Debounce the search box so we don't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(searchInput.trim());
      setPage(0);
      setSelected(new Set()); // the result set changes — drop stale selections
    }, 250);
    return () => clearTimeout(t);
  }, [searchInput]);

  const usersQuery = useQuery({
    queryKey: ["admin", "users", { q, statusFilter, roleFilter, page }],
    queryFn: () =>
      fetchAdminUsers({
        q: q || undefined,
        status: statusFilter,
        role: roleFilter,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    // Keep the current rows visible while the next page/filter loads.
    placeholderData: (prev) => prev,
  });

  const updateMut = useUpdateAdminUser();
  const resetMut = useResetAdminUserOnboarding();
  const logoutMut = useForceLogoutAdminUser();

  const [banner, setBanner] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);

  // --- Bulk selection ---
  const { userId: currentAdminId } = useAuth();
  const queryClient = useQueryClient();
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState<
    { verb: string; ok: number; failed: { label: string; error: string }[] } | null
  >(null);
  // Frozen at confirm-open time so the batch can't shift under a re-render.
  const [bulkDeleteIds, setBulkDeleteIds] = useState<number[] | null>(null);

  // The result toast auto-dismisses on a clean run; a partial failure lingers
  // (it names who failed and why) until the admin closes it.
  useEffect(() => {
    if (bulkResult && bulkResult.failed.length === 0) {
      const t = setTimeout(() => setBulkResult(null), 5000);
      return () => clearTimeout(t);
    }
  }, [bulkResult]);

  const dataUsers = usersQuery.data?.users;
  // Demo accounts and the acting admin themselves can't be bulk-mutated (the
  // backend would 400/409 anyway) — exclude them from selection.
  function isSelectable(u: AdminUser): boolean {
    return !u.is_demo && u.id !== currentAdminId;
  }
  const selectableOnPage = (dataUsers ?? []).filter(isSelectable);
  const allSelected =
    selectableOnPage.length > 0 && selectableOnPage.every((u) => selected.has(u.id));
  const someSelected = selectableOnPage.some((u) => selected.has(u.id));
  // Only ever act on rows the admin can currently SEE and select — derived, so a
  // stale off-page id in `selected` can never be mutated (selection is also
  // cleared on navigation, below).
  const selectedIds = selectableOnPage.filter((u) => selected.has(u.id)).map((u) => u.id);

  function toggleRow(id: number): void {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function toggleSelectAll(): void {
    setSelected(allSelected ? new Set() : new Set(selectableOnPage.map((u) => u.id)));
  }

  // Run a mutation over every selected id, collecting per-user outcomes (each
  // endpoint is already guarded/audited), then invalidate the list ONCE and
  // report a summary — a partial batch shows which users failed and why (e.g.
  // the last-admin 409) rather than aborting the whole run.
  async function runBulk(
    ids: number[],
    action: (id: number) => Promise<unknown>,
    verb: string,
  ): Promise<void> {
    setBanner(null);
    setBulkResult(null);
    setBulkBusy(true);
    const labelFor = new Map((dataUsers ?? []).map((u) => [u.id, u.email] as const));
    const failed: { label: string; error: string }[] = [];
    let ok = 0;
    for (const id of ids) {
      try {
        await action(id);
        ok += 1;
      } catch (e) {
        failed.push({ label: labelFor.get(id) ?? String(id), error: e instanceof Error ? e.message : "failed" });
      }
    }
    setSelected(new Set());
    setBulkBusy(false);
    await queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    setBulkResult({ verb, ok, failed });
  }

  function bulkDeactivate(): void {
    void runBulk(selectedIds, (id) => updateAdminUser(id, { is_active: false }), "Deactivated");
  }
  function bulkReactivate(): void {
    void runBulk(selectedIds, (id) => updateAdminUser(id, { is_active: true }), "Reactivated");
  }
  function doBulkDelete(): void {
    const ids = bulkDeleteIds ?? [];
    setBulkDeleteIds(null);
    void runBulk(ids, (id) => deleteAdminUser(id), "Deleted");
  }

  // A non-confirmed ("direct") mutation — surface any error in the top banner.
  function runDirect(fire: (cb: { onError: (e: Error) => void }) => void): void {
    setBanner(null);
    fire({ onError: (e) => setBanner(e.message) });
  }

  function askConfirm(c: PendingConfirm): void {
    setBanner(null);
    setConfirmError(null);
    setConfirm(c);
  }

  function submitConfirm(): void {
    if (!confirm) return;
    setConfirmLoading(true);
    setConfirmError(null);
    confirm.run({
      onSuccess: () => {
        setConfirmLoading(false);
        setConfirm(null);
      },
      onError: (e) => {
        setConfirmLoading(false);
        setConfirmError(e.message);
      },
    });
  }

  // --- per-row actions ---

  function toggleActive(u: AdminUser): void {
    if (u.is_active) {
      askConfirm({
        title: "Deactivate account",
        message: `Disable ${u.email}? They'll be logged out of every device immediately and can't sign in until reactivated.`,
        confirmLabel: "Deactivate",
        run: (cb) => updateMut.mutate({ id: u.id, update: { is_active: false } }, cb),
      });
    } else {
      runDirect((cb) => updateMut.mutate({ id: u.id, update: { is_active: true } }, cb));
    }
  }

  function toggleAdmin(u: AdminUser): void {
    if (u.is_admin) {
      askConfirm({
        title: "Revoke admin access",
        message: `Remove admin access from ${u.email}?`,
        confirmLabel: "Revoke admin",
        run: (cb) => updateMut.mutate({ id: u.id, update: { is_admin: false } }, cb),
      });
    } else {
      runDirect((cb) => updateMut.mutate({ id: u.id, update: { is_admin: true } }, cb));
    }
  }

  function toggleComp(u: AdminUser): void {
    runDirect((cb) => updateMut.mutate({ id: u.id, update: { is_comped: !u.is_comped } }, cb));
  }

  function resetOnboarding(u: AdminUser): void {
    runDirect((cb) => resetMut.mutate(u.id, cb));
  }

  function forceLogout(u: AdminUser): void {
    askConfirm({
      title: "Force log out",
      message: `Log ${u.email} out of every device? They can sign back in — this doesn't disable the account.`,
      confirmLabel: "Log out",
      run: (cb) => logoutMut.mutate(u.id, cb),
    });
  }

  const data = usersQuery.data;
  const total = data?.total ?? 0;
  const start = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const end = Math.min(total, (page + 1) * PAGE_SIZE);

  return (
    <div>
      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          alignItems: "center",
          marginBottom: "1rem",
        }}
      >
        <input
          type="search"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search email…"
          aria-label="Search users by email"
          style={inputStyle}
        />
        <label style={filterLabel}>
          Status
          <select
            value={statusFilter}
            aria-label="Filter by status"
            onChange={(e) => {
              setStatusFilter(e.target.value as AdminUserStatusFilter);
              setPage(0);
              setSelected(new Set());
            }}
            style={selectStyle}
          >
            <option value="all">All</option>
            <option value="active">Active</option>
            <option value="disabled">Disabled</option>
          </select>
        </label>
        <label style={filterLabel}>
          Role
          <select
            value={roleFilter}
            aria-label="Filter by role"
            onChange={(e) => {
              setRoleFilter(e.target.value as AdminUserRoleFilter);
              setPage(0);
              setSelected(new Set());
            }}
            style={selectStyle}
          >
            <option value="all">All</option>
            <option value="admin">Admin</option>
            <option value="comped">Comped</option>
            <option value="demo">Demo</option>
          </select>
        </label>
        <div style={{ flex: 1 }} />
        <button type="button" onClick={() => setShowCreate(true)} style={primaryBtn}>
          + New user
        </button>
      </div>

      {banner && (
        <div role="alert" style={bannerStyle}>
          {banner}
        </div>
      )}

      {/* Result toast + selection bar are BOTH position:fixed (out of document
          flow), so they never push the table down — the whole bulk flow has zero
          layout shift (CLS). They share the pinned spot but are mutually exclusive:
          runBulk clears the selection before setting the result, and the toast is
          also gated on an empty selection so a new selection hides a lingering one
          (a partial-failure toast persists until then). */}
      {bulkResult && selectedIds.length === 0 && (
        <div
          role="status"
          style={bulkResult.failed.length === 0 ? successToastStyle : warnToastStyle}
        >
          <span>
            {bulkResult.verb} {bulkResult.ok} user{bulkResult.ok === 1 ? "" : "s"}.
            {bulkResult.failed.length > 0 && (
              <>
                {" "}
                {bulkResult.failed.length} failed —{" "}
                {bulkResult.failed.map((f) => `${f.label}: ${f.error}`).join("; ")}
              </>
            )}
          </span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setBulkResult(null)}
            style={toastCloseStyle}
          >
            ×
          </button>
        </div>
      )}

      {selectedIds.length > 0 && (
        <div role="region" aria-label="Bulk actions" style={floatingBarStyle}>
          <span style={{ fontWeight: 600 }}>{selectedIds.length} selected</span>
          <button type="button" onClick={bulkDeactivate} disabled={bulkBusy} style={barBtn(bulkBusy)}>
            Deactivate
          </button>
          <button type="button" onClick={bulkReactivate} disabled={bulkBusy} style={barBtn(bulkBusy)}>
            Reactivate
          </button>
          <button
            type="button"
            onClick={() => setBulkDeleteIds(selectedIds)}
            disabled={bulkBusy}
            style={barBtn(bulkBusy, true)}
          >
            Delete
          </button>
          <button type="button" onClick={() => setSelected(new Set())} disabled={bulkBusy} style={barGhostBtn(bulkBusy)}>
            Clear
          </button>
          {bulkBusy && <span style={{ color: "#9ca3af", fontSize: 13 }}>Working…</span>}
        </div>
      )}

      {usersQuery.isLoading && (
        <div style={{ color: colors.textMuted, fontSize: 13 }}>Loading…</div>
      )}
      {usersQuery.error && (
        <div style={{ color: colors.danger, fontSize: 13 }}>
          Failed to load users.{" "}
          {usersQuery.error instanceof Error ? usersQuery.error.message : ""}
        </div>
      )}

      {data && (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14, minWidth: 620 }}>
              <thead>
                <tr style={{ textAlign: "left", color: colors.textMuted, borderBottom: `1px solid ${colors.border}` }}>
                  <th style={{ ...th, width: 28 }}>
                    <input
                      type="checkbox"
                      aria-label="Select all users on this page"
                      checked={allSelected}
                      ref={(el) => {
                        if (el) el.indeterminate = someSelected && !allSelected;
                      }}
                      onChange={toggleSelectAll}
                      disabled={selectableOnPage.length === 0}
                    />
                  </th>
                  <th style={th}>User</th>
                  <th style={th}>Status</th>
                  <th style={th}>Joined</th>
                  <th style={{ ...th, textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.users.map((u) => (
                  <tr key={u.id} style={{ borderBottom: `1px solid ${colors.borderSubtle}` }}>
                    <td style={td}>
                      {isSelectable(u) && (
                        <input
                          type="checkbox"
                          aria-label={`Select ${u.email}`}
                          checked={selected.has(u.id)}
                          onChange={() => toggleRow(u.id)}
                        />
                      )}
                    </td>
                    <td style={td}>
                      <div style={{ color: colors.text }}>{u.email}</div>
                      {u.country && (
                        <div style={{ fontSize: 12, color: colors.textFaint }}>{u.country}</div>
                      )}
                    </td>
                    <td style={td}>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {!u.is_active && <Badge label="Disabled" bg="#fee2e2" fg="#b91c1c" />}
                        {u.is_admin && <Badge label="Admin" bg="#ede9fe" fg="#6d28d9" />}
                        {u.is_comped && <Badge label="Comped" bg="#dbeafe" fg="#1d4ed8" />}
                        {u.is_demo && <Badge label="Demo" bg="#f3f4f6" fg="#4b5563" />}
                        {u.is_active && !u.is_admin && !u.is_comped && !u.is_demo && (
                          <span style={{ fontSize: 12, color: colors.textFaint }}>
                            {u.subscription_status === "none" ? "user" : u.subscription_status}
                          </span>
                        )}
                      </div>
                    </td>
                    <td style={{ ...td, color: colors.textBody, whiteSpace: "nowrap" }}>
                      {formatDate(u.created_at)}
                    </td>
                    <td style={{ ...td, textAlign: "right" }}>
                      {u.is_demo ? (
                        <span style={{ fontSize: 12, color: colors.textFaint }}>—</span>
                      ) : (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, justifyContent: "flex-end" }}>
                          <RowButton onClick={() => toggleActive(u)}>
                            {u.is_active ? "Deactivate" : "Reactivate"}
                          </RowButton>
                          <RowButton onClick={() => toggleAdmin(u)}>
                            {u.is_admin ? "Revoke admin" : "Make admin"}
                          </RowButton>
                          <RowButton onClick={() => toggleComp(u)}>
                            {u.is_comped ? "Un-comp" : "Comp"}
                          </RowButton>
                          {u.onboarding_completed && (
                            <RowButton onClick={() => resetOnboarding(u)}>Reset onboarding</RowButton>
                          )}
                          <RowButton onClick={() => forceLogout(u)}>Force logout</RowButton>
                          <RowButton onClick={() => setDeleteTarget(u)} danger>
                            Delete
                          </RowButton>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {data.users.length === 0 && (
                  <tr>
                    <td colSpan={5} style={{ ...td, color: colors.textFaint }}>
                      No users match these filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginTop: "0.75rem",
              fontSize: 13,
              color: colors.textMuted,
            }}
          >
            <span>
              {total === 0 ? "No users" : `${start}–${end} of ${total}`}
            </span>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                type="button"
                onClick={() => {
                  setPage((p) => Math.max(0, p - 1));
                  setSelected(new Set());
                }}
                disabled={page === 0}
                style={secondaryBtn(page === 0)}
              >
                ← Prev
              </button>
              <button
                type="button"
                onClick={() => {
                  setPage((p) => p + 1);
                  setSelected(new Set());
                }}
                disabled={end >= total}
                style={secondaryBtn(end >= total)}
              >
                Next →
              </button>
            </div>
          </div>
        </>
      )}

      {confirm && (
        <ConfirmDialog
          title={confirm.title}
          message={confirm.message}
          confirmLabel={confirm.confirmLabel}
          onConfirm={submitConfirm}
          onCancel={() => {
            setConfirm(null);
            setConfirmError(null);
          }}
          loading={confirmLoading}
          loadingLabel="Working…"
          error={confirmError}
          destructive
        />
      )}

      {showCreate && <CreateUserModal onClose={() => setShowCreate(false)} />}

      {deleteTarget && (
        <DeleteUserModal user={deleteTarget} onClose={() => setDeleteTarget(null)} />
      )}

      {bulkDeleteIds != null && (
        <BulkDeleteModal
          count={bulkDeleteIds.length}
          onConfirm={doBulkDelete}
          onClose={() => setBulkDeleteIds(null)}
        />
      )}
    </div>
  );
}

// Permanent single-user delete behind a type-the-EMAIL confirmation — a
// deliberately higher bar than a one-click ConfirmDialog, because this is
// irreversible. Its bulk sibling (BulkDeleteModal, below) gates on the sentinel
// word DELETE for the same reason: a batch has no single email to type, but a
// larger blast radius must not get *weaker* friction than deleting one account.
function DeleteUserModal({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const deleteMut = useDeleteAdminUser();
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const confirmed = typed.trim().toLowerCase() === user.email.toLowerCase();

  function submit(e: React.FormEvent): void {
    e.preventDefault();
    if (!confirmed) return;
    setError(null);
    deleteMut.mutate(user.id, {
      onSuccess: () => onClose(),
      onError: (err) => setError(err instanceof Error ? err.message : "Could not delete the user."),
    });
  }

  return (
    <ModalShell onClose={onClose} ariaLabel="Delete user" zIndex={1200}>
      <div
        style={{
          background: colors.card,
          color: colors.text,
          borderRadius: 12,
          padding: "1.5rem",
          width: "min(92vw, 440px)",
          boxShadow: "0 4px 24px rgba(0,0,0,0.25)",
          border: "1px solid #fecaca",
        }}
      >
        <h3 style={{ margin: "0 0 0.75rem", fontSize: "1.15rem", color: colors.danger }}>
          Delete {user.email}?
        </h3>
        <p style={{ margin: "0 0 1rem", fontSize: 14, color: colors.textBody }}>
          This permanently deletes the account and all of its data (plans, fridge,
          sessions). Sales records are kept but anonymised, for tax. <strong>This
          cannot be undone.</strong>
        </p>
        <form onSubmit={submit}>
          <label style={formLabel}>
            Type the email to confirm
            <input
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              aria-label="Type the email to confirm"
              placeholder={user.email}
              autoComplete="off"
              style={inputStyle}
            />
          </label>
          {error && (
            <div role="alert" style={{ ...bannerStyle, marginTop: "0.5rem" }}>
              {error}
            </div>
          )}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1.25rem" }}>
            <button type="button" onClick={onClose} style={secondaryBtn(false)}>
              Cancel
            </button>
            <button type="submit" disabled={!confirmed || deleteMut.isPending} style={dangerBtn(!confirmed || deleteMut.isPending)}>
              {deleteMut.isPending ? "Deleting…" : "Delete permanently"}
            </button>
          </div>
        </form>
      </div>
    </ModalShell>
  );
}

// Permanent BULK delete behind a type-the-word ("DELETE") confirmation. Bulk
// delete has a larger blast radius than single delete (up to a page of accounts
// at once), so it must carry at least as much friction — a deliberate typed
// token, not a one-click confirm that a slipped Enter could fire. There's no
// single email to type for a batch, hence the sentinel word. The count is shown
// prominently so the admin acknowledges how many accounts are about to go.
function BulkDeleteModal({
  count,
  onConfirm,
  onClose,
}: {
  count: number;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const confirmed = typed.trim().toUpperCase() === "DELETE";

  function submit(e: React.FormEvent): void {
    e.preventDefault();
    if (!confirmed) return;
    onConfirm();
  }

  return (
    <ModalShell onClose={onClose} ariaLabel="Delete selected users" zIndex={1200}>
      <div
        style={{
          background: colors.card,
          color: colors.text,
          borderRadius: 12,
          padding: "1.5rem",
          width: "min(92vw, 440px)",
          boxShadow: "0 4px 24px rgba(0,0,0,0.25)",
          border: "1px solid #fecaca",
        }}
      >
        <h3 style={{ margin: "0 0 0.75rem", fontSize: "1.15rem", color: colors.danger }}>
          Delete {count} account{count === 1 ? "" : "s"}?
        </h3>
        <p style={{ margin: "0 0 1rem", fontSize: 14, color: colors.textBody }}>
          This permanently deletes{" "}
          {count === 1 ? "the selected account" : `all ${count} selected accounts`} and
          every bit of their data (plans, fridge, sessions). Sales records are kept but
          anonymised, for tax. <strong>This cannot be undone.</strong>
        </p>
        <form onSubmit={submit}>
          <label style={formLabel}>
            Type DELETE to confirm
            <input
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              aria-label="Type DELETE to confirm"
              placeholder="DELETE"
              autoComplete="off"
              style={inputStyle}
            />
          </label>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1.25rem" }}>
            <button type="button" onClick={onClose} style={secondaryBtn(false)}>
              Cancel
            </button>
            <button type="submit" disabled={!confirmed} style={dangerBtn(!confirmed)}>
              Delete permanently
            </button>
          </div>
        </form>
      </div>
    </ModalShell>
  );
}

function CreateUserModal({ onClose }: { onClose: () => void }) {
  const createMut = useCreateAdminUser();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [isComped, setIsComped] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function submit(e: React.FormEvent): void {
    e.preventDefault();
    setError(null);
    createMut.mutate(
      { email: email.trim(), password, is_admin: isAdmin, is_comped: isComped },
      {
        onSuccess: () => onClose(),
        onError: (err) => setError(err instanceof Error ? err.message : "Could not create the user."),
      },
    );
  }

  return (
    <ModalShell onClose={onClose} ariaLabel="Create a user" zIndex={1200}>
      <div
        style={{
          background: colors.card,
          color: colors.text,
          borderRadius: 12,
          padding: "1.5rem",
          width: "min(92vw, 420px)",
          boxShadow: "0 4px 24px rgba(0,0,0,0.25)",
          border: `1px solid ${colors.border}`,
        }}
      >
        <h3 style={{ margin: "0 0 1rem", fontSize: "1.15rem" }}>Create user</h3>
        <form onSubmit={submit}>
          <label style={formLabel}>
            Email
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={inputStyle}
            />
          </label>
          <label style={formLabel}>
            Password
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Min 8 chars, upper + lower + digit"
              style={inputStyle}
            />
          </label>
          <label style={checkboxRow}>
            <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />
            Admin access
          </label>
          <label style={checkboxRow}>
            <input type="checkbox" checked={isComped} onChange={(e) => setIsComped(e.target.checked)} />
            Comped (bypasses the paywall)
          </label>

          {error && (
            <div role="alert" style={{ ...bannerStyle, marginTop: "0.75rem" }}>
              {error}
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1.25rem" }}>
            <button type="button" onClick={onClose} style={secondaryBtn(false)}>
              Cancel
            </button>
            <button type="submit" disabled={createMut.isPending} style={primaryBtn}>
              {createMut.isPending ? "Creating…" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </ModalShell>
  );
}

function Badge({ label, bg, fg }: { label: string; bg: string; fg: string }) {
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
      {label}
    </span>
  );
}

function RowButton({
  onClick,
  children,
  danger = false,
}: {
  onClick: () => void;
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <button type="button" onClick={onClick} style={danger ? dangerRowBtnStyle : rowBtnStyle}>
      {children}
    </button>
  );
}

function formatDate(iso: string): string {
  // "2026-07-23T..." → "Jul 23, 2026" (local, no time).
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

const th: CSSProperties = { padding: "6px 8px", fontWeight: 600 };
const td: CSSProperties = { padding: "8px 8px", verticalAlign: "top" };

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

const selectStyle: CSSProperties = {
  padding: "0.4rem 0.5rem",
  border: `1px solid ${colors.borderStrong}`,
  borderRadius: 6,
  fontSize: 14,
  background: colors.card,
  color: colors.text,
};

const filterLabel: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "0.35rem",
  fontSize: 13,
  color: colors.textMuted,
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

const rowBtnStyle: CSSProperties = {
  padding: "0.25rem 0.55rem",
  border: `1px solid ${colors.border}`,
  borderRadius: 6,
  background: colors.card,
  color: colors.accent,
  cursor: "pointer",
  fontSize: 12,
  fontWeight: 600,
  whiteSpace: "nowrap",
};

const dangerRowBtnStyle: CSSProperties = {
  ...rowBtnStyle,
  color: colors.danger,
  border: "1px solid #fecaca",
};

function dangerBtn(disabled: boolean): CSSProperties {
  // Inactive → a legible grey (white-on-light-red reads poorly); it arms to a
  // solid, high-contrast red only once the email matches — the colour shift is
  // itself the "now you can delete" affordance.
  return {
    padding: "0.45rem 0.9rem",
    border: "none",
    borderRadius: 6,
    background: disabled ? colors.border : "#dc2626",
    color: disabled ? colors.textFaint : "#ffffff",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: 14,
    fontWeight: 600,
  };
}

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

function secondaryBtn(disabled: boolean): CSSProperties {
  return {
    padding: "0.4rem 0.85rem",
    border: `1px solid ${colors.borderStrong}`,
    borderRadius: 6,
    background: colors.card,
    color: disabled ? colors.textFaint : colors.text,
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: 14,
  };
}

const bannerStyle: CSSProperties = {
  padding: "0.5rem 0.75rem",
  borderRadius: radius,
  background: "#fef2f2",
  color: colors.danger,
  border: "1px solid #fecaca",
  fontSize: 13,
  marginBottom: "0.75rem",
};

// The bulk selection bar floats — position:fixed, pinned bottom-centre, OUT of
// document flow — so selecting rows never pushes the table down (zero CLS). A
// dark opaque pill: high-contrast and theme-independent (explicit colours), so it
// reads on the light admin surface in either OS colour scheme. zIndex sits below
// the confirm/modal layer (1100+) so the delete dialog still covers it.
const floatingBarStyle: CSSProperties = {
  position: "fixed",
  left: "50%",
  bottom: 20,
  transform: "translateX(-50%)",
  zIndex: 900,
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  justifyContent: "center",
  gap: "0.5rem",
  maxWidth: "calc(100vw - 24px)",
  padding: "0.55rem 0.85rem",
  borderRadius: 999,
  background: "#111827",
  color: "#ffffff",
  boxShadow: "0 8px 28px rgba(0,0,0,0.35)",
};

function barBtn(disabled: boolean, danger = false): CSSProperties {
  return {
    padding: "0.35rem 0.75rem",
    border: "none",
    borderRadius: 8,
    background: danger ? "#dc2626" : "#374151",
    color: "#ffffff",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: 13,
    fontWeight: 600,
    opacity: disabled ? 0.55 : 1,
  };
}

function barGhostBtn(disabled: boolean): CSSProperties {
  return {
    padding: "0.35rem 0.75rem",
    border: "1px solid #4b5563",
    borderRadius: 8,
    background: "transparent",
    color: "#e5e7eb",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: 13,
    fontWeight: 600,
    opacity: disabled ? 0.55 : 1,
  };
}

// The result confirmation is a floating toast too (same fixed spot the bar
// vacated), so it doesn't shift the table either. Success auto-dismisses; a
// partial failure keeps its detail until dismissed.
const toastBaseStyle: CSSProperties = {
  position: "fixed",
  left: "50%",
  bottom: 20,
  transform: "translateX(-50%)",
  zIndex: 900,
  display: "flex",
  // Top-align so the × stays at the top (reachable at scroll-top) when a large
  // failure batch makes the toast tall.
  alignItems: "flex-start",
  gap: "0.5rem",
  maxWidth: "calc(100vw - 24px)",
  // A whole page of failures (up to PAGE_SIZE) can't grow the box off the top of
  // the viewport — since it's out of flow it can't be page-scrolled, so cap the
  // height and let the failure list scroll inside instead.
  maxHeight: "60vh",
  overflowY: "auto",
  padding: "0.5rem 0.5rem 0.5rem 0.85rem",
  borderRadius: 10,
  fontSize: 13,
  boxShadow: "0 8px 28px rgba(0,0,0,0.25)",
};

const successToastStyle: CSSProperties = {
  ...toastBaseStyle,
  background: "#f0fdf4",
  color: "#166534",
  border: "1px solid #bbf7d0",
};

const warnToastStyle: CSSProperties = {
  ...toastBaseStyle,
  background: "#fffbeb",
  color: "#92400e",
  border: "1px solid #fde68a",
};

const toastCloseStyle: CSSProperties = {
  border: "none",
  background: "transparent",
  color: "inherit",
  cursor: "pointer",
  fontSize: 18,
  lineHeight: 1,
  padding: "0 0.35rem",
  opacity: 0.7,
  flexShrink: 0,
  // Keep the dismiss control pinned to the top of a tall (scrolling) toast.
  position: "sticky",
  top: 0,
};
