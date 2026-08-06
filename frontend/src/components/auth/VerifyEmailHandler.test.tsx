import { StrictMode } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../../test/test-utils";
import { VerifyEmailHandler } from "./VerifyEmailHandler";
import * as AuthCtx from "../../contexts/AuthContext";
import * as api from "../../api";
import type { AuthState } from "../../types";
import { useLocaleStore, DEFAULT_LOCALE } from "../../store/useLocaleStore";
import { untranslatedEnglishIn } from "../../test/i18nAssertions";
import { cs } from "../../i18n/cs";

function mockAuth(over: Partial<AuthState> = {}) {
  vi.spyOn(AuthCtx, "useAuth").mockReturnValue({
    userId: 1,
    emailVerified: false,
    refreshProfile: vi.fn().mockResolvedValue(undefined),
    ...over,
  } as unknown as AuthState);
}

function setUrl(search: string) {
  window.history.replaceState(null, "", `/app${search}`);
}

beforeEach(() => {
  vi.restoreAllMocks();
  setUrl("");
});
afterEach(() => setUrl(""));

describe("VerifyEmailHandler", () => {
  it("renders nothing when there is no verify_token", () => {
    mockAuth();
    const spy = vi.spyOn(api, "verifyEmail");
    const { container } = renderWithProviders(<VerifyEmailHandler />);
    expect(container).toBeEmptyDOMElement();
    expect(spy).not.toHaveBeenCalled();
  });

  it("redeems the token, confirms, and STRIPS it from the URL", async () => {
    // Stripping matters: the token is single-use, so a reload would otherwise
    // replay it and show a failure for a confirmation that worked — and it
    // would linger in history.
    mockAuth();
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc123");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() => expect(screen.getByText(/email confirmed/i)).toBeInTheDocument());
    expect(api.verifyEmail).toHaveBeenCalledWith("abc123");
    expect(window.location.search).not.toContain("verify_token");
  });

  it("preserves other query params while stripping the token", async () => {
    mockAuth();
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc&utm_source=news");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() => expect(screen.getByText(/email confirmed/i)).toBeInTheDocument());
    expect(window.location.search).toContain("utm_source=news");
    expect(window.location.search).not.toContain("verify_token");
  });

  it("refreshes the profile on success so the banner disappears immediately", async () => {
    const refreshProfile = vi.fn().mockResolvedValue(undefined);
    mockAuth({ refreshProfile });
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() => expect(refreshProfile).toHaveBeenCalled());
  });

  it("works logged-OUT (the link often opens in a different browser)", async () => {
    const refreshProfile = vi.fn();
    mockAuth({ userId: null, refreshProfile });
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() => expect(screen.getByText(/email confirmed/i)).toBeInTheDocument());
    // Nothing to refresh when no one is signed in here.
    expect(refreshProfile).not.toHaveBeenCalled();
  });

  it("tells a signed-in unverified user to use the banner Resend control", async () => {
    mockAuth({ userId: 1, emailVerified: false });
    vi.spyOn(api, "verifyEmail").mockRejectedValue(new Error("expired"));
    setUrl("?verify_token=stale");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() =>
      expect(screen.getByText(/invalid or has expired/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/banner above/i)).toBeInTheDocument();
  });

  it("redeems ONCE under a real StrictMode double-invoke", async () => {
    // The token is single-use: a second redeem would 400 and report failure
    // for a confirmation that actually succeeded.
    mockAuth();
    const spy = vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc");

    renderWithProviders(
      <StrictMode>
        <VerifyEmailHandler />
      </StrictMode>,
    );
    await waitFor(() => expect(screen.getByText(/email confirmed/i)).toBeInTheDocument());
    expect(spy).toHaveBeenCalledTimes(1);
  });

  // NOTE ON COVERAGE, so the next reader doesn't mistake breadth for depth:
  // the StrictMode test above passes with `startedRef` DELETED. Verified by
  // mutation, including with history.replaceState stubbed to a no-op so the
  // token survives — the double redeem still doesn't happen. StrictMode really
  // does double-invoke here (checked separately: 2 effect runs), so single-
  // redeem is coming from somewhere other than the latch.
  //
  // The latch is therefore kept as belt-and-braces, NOT as the tested
  // mechanism, and no test here asserts it — an assertion that passes with the
  // code removed is worse than none, which is exactly the vacuity this comment
  // exists to stop being reintroduced. Same honesty as password_reset's
  // with_for_update(): defensive, deliberate, uncovered, documented.

  it("does not re-redeem after a genuine remount (the token is already stripped)", async () => {
    mockAuth();
    const spy = vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc");

    const { unmount } = renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    unmount();

    // A fresh instance sees the stripped URL and must do nothing — this is the
    // case that made mounting inside the userId-keyed MainLayout a bug.
    renderWithProviders(<VerifyEmailHandler />);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("treats a failed link as SUCCESS when the user is already verified", async () => {
    // Clicking the same link twice is the common case; reporting "invalid or
    // expired" for an address that IS confirmed would be alarming and wrong.
    mockAuth({ userId: 1, emailVerified: true });
    vi.spyOn(api, "verifyEmail").mockRejectedValue(new Error("used"));
    setUrl("?verify_token=used");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() =>
      expect(screen.getByText(/already used — your email is confirmed/i)).toBeInTheDocument(),
    );
  });

  it("points a logged-OUT visitor at signing in, not at a banner they can't see", async () => {
    // EmailVerificationBanner (which owns the Resend control) renders nothing
    // when logged out, so telling them to use it would be a dead end.
    mockAuth({ userId: null, emailVerified: false });
    vi.spyOn(api, "verifyEmail").mockRejectedValue(new Error("expired"));
    setUrl("?verify_token=stale");

    renderWithProviders(<VerifyEmailHandler />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText(/sign in and use/i)).toBeInTheDocument();
  });

  it("announces a failure assertively (role=alert), not politely", async () => {
    mockAuth({ userId: 1, emailVerified: false });
    vi.spyOn(api, "verifyEmail").mockRejectedValue(new Error("expired"));
    setUrl("?verify_token=stale");

    renderWithProviders(<VerifyEmailHandler />);
    // A polite role=status can be missed entirely — this is the only thing
    // telling the user their confirmation didn't work.
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });

  it("floats out of document flow so it can't shift the page (CLS)", async () => {
    mockAuth();
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc");

    renderWithProviders(<VerifyEmailHandler />);
    const toast = await screen.findByRole("status");
    expect(toast.style.position).toBe("fixed");
    // Self-contained surface: both halves set together, or it can go
    // dark-on-dark in the other colour scheme.
    expect(toast.style.backgroundColor).toBeTruthy();
    expect(toast.style.color).toBeTruthy();
  });
});

describe("VerifyEmailHandler in Czech", () => {
  // This component had NO `t()` call at all until now, which is why the sweep
  // that translated the rest of auth walked past it: `untranslatedEnglishIn`
  // compares the DOM against `en`, so a literal with no key has nothing to
  // match and reads as clean. See test/i18nAssertions.ts, SCOPE 2.
  //
  // All four message branches are driven, because each one REPLACES the others
  // — one render can only ever prove one of them.
  beforeEach(() => useLocaleStore.setState({ locale: "cs", explicit: true }));
  afterEach(() =>
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false }),
  );

  it("translates the success toast", async () => {
    mockAuth();
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc");

    renderWithProviders(<VerifyEmailHandler />);
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent("E-mail potvrzen");
    expect(untranslatedEnglishIn(toast)).toEqual([]);
  });

  it("translates the already-used toast", async () => {
    mockAuth({ userId: 1, emailVerified: true });
    vi.spyOn(api, "verifyEmail").mockRejectedValue(new Error("expired"));
    setUrl("?verify_token=stale");

    renderWithProviders(<VerifyEmailHandler />);
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent("už byl použit");
    expect(untranslatedEnglishIn(toast)).toEqual([]);
  });

  it("translates the invalid-link toast, naming the Czech Resend label", async () => {
    mockAuth({ userId: 1, emailVerified: false });
    vi.spyOn(api, "verifyEmail").mockRejectedValue(new Error("expired"));
    setUrl("?verify_token=stale");

    renderWithProviders(<VerifyEmailHandler />);
    const toast = await screen.findByRole("alert");
    // The sentence quotes a BUTTON the user has to find on screen, so it must
    // carry that button's Czech label — quoting the English one would send
    // them looking for a control that does not exist in this UI.
    expect(toast).toHaveTextContent(cs["verify.resend"]);
    expect(untranslatedEnglishIn(toast)).toEqual([]);
  });

  it("translates the logged-out invalid-link toast", async () => {
    mockAuth({ userId: null, emailVerified: false });
    vi.spyOn(api, "verifyEmail").mockRejectedValue(new Error("expired"));
    setUrl("?verify_token=stale");

    renderWithProviders(<VerifyEmailHandler />);
    const toast = await screen.findByRole("alert");
    expect(toast).toHaveTextContent("Přihlaste se");
    expect(untranslatedEnglishIn(toast)).toEqual([]);
  });

  it("translates the dismiss control's accessible name", async () => {
    // aria-label never appears in textContent, so the survivor check above
    // reads it separately and a render assertion would not have caught it.
    mockAuth();
    vi.spyOn(api, "verifyEmail").mockResolvedValue(undefined);
    setUrl("?verify_token=abc");

    renderWithProviders(<VerifyEmailHandler />);
    await screen.findByRole("status");
    expect(screen.getByRole("button", { name: cs["verifyToast.dismiss"] }))
      .toBeInTheDocument();
  });
});
