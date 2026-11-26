import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { untranslatedEnglishIn } from "../../test/i18nAssertions";
import { useLocaleStore, DEFAULT_LOCALE } from "../../store/useLocaleStore";
import { ChangePasswordModal } from "./ChangePasswordModal";
import * as api from "../../api";
import * as AuthCtx from "../../contexts/AuthContext";
import type { AuthState } from "../../types";

// Literals already used by the other auth tests (gitleaks: no new ones).
const CURRENT = "Secret123";
const NEXT = "NewPass123";

const ACCOUNT = "cook@example.com";

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(AuthCtx, "useAuth").mockReturnValue({ email: ACCOUNT } as unknown as AuthState);
});

async function fill(
  user: ReturnType<typeof userEvent.setup>,
  { current = CURRENT, next = NEXT, confirm = NEXT } = {},
) {
  await user.type(screen.getByLabelText(/current password/i), current);
  await user.type(screen.getByLabelText(/^new password/i), next);
  await user.type(screen.getByLabelText(/confirm new password/i), confirm);
}

const submit = () => screen.getByRole("button", { name: /change password/i });

describe("ChangePasswordModal", () => {
  it("sends the current and new password, then says this device stays signed in", async () => {
    const user = userEvent.setup();
    const change = vi.spyOn(api, "changePassword").mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(<ChangePasswordModal onClose={onClose} />);
    await fill(user);
    await user.click(submit());

    await waitFor(() =>
      expect(change).toHaveBeenCalledWith(CURRENT, NEXT, {
        rateLimited: expect.any(String),
        fallback: expect.any(String),
      }),
    );
    expect(await screen.findByText("Password changed")).toBeInTheDocument();
    // The server minted a fresh session for this device: saying "sign in
    // again" here would be false.
    expect(screen.getByText(/still signed in here/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("uses password inputs with the autocomplete hints password managers read", () => {
    render(<ChangePasswordModal onClose={vi.fn()} />);
    const current = screen.getByLabelText(/current password/i);
    const next = screen.getByLabelText(/^new password/i);
    const confirm = screen.getByLabelText(/confirm new password/i);
    for (const input of [current, next, confirm]) expect(input).toHaveAttribute("type", "password");
    expect(current).toHaveAttribute("autocomplete", "current-password");
    expect(next).toHaveAttribute("autocomplete", "new-password");
    expect(confirm).toHaveAttribute("autocomplete", "new-password");
  });

  it("carries the account email in a hidden username field for password managers", () => {
    // Without it a manager guesses which saved login the new password belongs
    // to, or saves a second login with no username.
    render(<ChangePasswordModal onClose={vi.fn()} />);
    const username = document.querySelector<HTMLInputElement>('input[autocomplete="username"]');
    expect(username).not.toBeNull();
    expect(username).toHaveValue(ACCOUNT);
    expect(username).not.toBeVisible();
    // Inside the form, or the manager does not pair it with the passwords.
    expect(username?.form).toBe(screen.getByLabelText(/current password/i).closest("form"));
  });

  it("will not submit when the confirmation does not match", async () => {
    const user = userEvent.setup();
    const change = vi.spyOn(api, "changePassword").mockResolvedValue(undefined);

    render(<ChangePasswordModal onClose={vi.fn()} />);
    await fill(user, { confirm: "NewPass124" });

    expect(screen.getByText("Passwords don't match.")).toBeInTheDocument();
    expect(submit()).toBeDisabled();
    // Enter in a field is the other way to submit a form.
    await user.type(screen.getByLabelText(/confirm new password/i), "{Enter}");
    expect(change).not.toHaveBeenCalled();
  });

  it("names the first unmet rule of a weak new password and keeps submit off", async () => {
    // Same rules as the server's PasswordChangeRequest, so the 422 it would
    // send (a list detail with no sentence for a person) is never reached.
    const user = userEvent.setup();
    render(<ChangePasswordModal onClose={vi.fn()} />);
    await fill(user, { next: "newpass123", confirm: "newpass123" });

    expect(screen.getByText("Password must contain an upper-case letter.")).toBeInTheDocument();
    expect(submit()).toBeDisabled();
  });

  it("requires every field before enabling submit", async () => {
    const user = userEvent.setup();
    render(<ChangePasswordModal onClose={vi.fn()} />);
    expect(submit()).toBeDisabled();
    await user.type(screen.getByLabelText(/^new password/i), NEXT);
    await user.type(screen.getByLabelText(/confirm new password/i), NEXT);
    expect(submit()).toBeDisabled();
    await user.type(screen.getByLabelText(/current password/i), CURRENT);
    expect(submit()).toBeEnabled();
  });

  it("shows a wrong current password from the server and keeps the form", async () => {
    // The server's 401 detail is a LocalizedHTTPException, already in the
    // user's language, so it is shown as is.
    const user = userEvent.setup();
    vi.spyOn(api, "changePassword").mockRejectedValue(new Error("Current password is incorrect"));

    render(<ChangePasswordModal onClose={vi.fn()} />);
    await fill(user, { current: "Secret124" });
    await user.click(submit());

    expect(await screen.findByRole("alert")).toHaveTextContent("Current password is incorrect");
    expect(screen.getByLabelText(/^new password/i)).toHaveValue(NEXT);
    expect(submit()).toBeEnabled();
    // Typing again clears the stale error.
    await user.type(screen.getByLabelText(/current password/i), "x");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("disables submit and shows progress while the request runs", async () => {
    // A double click would spend a second attempt of the 5/minute limit and,
    // if the first succeeded, fail with "current password is incorrect".
    const user = userEvent.setup();
    let release: () => void = () => {};
    const change = vi
      .spyOn(api, "changePassword")
      .mockReturnValue(new Promise<void>((res) => { release = res; }));

    render(<ChangePasswordModal onClose={vi.fn()} />);
    await fill(user);
    await user.click(submit());

    const pending = screen.getByRole("button", { name: "Changing…" });
    expect(pending).toBeDisabled();
    await user.click(pending);
    expect(change).toHaveBeenCalledTimes(1);

    release();
    expect(await screen.findByText("Password changed")).toBeInTheDocument();
  });

  it("cannot be closed while the request runs, so the outcome is always shown", async () => {
    // Once sent, the change happens whatever the modal does, and a success has
    // already signed out every other device. Closing mid-request would let the
    // user believe they cancelled it.
    const user = userEvent.setup();
    let release: () => void = () => {};
    vi.spyOn(api, "changePassword").mockReturnValue(new Promise<void>((res) => { release = res; }));
    const onClose = vi.fn();

    render(<ChangePasswordModal onClose={onClose} />);
    await fill(user);
    await user.click(submit());

    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toBeDisabled();
    // Its inline colours would otherwise make it look clickable.
    expect(cancel).toHaveStyle({ opacity: "0.6", cursor: "not-allowed" });
    await user.click(cancel);
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();

    release();
    expect(await screen.findByText("Password changed")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    // Answered: Escape and the backdrop close it again.
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("re-enables Cancel, Escape and the backdrop once a request fails", async () => {
    const user = userEvent.setup();
    let fail: (err: Error) => void = () => {};
    vi.spyOn(api, "changePassword").mockReturnValue(
      new Promise<void>((_, rej) => { fail = rej; }),
    );
    const onClose = vi.fn();

    render(<ChangePasswordModal onClose={onClose} />);
    await fill(user);
    await user.click(submit());
    fail(new Error("Current password is incorrect"));
    await screen.findByRole("alert");

    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toBeEnabled();
    expect(cancel).toHaveStyle({ opacity: "1", cursor: "pointer" });
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("dialog"));
    await user.click(cancel);
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("closes on Escape and Cancel when no request is running", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<ChangePasswordModal onClose={onClose} />);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  describe("in Czech", () => {
    beforeEach(() => useLocaleStore.setState({ locale: "cs", explicit: true }));
    afterEach(() => {
      // Unmount first: resetting the store under a mounted modal re-renders it
      // outside act().
      cleanup();
      useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
    });

    it("renders no English on the form, with a rule hint showing", async () => {
      const user = userEvent.setup();
      render(<ChangePasswordModal onClose={vi.fn()} />);
      await user.type(screen.getByLabelText(/^nové heslo$/i), "abc");
      expect(screen.getByText("Heslo musí mít alespoň 8 znaků.")).toBeInTheDocument();
      expect(untranslatedEnglishIn(document.body)).toEqual([]);
    });

    it("renders no English on the confirmation state", async () => {
      const user = userEvent.setup();
      vi.spyOn(api, "changePassword").mockResolvedValue(undefined);
      render(<ChangePasswordModal onClose={vi.fn()} />);
      await user.type(screen.getByLabelText(/současné heslo/i), CURRENT);
      await user.type(screen.getByLabelText(/^nové heslo$/i), NEXT);
      await user.type(screen.getByLabelText(/nové heslo znovu/i), NEXT);
      await user.click(screen.getByRole("button", { name: /změnit heslo/i }));
      expect(await screen.findByText("Heslo bylo změněno")).toBeInTheDocument();
      expect(untranslatedEnglishIn(document.body)).toEqual([]);
    });

    it("passes Czech copy for the errors the client has to word itself", async () => {
      const user = userEvent.setup();
      const change = vi.spyOn(api, "changePassword").mockResolvedValue(undefined);
      render(<ChangePasswordModal onClose={vi.fn()} />);
      await user.type(screen.getByLabelText(/současné heslo/i), CURRENT);
      await user.type(screen.getByLabelText(/^nové heslo$/i), NEXT);
      await user.type(screen.getByLabelText(/nové heslo znovu/i), NEXT);
      await user.click(screen.getByRole("button", { name: /změnit heslo/i }));
      await waitFor(() =>
        expect(change).toHaveBeenCalledWith(CURRENT, NEXT, {
          rateLimited: "Příliš mnoho pokusů, počkejte prosím minutu a zkuste to znovu.",
          fallback: "Heslo se nepodařilo změnit.",
        }),
      );
      await screen.findByText("Heslo bylo změněno");
    });
  });
});
