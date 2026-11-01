import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/test-utils";
import { untranslatedEnglishIn } from "../../test/i18nAssertions";
import { TermsUpdateBanner } from "./TermsUpdateBanner";
import * as AuthCtx from "../../contexts/AuthContext";
import { TermsVersionStaleError } from "../../api";
import { useLocaleStore, DEFAULT_LOCALE } from "../../store/useLocaleStore";
import type { AuthState, TermsUpdate } from "../../types";

const UPDATE: TermsUpdate = {
  version: "2026-11-01",
  summary: { en: "Requests can now go to OpenAI.", cs: "Požadavky teď mohou jít i do OpenAI." },
};

/** Baseline: a logged-in user with a change due — the only state that renders. */
function authState(over: Partial<AuthState> = {}): AuthState {
  return {
    userId: 1,
    termsUpdate: UPDATE,
    acceptTerms: vi.fn().mockResolvedValue(undefined),
    isDemo: false,
    ...over,
  } as unknown as AuthState;
}

beforeEach(() => vi.restoreAllMocks());
// In act(): afterEach runs LIFO, so this fires while the banner is still mounted.
afterEach(() =>
  act(() => useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false })),
);

describe("TermsUpdateBanner", () => {
  it("shows the server's summary and the English documents", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<TermsUpdateBanner />);
    expect(screen.getByText(/changed our privacy policy and terms/i)).toBeInTheDocument();
    expect(screen.getByText(UPDATE.summary.en!)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute("href", "/privacy");
    expect(screen.getByRole("link", { name: "Terms of Service" })).toHaveAttribute("href", "/terms");
  });

  it("speaks Czech and links the Czech editions in a Czech UI", () => {
    useLocaleStore.setState({ locale: "cs", explicit: true });
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<TermsUpdateBanner />);
    expect(screen.getByText(UPDATE.summary.cs!)).toBeInTheDocument();
    expect(screen.getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      "/cs/privacy",
      "/cs/terms",
    ]);
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });

  it("falls back to English when the summary lacks the UI locale", () => {
    useLocaleStore.setState({ locale: "cs", explicit: true });
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(
      authState({ termsUpdate: { version: "v", summary: { en: "English only." } } }),
    );
    renderWithProviders(<TermsUpdateBanner />);
    expect(screen.getByText("English only.")).toBeInTheDocument();
  });

  it("offers no way to dismiss it other than agreeing", () => {
    // The point of the notice: it stays until the server has recorded "I agree".
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState());
    renderWithProviders(<TermsUpdateBanner />);
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["I agree"]);
  });

  it("records agreement to the version it showed", async () => {
    const state = authState();
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(state);
    renderWithProviders(<TermsUpdateBanner />);
    await userEvent.click(screen.getByRole("button", { name: "I agree" }));
    expect(state.acceptTerms).toHaveBeenCalledWith("2026-11-01");
  });

  it("explains a stale version instead of a generic failure", async () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(
      authState({ acceptTerms: vi.fn().mockRejectedValue(new TermsVersionStaleError()) }),
    );
    renderWithProviders(<TermsUpdateBanner />);
    await userEvent.click(screen.getByRole("button", { name: "I agree" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/changed again/i);
  });

  it("asks to retry when saving fails", async () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(
      authState({ acceptTerms: vi.fn().mockRejectedValue(new Error("network")) }),
    );
    renderWithProviders(<TermsUpdateBanner />);
    await userEvent.click(screen.getByRole("button", { name: "I agree" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/try again/i);
    expect(screen.getByRole("button", { name: "I agree" })).toBeEnabled();
  });

  it("renders NOTHING when no change is due", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ termsUpdate: null }));
    const { container } = renderWithProviders(<TermsUpdateBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders NOTHING when logged out", () => {
    vi.spyOn(AuthCtx, "useAuth").mockReturnValue(authState({ userId: null }));
    const { container } = renderWithProviders(<TermsUpdateBanner />);
    expect(container).toBeEmptyDOMElement();
  });
});
