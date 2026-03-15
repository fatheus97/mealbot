import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StarRating } from "./StarRating";

describe("StarRating", () => {
  it("renders 5 stars", () => {
    render(<StarRating rating={null} onRate={vi.fn()} />);
    const stars = screen.getAllByRole("button");
    expect(stars).toHaveLength(5);
  });

  it("calls onRate with correct value when clicked", async () => {
    const onRate = vi.fn();
    const user = userEvent.setup();
    render(<StarRating rating={null} onRate={onRate} />);

    await user.click(screen.getByLabelText("Rate 3 stars"));
    expect(onRate).toHaveBeenCalledWith(3);
  });

  it("does not call onRate when disabled", async () => {
    const onRate = vi.fn();
    const user = userEvent.setup();
    render(<StarRating rating={null} onRate={onRate} disabled />);

    await user.click(screen.getByLabelText("Rate 3 stars"));
    expect(onRate).not.toHaveBeenCalled();
  });

  it("displays correct aria labels", () => {
    render(<StarRating rating={2} onRate={vi.fn()} />);
    expect(screen.getByLabelText("Rate 1 star")).toBeInTheDocument();
    expect(screen.getByLabelText("Rate 2 stars")).toBeInTheDocument();
    expect(screen.getByLabelText("Rate 5 stars")).toBeInTheDocument();
  });
});
