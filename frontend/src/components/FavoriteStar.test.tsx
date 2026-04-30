import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FavoriteStar } from "./FavoriteStar";

describe("FavoriteStar", () => {
  it("calls onToggle(true) when clicked while not favorited", async () => {
    const onToggle = vi.fn();
    render(<FavoriteStar isFavorite={false} onToggle={onToggle} />);

    await userEvent.click(screen.getByRole("switch"));

    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onToggle).toHaveBeenCalledWith(true);
  });

  it("calls onToggle(false) when clicked while favorited", async () => {
    const onToggle = vi.fn();
    render(<FavoriteStar isFavorite={true} onToggle={onToggle} />);

    await userEvent.click(screen.getByRole("switch"));

    expect(onToggle).toHaveBeenCalledWith(false);
  });

  it("reflects favorited state via aria-checked", () => {
    const { rerender } = render(<FavoriteStar isFavorite={false} onToggle={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    rerender(<FavoriteStar isFavorite={true} onToggle={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("does not fire onToggle when disabled", async () => {
    const onToggle = vi.fn();
    render(<FavoriteStar isFavorite={false} onToggle={onToggle} disabled />);

    await userEvent.click(screen.getByRole("switch"));

    expect(onToggle).not.toHaveBeenCalled();
  });

  it("uses appropriate aria-label per state", () => {
    const { rerender } = render(<FavoriteStar isFavorite={false} onToggle={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAccessibleName("Add to cookbook");
    rerender(<FavoriteStar isFavorite={true} onToggle={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAccessibleName("Remove from cookbook");
  });
});
