import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setMobileViewport } from "../test/test-utils";
import { InfoHint } from "./InfoHint";

/** Listeners registered by the Escape tests, torn down in afterEach. */
const escapeWatchers: Array<() => void> = [];

/**
 * Stand in for an enclosing modal's Escape handler.
 *
 * Bubble-phase on `window`, which is exactly how ModalShell / PaywallModal /
 * CookbookModal register theirs — a capture-phase or document-level stub would
 * not reproduce the ordering the fix depends on.
 */
function watchEscape() {
  const spy = vi.fn();
  const handler = (e: KeyboardEvent) => {
    if (e.key === "Escape") spy();
  };
  window.addEventListener("keydown", handler);
  escapeWatchers.push(() => window.removeEventListener("keydown", handler));
  return spy;
}

afterEach(() => {
  // Without this a leaked listener outlives its test and quietly counts the
  // NEXT test's key presses — the stub-cleanup trap in
  // .claude/rules/frontend.md, one layer up.
  while (escapeWatchers.length) escapeWatchers.pop()!();
});

describe("InfoHint", () => {
  it("renders a labelled trigger with the tooltip hidden until interacted with", () => {
    render(<InfoHint text="Helpful explanation" label="More info" />);
    const trigger = screen.getByRole("button", { name: "More info" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(screen.queryByText("Helpful explanation")).not.toBeInTheDocument();
  });

  it("reveals on hover and hides on unhover, wiring aria-describedby", async () => {
    const user = userEvent.setup();
    render(<InfoHint text="Helpful explanation" />);
    const trigger = screen.getByRole("button", { name: "More information" });

    await user.hover(trigger);
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("Helpful explanation");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-describedby", tip.id);

    await user.unhover(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("opens on click so touch taps work", async () => {
    const user = userEvent.setup();
    render(<InfoHint text="Tap explanation" />);
    await user.click(screen.getByRole("button", { name: "More information" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Tap explanation");
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<InfoHint text="Esc explanation" />);
    await user.click(screen.getByRole("button", { name: "More information" }));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("CONSUMES the Escape, so an enclosing modal does not close too", async () => {
    // Regression: the hint used to let Escape through, so pressing it inside
    // ModalShell / PaywallModal / CookbookModal dismissed the hint AND the
    // modal — taking away the very thing the hint was explaining. One Escape
    // should dismiss one layer, innermost first.
    const user = userEvent.setup();
    const modalEscape = watchEscape();

    render(<InfoHint text="Nested explanation" />);
    await user.click(screen.getByRole("button", { name: "More information" }));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(modalEscape).not.toHaveBeenCalled();
  });

  it("does NOT swallow Escape once closed — the modal gets it", async () => {
    // The other half, and the one that would make this a bug rather than a
    // fix: an idle hint must not register a global listener at all, or every
    // hint on the page would eat the modal's Escape.
    const user = userEvent.setup();
    const modalEscape = watchEscape();

    render(<InfoHint text="Idle explanation" />);
    await user.keyboard("{Escape}");
    expect(modalEscape).toHaveBeenCalledTimes(1);
  });

  it("closes on an outside pointerdown (tap-away) — the touch dismissal path", async () => {
    const user = userEvent.setup();
    render(<InfoHint text="Outside explanation" />);
    const trigger = screen.getByRole("button", { name: "More information" });

    // Open via HOVER, not click/focus, so the document pointerdown listener is the only
    // thing that can close it — otherwise onBlur masks this branch (it fires on any focus
    // loss and the assertion would pass even if outside-dismissal were broken).
    await user.hover(trigger);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("keeps the trigger a square on mobile (defeats index.css min-height:40 → no pill)", () => {
    setMobileViewport(true);
    render(<InfoHint text="Mobile explanation" />);
    const trigger = screen.getByRole("button", { name: "More information" });
    // An explicit inline minHeight is what overrides the mobile `button { min-height:40 }`
    // rule; without it the fixed-height-only circle stretches to an 18×40 pill.
    expect(trigger.style.minHeight).toBe("24px");
    expect(trigger.style.minHeight).toBe(trigger.style.width); // stays a circle
  });
});
