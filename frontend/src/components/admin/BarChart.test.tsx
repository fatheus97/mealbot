import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BarChart } from "./BarChart";

describe("BarChart", () => {
  it("shows an empty state when there is no data", () => {
    render(<BarChart data={[]} />);
    expect(screen.getByText(/no data/i)).toBeInTheDocument();
  });

  it("renders one bar per datum with a value tooltip", () => {
    render(
      <BarChart
        data={[
          { label: "Mon", value: 10 },
          { label: "Tue", value: 20 },
        ]}
      />,
    );
    expect(screen.getByTitle("Mon: 10")).toBeInTheDocument();
    expect(screen.getByTitle("Tue: 20")).toBeInTheDocument();
  });
});
