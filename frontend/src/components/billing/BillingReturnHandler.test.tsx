import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { BillingReturnHandler } from "./BillingReturnHandler";

const { refreshProfile } = vi.hoisted(() => ({ refreshProfile: vi.fn().mockResolvedValue(undefined) }));

vi.mock("../../contexts/AuthContext", () => ({ useAuth: vi.fn() }));
import { useAuth } from "../../contexts/AuthContext";
const mockedUseAuth = useAuth as unknown as ReturnType<typeof vi.fn>;

describe("BillingReturnHandler", () => {
  beforeEach(() => {
    refreshProfile.mockClear();
    mockedUseAuth.mockReturnValue({ userId: 1, refreshProfile });
  });

  it("strips ?billing=success and refreshes the profile", async () => {
    window.history.replaceState({}, "", "/?billing=success&keep=1");
    render(<BillingReturnHandler />);
    await waitFor(() => expect(refreshProfile).toHaveBeenCalled());
    // The marker is removed, unrelated params preserved.
    expect(window.location.search).toBe("?keep=1");
  });

  it("strips ?billing=managed (portal return) and refreshes the profile", async () => {
    window.history.replaceState({}, "", "/?billing=managed");
    render(<BillingReturnHandler />);
    await waitFor(() => expect(refreshProfile).toHaveBeenCalled());
    expect(window.location.search).toBe("");
  });

  it("strips ?billing=cancel without refreshing", async () => {
    window.history.replaceState({}, "", "/?billing=cancel");
    render(<BillingReturnHandler />);
    await waitFor(() => expect(window.location.search).toBe(""));
    expect(refreshProfile).not.toHaveBeenCalled();
  });

  it("does nothing without the billing marker", () => {
    window.history.replaceState({}, "", "/");
    render(<BillingReturnHandler />);
    expect(refreshProfile).not.toHaveBeenCalled();
  });
});
