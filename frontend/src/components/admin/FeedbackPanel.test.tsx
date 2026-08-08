import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../../test/test-utils";
import { FeedbackPanel } from "./FeedbackPanel";
import * as api from "../../api";
import type { AdminFeedbackDetail, AdminFeedbackListResponse } from "../../types";

vi.mock("../../api", () => ({
  authFetch: vi.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) })),
  fetchAdminFeedback: vi.fn(),
  fetchAdminFeedbackDetail: vi.fn(),
  updateAdminFeedback: vi.fn(),
  retriageAdminFeedback: vi.fn(),
  acceptAdminFeedback: vi.fn(),
}));

const listResp: AdminFeedbackListResponse = {
  total: 1,
  limit: 25,
  offset: 0,
  items: [
    {
      id: 1,
      user_id: 2,
      user_email: "reporter@example.com",
      kind: "bug",
      status: "new",
      created_at: "2026-07-24T10:00:00Z",
      preview: "the plan crashes",
      triage_status: "done",
      triage_is_actionable: true,
      triage_type: "bug",
      triage_severity: "high",
      triage_title: "Plan crash on regenerate",
    },
  ],
};

const detailResp: AdminFeedbackDetail = {
  id: 1,
  user_id: 2,
  user_email: "reporter@example.com",
  kind: "bug",
  message: "The plan view crashes when I click regenerate twice.",
  page: "settings",
  screenshot_base64: null,
  screenshot_content_type: null,
  status: "new",
  created_at: "2026-07-24T10:00:00Z",
  triage_status: "done",
  triage: {
    is_actionable: true,
    type: "bug",
    severity: "high",
    title: "Plan crash on regenerate",
    summary: "The plan view crashes on a double regenerate.",
    repro: "Open a plan, click regenerate twice.",
    dedupe_hint: "plan crash",
  },
  reviewed_by_admin_id: null,
  reviewed_at: null,
  credit_cents: null,
  credit_granted_at: null,
  ticket_url: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  vi.mocked(api.fetchAdminFeedback).mockResolvedValue(listResp);
  vi.mocked(api.fetchAdminFeedbackDetail).mockResolvedValue(detailResp);
  vi.mocked(api.updateAdminFeedback).mockResolvedValue({ ...detailResp, status: "reviewing" });
  vi.mocked(api.retriageAdminFeedback).mockResolvedValue(detailResp);
  vi.mocked(api.acceptAdminFeedback).mockResolvedValue({
    ...detailResp,
    status: "accepted",
    credit_cents: 100,
    credit_granted_at: "2026-07-25T10:00:00Z",
    ticket_url: "https://github.com/owner/tickets/issues/3",
  });
});

describe("FeedbackPanel", () => {
  it("lists reports with triage + status and defaults to the New filter", async () => {
    renderWithProviders(<FeedbackPanel />);
    expect(await screen.findByText("Plan crash on regenerate")).toBeInTheDocument();
    expect(screen.getByText("reporter@example.com")).toBeInTheDocument();
    // Advisory triage pills + status pill are rendered.
    expect(screen.getByText("high")).toBeInTheDocument();
    // Defaulted to the "new" queue on mount.
    expect(api.fetchAdminFeedback).toHaveBeenCalledWith(
      expect.objectContaining({ status: "new", limit: 25, offset: 0 }),
    );
  });

  it("refetches when the status filter changes", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FeedbackPanel />);
    await screen.findByText("Plan crash on regenerate");

    await user.selectOptions(screen.getByRole("combobox"), "spam");
    await waitFor(() =>
      expect(api.fetchAdminFeedback).toHaveBeenCalledWith(
        expect.objectContaining({ status: "spam", offset: 0 }),
      ),
    );
  });

  it("opens the detail drawer and moderates a report", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FeedbackPanel />);
    await screen.findByText("Plan crash on regenerate");

    await user.click(screen.getByRole("button", { name: "View" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/the plan view crashes when i click regenerate twice/i),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/open a plan, click regenerate twice/i)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Reviewing" }));
    await waitFor(() => expect(api.updateAdminFeedback).toHaveBeenCalledWith(1, "reviewing"));
  });

  it("accepts a report (credit + ticket) in ONE click — no confirm step", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FeedbackPanel />);
    await screen.findByText("Plan crash on regenerate");

    await user.click(screen.getByRole("button", { name: "View" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^✓ Accept/ }));

    await waitFor(() => expect(api.acceptAdminFeedback).toHaveBeenCalledWith(1));
    // No second dialog to dismiss: the accept fired straight from the button.
    expect(screen.queryByRole("dialog", { name: /accept this report/i })).toBeNull();
  });

  it("re-runs advisory triage from the drawer", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FeedbackPanel />);
    await screen.findByText("Plan crash on regenerate");

    await user.click(screen.getByRole("button", { name: "View" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Re-run" }));
    await waitFor(() => expect(api.retriageAdminFeedback).toHaveBeenCalledWith(1));
  });

  it("renders an attached screenshot in the detail drawer", async () => {
    vi.mocked(api.fetchAdminFeedbackDetail).mockResolvedValue({
      ...detailResp,
      screenshot_base64: "c2NyZWVuc2hvdA==",
      screenshot_content_type: "image/png",
    });
    const user = userEvent.setup();
    renderWithProviders(<FeedbackPanel />);
    await screen.findByText("Plan crash on regenerate");

    await user.click(screen.getByRole("button", { name: "View" }));
    const dialog = await screen.findByRole("dialog");
    const img = within(dialog).getByAltText(/attached screenshot/i) as HTMLImageElement;
    expect(img.src).toBe("data:image/png;base64,c2NyZWVuc2hvdA==");
  });

  it("shows no screenshot when the report has none", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FeedbackPanel />);
    await screen.findByText("Plan crash on regenerate");

    await user.click(screen.getByRole("button", { name: "View" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByAltText(/attached screenshot/i)).not.toBeInTheDocument();
  });
});
