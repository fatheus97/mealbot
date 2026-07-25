import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { FeedbackModal } from "./FeedbackModal";
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
