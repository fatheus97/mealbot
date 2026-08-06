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

describe("FavoriteStar conveys state by shape, not colour alone", () => {
  // The two colours are 1.04:1 against EACH OTHER — near-identical luminance,
  // differing only in hue. If the glyph were the same in both states, "saved"
  // would be carried by colour alone (WCAG 1.4.1). Ratios against the surfaces
  // are pinned in test/contrast.test.ts; this pins the shape.
  it("uses an outline star when not saved and a filled one when saved", () => {
    const { rerender } = render(<FavoriteStar isFavorite={false} onToggle={() => {}} />);
    expect(screen.getByRole("switch").textContent).toBe("☆");
    rerender(<FavoriteStar isFavorite={true} onToggle={() => {}} />);
    expect(screen.getByRole("switch").textContent).toBe("★");
  });

  it("still changes colour as well, so the cue is doubled not swapped", () => {
    const { rerender } = render(<FavoriteStar isFavorite={false} onToggle={() => {}} />);
    const unsaved = screen.getByRole("switch").style.color;
    rerender(<FavoriteStar isFavorite={true} onToggle={() => {}} />);
    expect(screen.getByRole("switch").style.color).not.toBe(unsaved);
  });
});
