import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { FunnelPanel } from "./FunnelPanel";
import type { FunnelStatsResponse } from "../../types";

// `subscribed` deliberately exceeds `paid` — the launch-week shape, where every
// subscription is still in its trial and the ledger has no invoice to show.
const stats: FunnelStatsResponse = {
  stages: [
    { key: "signed_up", label: "Signed up", count: 10 },
    { key: "verified", label: "Verified their email", count: 8 },
    { key: "generated", label: "Generated a recipe", count: 6 },
    { key: "confirmed", label: "Confirmed a plan", count: 4 },
    { key: "cooked", label: "Cooked a meal", count: 3 },
    { key: "subscribed", label: "Started a subscription", count: 5 },
    { key: "paid", label: "Paid an invoice", count: 2 },
  ],
  by_source: [
    {
      source: "google",
      signed_up: 6,
      verified: 5,
      generated: 4,
      confirmed: 3,
      cooked: 2,
      subscribed: 3,
      paid: 2,
    },
    {
      source: "direct",
      signed_up: 4,
      verified: 3,
      generated: 2,
      confirmed: 1,
      cooked: 1,
      subscribed: 2,
      paid: 0,
    },
  ],
};

describe("FunnelPanel", () => {
  it("shows the two headline conversion rates computed from the stages", () => {
    render(<FunnelPanel stats={stats} />);
    // 6/10 activated, 5/10 subscribed.
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("reads the subscription rate off `subscribed`, not `paid`", () => {
    // The whole point of the stage. With `paid` (2/10) this would read 20% —
    // and during a cohort's first 10 days, when no paid invoice can exist at
    // all, it would read 0% no matter how well the launch went.
    render(<FunnelPanel stats={stats} />);
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.queryByText("20%")).not.toBeInTheDocument();
  });

  it("renders a per-source row with each stage count", () => {
    render(<FunnelPanel stats={stats} />);
    const googleRow = screen.getByText("google").closest("tr")!;
    const cells = within(googleRow).getAllByRole("cell");
    // Source, signed_up, verified, generated, confirmed, cooked, subscribed, paid
    expect(cells.map((c) => c.textContent)).toEqual([
      "google",
      "6",
      "5",
      "4",
      "3",
      "2",
      "3",
      "2",
    ]);
  });

  it("shows an empty state when there are no signups", () => {
    render(
      <FunnelPanel
        stats={{ stages: stats.stages.map((s) => ({ ...s, count: 0 })), by_source: [] }}
      />,
    );
    expect(screen.getByText(/no signups yet/i)).toBeInTheDocument();
  });

  it("renders an em dash for conversion rates when there are zero signups", () => {
    render(
      <FunnelPanel
        stats={{ stages: stats.stages.map((s) => ({ ...s, count: 0 })), by_source: [] }}
      />,
    );
    // Both conversion stats divide by zero → "—", never "NaN%" or "Infinity%".
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/nan/i)).not.toBeInTheDocument();
  });
});
