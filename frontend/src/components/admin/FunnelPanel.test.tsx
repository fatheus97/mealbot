import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { FunnelPanel } from "./FunnelPanel";
import type { FunnelStatsResponse } from "../../types";

const stats: FunnelStatsResponse = {
  stages: [
    { key: "signed_up", label: "Signed up", count: 10 },
    { key: "generated", label: "Generated a recipe", count: 6 },
    { key: "confirmed", label: "Confirmed a plan", count: 4 },
    { key: "cooked", label: "Cooked a meal", count: 3 },
    { key: "paid", label: "Subscribed", count: 2 },
  ],
  by_source: [
    { source: "google", signed_up: 6, generated: 4, confirmed: 3, cooked: 2, paid: 2 },
    { source: "direct", signed_up: 4, generated: 2, confirmed: 1, cooked: 1, paid: 0 },
  ],
};

describe("FunnelPanel", () => {
  it("shows the two headline conversion rates computed from the stages", () => {
    render(<FunnelPanel stats={stats} />);
    // 6/10 activated, 2/10 subscribed.
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument();
  });

  it("renders a per-source row with each stage count", () => {
    render(<FunnelPanel stats={stats} />);
    const googleRow = screen.getByText("google").closest("tr")!;
    const cells = within(googleRow).getAllByRole("cell");
    // Source, signed_up, generated, confirmed, cooked, paid
    expect(cells.map((c) => c.textContent)).toEqual(["google", "6", "4", "3", "2", "2"]);
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
