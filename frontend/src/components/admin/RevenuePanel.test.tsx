import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RevenuePanel } from "./RevenuePanel";
import type { RevenueStats } from "../../types";

function stats(overrides: Partial<RevenueStats> = {}): RevenueStats {
  return {
    currency: "eur",
    total_cents: 5000,
    sales_count: 3,
    eu_cross_border_b2c_cents: 3000,
    cz_domestic_cents: 2000,
    non_eur_sales_count: 0,
    eur_czk_rate: 25,
    thresholds: [
      {
        key: "eu_oss",
        label: "EU cross-border B2C (OSS)",
        current: 30,
        threshold: 10000,
        unit: "EUR",
        pct: 0.003,
        note: "B2C sales to other EU countries.",
      },
      {
        key: "cz_domestic",
        label: "CZ domestic turnover",
        current: 1250,
        threshold: 2000000,
        unit: "CZK",
        pct: 0.000625,
        note: "All turnover ≈CZK.",
      },
    ],
    by_country: [
      { country: "DE", is_eu: true, amount_cents: 3000, sales: 2 },
      { country: "US", is_eu: false, amount_cents: 2000, sales: 1 },
    ],
    recent: [{ occurred_at: "2026-07-13T00:00:00", amount_cents: 1000, currency: "eur", country: "DE", is_business: false }],
    ...overrides,
  };
}

describe("RevenuePanel", () => {
  it("shows an empty state when there are no sales", () => {
    render(<RevenuePanel stats={stats({ sales_count: 0, non_eur_sales_count: 0, by_country: [], recent: [], total_cents: 0 })} />);
    expect(screen.getByText(/no sales recorded yet/i)).toBeInTheDocument();
  });

  it("renders both threshold progress bars with aria values", () => {
    render(<RevenuePanel stats={stats()} />);
    const eu = screen.getByRole("progressbar", { name: /EU cross-border/i });
    expect(eu).toHaveAttribute("aria-valuenow", "0"); // 0.3% rounds to 0
    expect(screen.getByRole("progressbar", { name: /CZ domestic/i })).toBeInTheDocument();
  });

  it("caps aria-valuenow at 100 once a threshold is crossed", () => {
    const s = stats();
    s.thresholds[0] = { ...s.thresholds[0], current: 15000, pct: 1.5 };
    render(<RevenuePanel stats={s} />);
    expect(screen.getByRole("progressbar", { name: /EU cross-border/i })).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
  });

  it("renders totals and the by-country table", () => {
    render(<RevenuePanel stats={stats()} />);
    expect(screen.getByText(/€50\.00/)).toBeInTheDocument(); // total_cents 5000
    expect(screen.getByText("DE")).toBeInTheDocument();
    expect(screen.getByText("US")).toBeInTheDocument();
  });

  it("flags excluded non-EUR sales", () => {
    render(<RevenuePanel stats={stats({ non_eur_sales_count: 2 })} />);
    expect(screen.getByText(/non-EUR sale\(s\) excluded/i)).toBeInTheDocument();
  });
});
