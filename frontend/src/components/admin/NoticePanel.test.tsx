import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/test-utils";
import { NoticePanel } from "./NoticePanel";
import * as api from "../../api";
import type { PolicyNoticePreview } from "../../types";

vi.mock("../../api", () => ({
  // AuthProvider calls authFetch("/config") on mount — stub it.
  authFetch: vi.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) })),
  fetchPolicyNotice: vi.fn(),
  sendPolicyNotice: vi.fn(),
}));

function preview(over: Partial<PolicyNoticePreview> = {}): PolicyNoticePreview {
  return {
    campaign: "policy-2026-11-01",
    counts: { eligible: 2, sent: 1, unconfirmed: 0, accepted_in_app: 3, excluded: 1 },
    daily_limit: 50,
    sent_last_24h: 0,
    email_configured: true,
    previews: [
      { locale: "en", subject: "We've changed it", html: "<p>Hi</p>" },
      { locale: "cs", subject: "Změnili jsme to", html: "<p>Dobrý den</p>" },
    ],
    ...over,
  };
}

beforeEach(() => vi.clearAllMocks());

describe("NoticePanel", () => {
  it("shows the counts and each locale's email in a sandboxed frame", async () => {
    vi.mocked(api.fetchPolicyNotice).mockResolvedValue(preview());
    renderWithProviders(<NoticePanel />);

    expect(await screen.findByText("policy-2026-11-01")).toBeInTheDocument();
    expect(screen.getByText("Agreed in app").parentElement).toHaveTextContent("3");
    const frames = screen.getAllByTitle(/notice email preview/i);
    expect(frames).toHaveLength(2);
    for (const frame of frames) {
      // Empty sandbox: no scripts, no same-origin access to the admin session.
      expect(frame).toHaveAttribute("sandbox", "");
    }
    expect(frames[1]).toHaveAttribute("srcdoc", "<p>Dobrý den</p>");
  });

  it("sends the SHOWN eligible count as the confirmation, after a dialog", async () => {
    vi.mocked(api.fetchPolicyNotice).mockResolvedValue(preview());
    vi.mocked(api.sendPolicyNotice).mockResolvedValue({ campaign: "policy-2026-11-01", queued: 2 });
    renderWithProviders(<NoticePanel />);

    await userEvent.click(await screen.findByRole("button", { name: "Send to 2 users" }));
    expect(api.sendPolicyNotice).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send" }));

    await waitFor(() => expect(api.sendPolicyNotice).toHaveBeenCalledWith(2));
    expect(await screen.findByRole("status")).toHaveTextContent("Queued 2");
  });

  it("shows the server's refusal", async () => {
    vi.mocked(api.fetchPolicyNotice).mockResolvedValue(preview());
    vi.mocked(api.sendPolicyNotice).mockRejectedValue(
      new Error("The recipient count changed from 2 to 3. Review the preview again."),
    );
    renderWithProviders(<NoticePanel />);

    await userEvent.click(await screen.findByRole("button", { name: "Send to 2 users" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("changed from 2 to 3");
  });

  it("caps the button at the remaining daily quota", async () => {
    vi.mocked(api.fetchPolicyNotice).mockResolvedValue(
      preview({ daily_limit: 50, sent_last_24h: 49 }),
    );
    renderWithProviders(<NoticePanel />);
    expect(await screen.findByRole("button", { name: "Send to 1 user" })).toBeEnabled();
  });

  it.each([
    ["Resend is not configured", { email_configured: false }, /RESEND_API_KEY/],
    [
      "nobody is eligible",
      { counts: { eligible: 0, sent: 2, unconfirmed: 0, accepted_in_app: 0, excluded: 0 } },
      /Nobody/,
    ],
    ["the quota is spent", { sent_last_24h: 50 }, /quota/],
  ])("disables sending when %s", async (_name, over, reason) => {
    vi.mocked(api.fetchPolicyNotice).mockResolvedValue(preview(over));
    renderWithProviders(<NoticePanel />);
    expect(await screen.findByText(reason)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Send to/ })).toBeDisabled();
  });
});
