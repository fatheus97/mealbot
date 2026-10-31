import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FavoriteHeart } from "./FavoriteHeart";
import { useLocaleStore } from "../store/useLocaleStore";

describe("FavoriteHeart", () => {
  afterEach(() => useLocaleStore.setState({ locale: "en" }));

  it("calls onToggle(true) when clicked while not favorited", async () => {
    const onToggle = vi.fn();
    render(<FavoriteHeart isFavorite={false} onToggle={onToggle} />);

    await userEvent.click(screen.getByRole("switch"));

    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onToggle).toHaveBeenCalledWith(true);
  });

  it("calls onToggle(false) when clicked while favorited", async () => {
    const onToggle = vi.fn();
    render(<FavoriteHeart isFavorite={true} onToggle={onToggle} />);

    await userEvent.click(screen.getByRole("switch"));

    expect(onToggle).toHaveBeenCalledWith(false);
  });

  it("reflects favorited state via aria-checked", () => {
    const { rerender } = render(<FavoriteHeart isFavorite={false} onToggle={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    rerender(<FavoriteHeart isFavorite={true} onToggle={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("does not fire onToggle when disabled", async () => {
    const onToggle = vi.fn();
    render(<FavoriteHeart isFavorite={false} onToggle={onToggle} disabled />);

    await userEvent.click(screen.getByRole("switch"));

    expect(onToggle).not.toHaveBeenCalled();
  });

  it("uses appropriate aria-label per state", () => {
    const { rerender } = render(<FavoriteHeart isFavorite={false} onToggle={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAccessibleName("Add to cookbook");
    rerender(<FavoriteHeart isFavorite={true} onToggle={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAccessibleName("Remove from cookbook");
  });

  it("names itself in Czech for a Czech user", () => {
    // The star's label was a hardcoded English literal, so Czech users heard
    // English from a screen reader.
    useLocaleStore.setState({ locale: "cs" });
    const { rerender } = render(<FavoriteHeart isFavorite={false} onToggle={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAccessibleName("Přidat do kuchařky");
    rerender(<FavoriteHeart isFavorite={true} onToggle={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAccessibleName("Odebrat z kuchařky");
  });
});

describe("FavoriteHeart conveys state by shape, not colour alone", () => {
  // The two colours are 1.3:1 against EACH OTHER. If the heart looked the same
  // in both states, "saved" would be carried by colour alone (WCAG 1.4.1).
  // Ratios against the surfaces are pinned in test/contrast.test.ts; this pins
  // the shape.
  const heart = () => screen.getByRole("switch").querySelector("svg");

  it("draws an outline heart when not saved and a filled one when saved", () => {
    const { rerender } = render(<FavoriteHeart isFavorite={false} onToggle={() => {}} />);
    expect(heart()).toHaveAttribute("fill", "none");
    rerender(<FavoriteHeart isFavorite={true} onToggle={() => {}} />);
    expect(heart()).toHaveAttribute("fill", "currentColor");
  });

  it("is a drawn heart, not a glyph a platform may swap for an emoji", () => {
    render(<FavoriteHeart isFavorite={true} onToggle={() => {}} />);
    expect(screen.getByRole("switch").textContent).toBe("");
    expect(heart()).toHaveAttribute("aria-hidden", "true");
  });

  it("still changes colour as well, so the cue is doubled not swapped", () => {
    const { rerender } = render(<FavoriteHeart isFavorite={false} onToggle={() => {}} />);
    const unsaved = screen.getByRole("switch").style.color;
    rerender(<FavoriteHeart isFavorite={true} onToggle={() => {}} />);
    expect(screen.getByRole("switch").style.color).not.toBe(unsaved);
  });
});
