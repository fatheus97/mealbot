import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/test-utils";
import { untranslatedEnglishIn } from "../../test/i18nAssertions";
import { useLocaleStore, DEFAULT_LOCALE } from "../../store/useLocaleStore";
import { ChangeEmailModal } from "./ChangeEmailModal";
import * as AuthCtx from "../../contexts/AuthContext";
import * as api from "../../api";
import type { AuthState } from "../../types";

function authState(over: Partial<AuthState> = {}): AuthState {
  return {
    userId: 1,
    email: "typo@exmaple.com",
    emailVerified: false,
    refreshProfile: vi.fn().mockResolvedValue(undefined),
    isDemo: false,
    isAdmin: false,
    ...over,
  } as unknown as AuthState;
}

beforeEach(() => vi.restoreAllMocks());

describe("ChangeEmailModal", () => {
  it("sends the new address with the current password", async () => {
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    const change = vi.spyOn(api, "changeEmail").mockResolvedValue(undefined);

    renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
    await user.type(screen.getByLabelText(/new email address/i), "right@example.com");
    await user.type(screen.getByLabelText(/current password/i), "Secret123");
    await user.click(screen.getByRole("button", { name: /change address/i }));

    await waitFor(() =>
      expect(change).toHaveBeenCalledWith("Secret123", "right@example.com", {
        invalidEmail: "Please enter a valid email address.",
        rateLimited: "Too many attempts. Please try again later.",
        fallback: "Could not change your email address.",
      }),
    );
  });

  it("cannot be closed while the request runs, and can again once it has an answer", async () => {
    // Once sent, the change lands whatever the modal does and signs out every
    // other device; closing mid-request would read as a cancel.
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    let fail: (err: Error) => void = () => {};
    vi.spyOn(api, "changeEmail").mockReturnValue(new Promise<void>((_, rej) => { fail = rej; }));
    const onClose = vi.fn();

    renderWithProviders(<ChangeEmailModal onClose={onClose} />);
    await user.type(screen.getByLabelText(/new email address/i), "right@example.com");
    await user.type(screen.getByLabelText(/current password/i), "Secret123");
    await user.click(screen.getByRole("button", { name: /change address/i }));

    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toBeDisabled();
    expect(cancel).toHaveStyle({ opacity: "0.6", cursor: "not-allowed" });
    await user.click(cancel);
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();

    fail(new Error("Current password is incorrect"));
    await screen.findByRole("alert");
    expect(cancel).toBeEnabled();
    expect(cancel).toHaveStyle({ opacity: "1", cursor: "pointer" });
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("dialog"));
    await user.click(cancel);
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("refreshes the profile before confirming", async () => {
    // The server rotated cookies and cleared email_verified. Without the
    // refresh the banner keeps naming the OLD address, which reads as "the
    // change didn't work" on the very screen that just said it did.
    const user = userEvent.setup();
    const refreshProfile = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ refreshProfile }));
    vi.spyOn(api, "changeEmail").mockResolvedValue(undefined);

    renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
    await user.type(screen.getByLabelText(/new email address/i), "right@example.com");
    await user.type(screen.getByLabelText(/current password/i), "Secret123");
    await user.click(screen.getByRole("button", { name: /change address/i }));

    await waitFor(() => expect(refreshProfile).toHaveBeenCalled());
    expect(await screen.findByText(/check your new inbox/i)).toBeInTheDocument();
    expect(screen.getByText("right@example.com")).toBeInTheDocument();
  });

  it("surfaces the server's reason verbatim", async () => {
    // "Current password is incorrect", "Email already registered" and "that is
    // already your address" each need a different next action from the user, so
    // collapsing them into one generic failure would leave them guessing.
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    vi.spyOn(api, "changeEmail").mockRejectedValue(
      new Error("Current password is incorrect"),
    );

    renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
    await user.type(screen.getByLabelText(/new email address/i), "right@example.com");
    await user.type(screen.getByLabelText(/current password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /change address/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /current password is incorrect/i,
    );
    // Still on the form, with the typed address kept — retyping it after a
    // wrong password is pure friction.
    expect(screen.getByLabelText(/new email address/i)).toHaveValue("right@example.com");
  });

  it("will not submit the address the account already has", async () => {
    // Server-side this is a 400; blocking it here saves the round-trip and the
    // scary-looking error for what is really a no-op.
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ email: "same@example.com" }));
    const change = vi.spyOn(api, "changeEmail").mockResolvedValue(undefined);

    renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
    await user.type(screen.getByLabelText(/new email address/i), "same@example.com");
    await user.type(screen.getByLabelText(/current password/i), "Secret123");
    expect(screen.getByRole("button", { name: /change address/i })).toBeDisabled();
    expect(change).not.toHaveBeenCalled();
  });

  it("treats a case-only difference as the same address", async () => {
    // Matches the server, which compares NORMALIZED addresses — otherwise the
    // button is enabled and the user gets a 400 for typing their own address.
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ email: "same@example.com" }));

    renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
    await user.type(screen.getByLabelText(/new email address/i), "SAME@Example.com");
    await user.type(screen.getByLabelText(/current password/i), "Secret123");
    expect(screen.getByRole("button", { name: /change address/i })).toBeDisabled();
  });

  it("requires both fields before enabling submit", async () => {
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());

    renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
    const submit = screen.getByRole("button", { name: /change address/i });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/new email address/i), "right@example.com");
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/current password/i), "Secret123");
    expect(submit).toBeEnabled();
  });

  it("reserves the error slot so a failure does not move the buttons", async () => {
    // ModalShell centres the card vertically, so growing it downward pushes the
    // whole card UP — putting the error below the buttons is NOT enough on its
    // own. The reserved slot is what actually holds them still.
    const user = userEvent.setup();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    vi.spyOn(api, "changeEmail").mockRejectedValue(new Error("Current password is incorrect"));

    renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
    const submit = screen.getByRole("button", { name: /change address/i });
    const before = submit.parentElement?.getBoundingClientRect().top;

    await user.type(screen.getByLabelText(/new email address/i), "right@example.com");
    await user.type(screen.getByLabelText(/current password/i), "wrong");
    await user.click(submit);
    await screen.findByRole("alert");

    expect(submit.parentElement?.getBoundingClientRect().top).toBe(before);
  });

  it("explains why it asks for the password", async () => {
    // Asking for a password to change an email looks like over-collection
    // unless the reason is stated where it is asked.
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
    expect(screen.getByText(/whoever can read your email can reset it/i)).toBeInTheDocument();
  });

  describe("in Czech", () => {
    beforeEach(() => useLocaleStore.setState({ locale: "cs", explicit: true }));
    afterEach(() =>
      useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false }),
    );

    it("renders no English on the form", () => {
      renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
      expect(untranslatedEnglishIn(document.body)).toEqual([]);
    });

    it("renders no English on the confirmation state", async () => {
      vi.spyOn(api, "changeEmail").mockResolvedValue(undefined);
      const user = userEvent.setup();
      renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
      await user.type(screen.getByLabelText(/nová e-mailová adresa/i), "novy@example.com");
      await user.type(screen.getByLabelText(/současné heslo/i), "CurrentPass123");
      await user.click(screen.getByRole("button", { name: /změnit adresu/i }));
      await waitFor(() =>
        expect(screen.getByText(/zkontrolujte novou schránku/i)).toBeInTheDocument(),
      );
      expect(untranslatedEnglishIn(document.body)).toEqual([]);
    });

    it.each([
      [429, { error: "Rate limit exceeded" }, "Příliš mnoho pokusů. Zkuste to prosím později."],
      [422, { detail: [{ msg: "value is not a valid email address" }] }, "Zadejte prosím platnou e-mailovou adresu."],
    ])("shows a %i in Czech, through the real request", async (status, body, czech) => {
      // The real changeEmail, not a spy: neither status carries a sentence the
      // server translated, so the Czech has to come from the copy this modal passes.
      vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
      // A spy, not vi.stubGlobal: unstubAllGlobals would also undo setup.ts's
      // localStorage stub for every later test in this file.
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
        Promise.resolve(
          (String(input).endsWith("/auth/email")
            ? { ok: false, status, json: () => Promise.resolve(body) }
            : { ok: true, status: 204, json: () => Promise.resolve({}) }) as Response,
        ),
      );
      try {
        const user = userEvent.setup();
        renderWithProviders(<ChangeEmailModal onClose={vi.fn()} />);
        await user.type(screen.getByLabelText(/nová e-mailová adresa/i), "novy@example.com");
        await user.type(screen.getByLabelText(/současné heslo/i), "CurrentPass123");
        await user.click(screen.getByRole("button", { name: /změnit adresu/i }));
        expect(await screen.findByRole("alert")).toHaveTextContent(czech);
        expect(untranslatedEnglishIn(document.body)).toEqual([]);
      } finally {
        fetchSpy.mockRestore();
      }
    });
  });
});
