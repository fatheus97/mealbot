import { describe, it, expect, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import { AppFooter } from "./AppFooter";

// In act(): Vitest runs afterEach LIFO, so this fires BEFORE RTL's cleanup —
// i.e. while the footer is still mounted and subscribed to the store.
afterEach(() =>
  act(() => useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false })),
);

describe("AppFooter", () => {
  it("links to both legal documents", () => {
    render(<AppFooter />);
    expect(screen.getByRole("link", { name: /privacy policy/i })).toHaveAttribute(
      "href",
      "/privacy",
    );
    expect(screen.getByRole("link", { name: /terms of service/i })).toHaveAttribute(
      "href",
      "/terms",
    );
  });

  it("opens them in a new tab without leaking the referrer window", () => {
    render(<AppFooter />);
    for (const link of screen.getAllByRole("link")) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
  });

  it("points a Czech UI at the CZECH editions", () => {
    // The two editions are equally authoritative (#396) and the Czech one is
    // what binds a Czech consumer — a footer link is the one route into the
    // document from inside the app, so it must not land on the English text.
    useLocaleStore.setState({ locale: "cs", explicit: true });
    render(<AppFooter />);
    expect(
      screen.getAllByRole("link").map((a) => a.getAttribute("href")),
    ).toEqual(["/cs/privacy", "/cs/terms"]);
  });

  it("renders no untranslated English in Czech", () => {
    useLocaleStore.setState({ locale: "cs", explicit: true });
    render(<AppFooter />);
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });
});
