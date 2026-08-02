import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TermsConsent } from "./TermsConsent";

describe("TermsConsent", () => {
  it("is unticked unless told otherwise", () => {
    // A pre-ticked box is not consent. This is the one prop default that
    // carries legal weight, so it is pinned rather than assumed.
    render(<TermsConsent checked={false} onChange={vi.fn()} />);
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("reports the user's choice both ways", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<TermsConsent checked={false} onChange={onChange} />);
    await user.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenLastCalledWith(true);

    rerender(<TermsConsent checked={true} onChange={onChange} />);
    await user.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenLastCalledWith(false);
  });

  it("links both documents", () => {
    render(<TermsConsent checked={false} onChange={vi.fn()} />);
    expect(screen.getByRole("link", { name: /terms of service/i })).toHaveAttribute(
      "href",
      "/terms",
    );
    expect(screen.getByRole("link", { name: /privacy policy/i })).toHaveAttribute(
      "href",
      "/privacy",
    );
  });

  it("opens them in a new tab, safely", () => {
    // Reading the terms must not cost a half-filled signup form — that is the
    // reason nobody reads them. rel=noopener because target=_blank without it
    // hands the opened page a window.opener handle back to this one.
    render(<TermsConsent checked={false} onChange={vi.fn()} />);
    for (const name of [/terms of service/i, /privacy policy/i]) {
      const link = screen.getByRole("link", { name });
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel")).toMatch(/noopener/);
    }
  });

  it("labels the checkbox, so clicking the text toggles it", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TermsConsent checked={false} onChange={onChange} />);
    await user.click(screen.getByText(/i accept the/i));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
