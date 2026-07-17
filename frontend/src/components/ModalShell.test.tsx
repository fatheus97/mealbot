import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ModalShell } from "./ModalShell";
import { setMobileViewport } from "../test/test-utils";

afterEach(() => {
  // A lockBodyScroll test could leave body.overflow set if an assertion threw
  // before unmount; reset so tests stay independent. (matchMedia is reset by
  // src/test/setup.ts.)
  document.body.style.overflow = "";
});

describe("ModalShell", () => {
  it("renders children inside a labelled dialog", () => {
    render(
      <ModalShell onClose={() => {}} ariaLabel="Test modal">
        <div>hello</div>
      </ModalShell>,
    );
    expect(screen.getByRole("dialog", { name: "Test modal" })).toBeInTheDocument();
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("closes on a backdrop click but not on a child click", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <ModalShell onClose={onClose} ariaLabel="Test modal">
        <button>inside</button>
      </ModalShell>,
    );

    // Click on the child → target !== backdrop → no close.
    await user.click(screen.getByText("inside"));
    expect(onClose).not.toHaveBeenCalled();

    // Click on the backdrop itself → close.
    await user.click(screen.getByRole("dialog", { name: "Test modal" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape by default, and not when closeOnEscape is false", async () => {
    const user = userEvent.setup();

    const onCloseDefault = vi.fn();
    const { unmount } = render(
      <ModalShell onClose={onCloseDefault} ariaLabel="A">
        <div>a</div>
      </ModalShell>,
    );
    await user.keyboard("{Escape}");
    expect(onCloseDefault).toHaveBeenCalledTimes(1);
    unmount();

    const onCloseOptOut = vi.fn();
    render(
      <ModalShell onClose={onCloseOptOut} ariaLabel="B" closeOnEscape={false}>
        <div>b</div>
      </ModalShell>,
    );
    await user.keyboard("{Escape}");
    expect(onCloseOptOut).not.toHaveBeenCalled();
  });

  it("locks body scroll while open and restores it on unmount (default)", () => {
    document.body.style.overflow = "auto";
    const { unmount } = render(
      <ModalShell onClose={() => {}} ariaLabel="Test">
        <div>x</div>
      </ModalShell>,
    );
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).toBe("auto");
  });

  it("leaves body scroll untouched when lockBodyScroll is false", () => {
    document.body.style.overflow = "auto";
    render(
      <ModalShell onClose={() => {}} ariaLabel="Test" lockBodyScroll={false}>
        <div>x</div>
      </ModalShell>,
    );
    expect(document.body.style.overflow).toBe("auto");
  });

  it("is a centered card on desktop and edge-to-edge on mobile", () => {
    // Desktop (no matchMedia mock → useIsMobile is false): dimmed backdrop with
    // a 1rem gutter around the centered child.
    const { unmount } = render(
      <ModalShell onClose={() => {}} ariaLabel="Desk">
        <div>x</div>
      </ModalShell>,
    );
    const desk = screen.getByRole("dialog", { name: "Desk" });
    expect(desk.style.position).toBe("fixed");
    expect(desk.style.padding).toBe("1rem");
    unmount();

    // Mobile → full-bleed: no gutter, pinned to the top-left corner. (The
    // 100dvh height that makes it truly edge-to-edge is verified in the browser,
    // since jsdom performs no layout.)
    setMobileViewport(true);
    render(
      <ModalShell onClose={() => {}} ariaLabel="Mob">
        <div>x</div>
      </ModalShell>,
    );
    const mob = screen.getByRole("dialog", { name: "Mob" });
    expect(mob.style.position).toBe("fixed");
    expect(mob.style.padding).toBe("0px");
    expect(mob.style.top).toBe("0px");
  });
});
