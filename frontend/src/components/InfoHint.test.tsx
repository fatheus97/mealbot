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

  describe("bubble placement (stays on screen)", () => {
    /** Pin the trigger's measured box: an 18px circle whose left edge sits at `left`. */
    function placeTrigger(trigger: HTMLElement, left: number) {
      vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
        left,
        right: left + 18,
        top: 300,
        bottom: 318,
        x: left,
        y: 300,
        width: 18,
        height: 18,
        toJSON: () => ({}),
      });
    }

    const openers = {
      hover: (user: ReturnType<typeof userEvent.setup>, el: HTMLElement) => user.hover(el),
      click: (user: ReturnType<typeof userEvent.setup>, el: HTMLElement) => user.click(el),
      focus: async (_user: ReturnType<typeof userEvent.setup>, el: HTMLElement) => {
        fireEvent.focus(el);
      },
    };

    it.each(Object.keys(openers) as Array<keyof typeof openers>)(
      "near the LEFT edge, opened by %s, grows rightward from the trigger",
      async (how) => {
        // Regression: the bubble was always right:0 / 240px wide, so a trigger at
        // x=8 put ~230px of it left of the viewport, cut off and unscrollable.
        const user = userEvent.setup();
        render(<InfoHint text="Left-edge explanation" />);
        const trigger = screen.getByRole("button", { name: "More information" });
        placeTrigger(trigger, 8);

        await openers[how](user, trigger);
        const tip = screen.getByRole("tooltip");
        expect(tip.style.left).toMatch(/^0(px)?$/);
        expect(tip.style.right).toBe("");
      },
    );

    it("far from the left edge keeps the default right anchor", async () => {
      const user = userEvent.setup();
      render(<InfoHint text="Right-side explanation" />);
      const trigger = screen.getByRole("button", { name: "More information" });
      placeTrigger(trigger, 900);

      await user.click(trigger);
      const tip = screen.getByRole("tooltip");
      expect(tip.style.right).toMatch(/^0(px)?$/);
      expect(tip.style.left).toBe("");
    });

    it("clamps maxWidth to the room left on the chosen side", async () => {
      // A left-anchored bubble on a narrow screen must not overflow the RIGHT edge
      // either: with the trigger at x=200 of 320px it may grow 320-200-8 = 112px.
      const user = userEvent.setup();
      const saved = window.innerWidth;
      window.innerWidth = 320;
      try {
        render(<InfoHint text="Narrow explanation" />);
        const trigger = screen.getByRole("button", { name: "More information" });
        placeTrigger(trigger, 200);
        await user.click(trigger);
        expect(screen.getByRole("tooltip").style.maxWidth).toBe("112px");
      } finally {
        window.innerWidth = saved;
      }
    });
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
