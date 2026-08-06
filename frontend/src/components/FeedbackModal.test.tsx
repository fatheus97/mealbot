import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { FeedbackModal } from "./FeedbackModal";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import * as api from "../api";

vi.mock("../api", () => ({
  // AuthProvider calls authFetch on mount — stub it.
  authFetch: vi.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) })),
  submitFeedback: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe("FeedbackModal", () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it("leaves no untranslated English when switched to Czech, form AND thanks", async () => {
    // The thank-you state REPLACES the form, so one render can only ever prove
    // one of them. This whole modal shipped untranslated behind an already-
    // translated "Poslat zpětnou vazbu" button — the button was migrated with
    // SettingsPopup and the modal it opens never was.
    vi.spyOn(api, "submitFeedback").mockResolvedValue({ id: 1 } as never);
    useLocaleStore.setState({ locale: "cs", explicit: true });

    const { container } = renderWithProviders(<FeedbackModal onClose={vi.fn()} />);
    expect(screen.getByText("Poslat zpětnou vazbu")).toBeInTheDocument();
    expect(untranslatedEnglishIn(container)).toEqual([]);

    const user = userEvent.setup();
    await user.type(
      screen.getByPlaceholderText(/Co se stalo/),
      "Tohle je dost dlouhá zpráva na odeslání.",
    );
    await user.click(screen.getByRole("button", { name: "Odeslat" }));
    await waitFor(() => expect(screen.getByText(/máme to/)).toBeInTheDocument());
    expect(untranslatedEnglishIn(container)).toEqual([]);
  });

  it("keeps Send disabled until the message is long enough", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FeedbackModal onClose={() => {}} />);

    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();

    await user.type(screen.getByPlaceholderText(/what happened/i), "short");
    expect(send).toBeDisabled(); // < 10 chars trimmed

    await user.type(screen.getByPlaceholderText(/what happened/i), " but now much longer");
    expect(send).toBeEnabled();
  });

  it("submits the report and shows the thank-you state", async () => {
    vi.mocked(api.submitFeedback).mockResolvedValue({ id: 7, status: "new" });
    const user = userEvent.setup();
    renderWithProviders(<FeedbackModal page="settings" onClose={() => {}} />);

    await user.selectOptions(screen.getByRole("combobox"), "feature");
    await user.type(
      screen.getByPlaceholderText(/what happened/i),
      "Please add a weekly shopping list export.",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(api.submitFeedback).toHaveBeenCalledWith({
        kind: "feature",
        message: "Please add a weekly shopping list export.",
        page: "settings",
      }),
    );
    expect(await screen.findByText(/thanks — we got it/i)).toBeInTheDocument();
  });

  it("surfaces a server error and stays on the form", async () => {
    vi.mocked(api.submitFeedback).mockRejectedValue(
      new Error("You've already sent this — thanks, we have it."),
    );
    const user = userEvent.setup();
    renderWithProviders(<FeedbackModal onClose={() => {}} />);

    await user.type(
      screen.getByPlaceholderText(/what happened/i),
      "The regenerate button is broken.",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already sent/i);
    // Still on the form (not the thank-you) — retryable.
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });
});
