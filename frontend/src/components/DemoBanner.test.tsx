import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { DemoBanner } from "./DemoBanner";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";

vi.mock("../contexts/AuthContext", () => ({ useAuth: vi.fn() }));
import { useAuth } from "../contexts/AuthContext";
const mockedUseAuth = useAuth as unknown as ReturnType<typeof vi.fn>;

/**
 * The banner had no test at all, which is part of why it stayed English: it is
 * the first thing a visitor arriving from the Czech landing page sees, since
 * "Try Demo" is the only door that opens while registration is closed.
 */
describe("DemoBanner", () => {
  beforeEach(() => mockedUseAuth.mockReset());

  it("renders nothing for a normal account", () => {
    mockedUseAuth.mockReturnValue({ isDemo: false });
    const { container } = render(<DemoBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("warns a demo user that the session is temporary", () => {
    mockedUseAuth.mockReturnValue({ isDemo: true });
    render(<DemoBanner />);
    expect(screen.getByText(/auto-deleted in 2 hours/i)).toBeInTheDocument();
  });

  describe("in Czech", () => {
    beforeEach(() => useLocaleStore.setState({ locale: "cs", explicit: true }));
    afterEach(() =>
      useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false }),
    );

    it("renders no English", () => {
      mockedUseAuth.mockReturnValue({ isDemo: true });
      const { container } = render(<DemoBanner />);
      expect(untranslatedEnglishIn(container)).toEqual([]);
    });
  });
});
