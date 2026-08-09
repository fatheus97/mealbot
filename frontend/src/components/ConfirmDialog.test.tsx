import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders title, message, and default labels", () => {
    render(
      <ConfirmDialog
        title="Delete recipe?"
        message="This will remove Pasta from your cookbook."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText("Delete recipe?")).toBeInTheDocument();
    expect(screen.getByText("This will remove Pasta from your cookbook.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("calls onConfirm when the confirm button is clicked", async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        title="Delete?"
        message="Sure?"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when the cancel button is clicked", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        title="Delete?"
        message="Sure?"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel on Escape", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        title="Delete?"
        message="Sure?"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );

    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel on backdrop click", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        title="Delete?"
        message="Sure?"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );

    await user.pointer({ keys: "[MouseLeft>]", target: screen.getByRole("dialog") });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables both buttons and swaps confirm label while loading", () => {
    render(
      <ConfirmDialog
        title="Delete?"
        message="Sure?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        loading
        loadingLabel="Removing…"
      />,
    );

    expect(screen.getByRole("button", { name: "Removing…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });

  it("ignores Escape while loading", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        title="Delete?"
        message="Sure?"
        onConfirm={vi.fn()}
        onCancel={onCancel}
        loading
      />,
    );

    await user.keyboard("{Escape}");
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("renders the error message when provided", () => {
    render(
      <ConfirmDialog
        title="Delete?"
        message="Sure?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        error="Server unreachable"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Server unreachable");
  });

  it("cycles focus between Cancel and Confirm on Tab / Shift+Tab", async () => {
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        title="Delete?"
        message="Sure?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    // Cancel is focused on mount.
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();

    // Tab → Confirm.
    await user.tab();
    expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus();

    // Tab again → wraps back to Cancel (trap).
    await user.tab();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();

    // Shift+Tab → wraps to Confirm.
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus();
  });

  it("renders children between the message and the buttons", () => {
    render(
      <ConfirmDialog
        title="Remove?"
        message="Sure?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      >
        <p>Where did it go?</p>
      </ConfirmDialog>,
    );

    expect(screen.getByText("Where did it go?")).toBeInTheDocument();
  });

  it("keeps the focus trap closed when children add focusable controls", async () => {
    // Regression: the trap used to cycle the Cancel/Confirm refs and was
    // documented as exhaustive because the dialog only ever had two tabbable
    // controls. Once `children` could contribute focusable elements, Shift+Tab
    // off the FIRST one matched none of its cases and fell through to the
    // browser default — leaving the dialog entirely, silently.
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        title="Remove?"
        message="Sure?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      >
        <input aria-label="Note" />
      </ConfirmDialog>,
    );

    const note = screen.getByLabelText("Note");
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Delete" });

    expect(cancel).toHaveFocus();

    // Backwards past the first control must wrap to the last, not escape.
    await user.tab({ shift: true });
    expect(note).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();

    // Forwards off the last control still wraps to the first — which is now
    // the child, not Cancel.
    await user.tab();
    expect(note).toHaveFocus();
  });

  it("skips disabled controls when wrapping", async () => {
    // `loading` disables both buttons; without the filter the trap would try to
    // focus one and the wrap would land nowhere.
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        title="Remove?"
        message="Sure?"
        loading
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      >
        <input aria-label="Note" />
      </ConfirmDialog>,
    );

    const note = screen.getByLabelText("Note");
    note.focus();
    expect(note).toHaveFocus();

    // The note is the only enabled control, so it is both first and last.
    await user.tab();
    expect(note).toHaveFocus();
    await user.tab({ shift: true });
    expect(note).toHaveFocus();
  });

  it("stops Escape from propagating to ancestor window listeners", async () => {
    // Regression: when ConfirmDialog is mounted inside another window-level
    // Escape handler (e.g. CookbookModal), the ancestor used to also fire
    // and close itself.
    const ancestorEsc = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") ancestorEsc();
    });
    render(
      <ConfirmDialog
        title="Delete?"
        message="Sure?"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );

    await user.keyboard("{Escape}");

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(ancestorEsc).not.toHaveBeenCalled();
  });

  it("respects custom confirm and cancel labels", () => {
    render(
      <ConfirmDialog
        title="Sign out?"
        message="You'll be returned to the login page."
        confirmLabel="Sign out"
        cancelLabel="Stay"
        destructive={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stay" })).toBeInTheDocument();
  });
});
