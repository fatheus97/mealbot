import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Tabs } from "./Tabs";
import { tabButtonId, tabPanelId, type TabDef } from "./tabIds";

const TABS: TabDef[] = [
  { id: "overview", label: "Overview" },
  { id: "revenue", label: "Revenue" },
  { id: "generation", label: "Generation" },
];

function renderTabs(active = "overview") {
  const onChange = vi.fn();
  render(
    <Tabs tabs={TABS} active={active} onChange={onChange} ariaLabel="Sections" idBase="admin" />,
  );
  return { onChange };
}

describe("Tabs", () => {
  it("renders one tab per def and marks the active one selected", () => {
    renderTabs("revenue");
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(3);
    expect(screen.getByRole("tab", { name: "Revenue" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false");
  });

  it("uses roving tabIndex (only the active tab is in the tab order)", () => {
    renderTabs("overview");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Revenue" })).toHaveAttribute("tabindex", "-1");
  });

  it("wires aria-controls to the matching panel id", () => {
    renderTabs();
    expect(screen.getByRole("tab", { name: "Revenue" })).toHaveAttribute(
      "aria-controls",
      tabPanelId("admin", "revenue"),
    );
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute(
      "id",
      tabButtonId("admin", "overview"),
    );
  });

  it("calls onChange with the clicked tab id", async () => {
    const user = userEvent.setup();
    const { onChange } = renderTabs("overview");
    await user.click(screen.getByRole("tab", { name: "Generation" }));
    expect(onChange).toHaveBeenCalledWith("generation");
  });

  it("moves selection with Arrow keys (wrapping) and Home/End", async () => {
    const user = userEvent.setup();
    const { onChange } = renderTabs("overview");
    const overview = screen.getByRole("tab", { name: "Overview" });
    const revenue = screen.getByRole("tab", { name: "Revenue" });
    const generation = screen.getByRole("tab", { name: "Generation" });

    // The handler moves focus to follow selection, so re-focus a known tab
    // before each keypress to make the wrapping cases deterministic.
    overview.focus();
    await user.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("revenue");

    overview.focus();
    await user.keyboard("{ArrowLeft}");
    expect(onChange).toHaveBeenLastCalledWith("generation"); // wraps past the start

    generation.focus();
    await user.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("overview"); // wraps past the end

    revenue.focus();
    await user.keyboard("{Home}");
    expect(onChange).toHaveBeenLastCalledWith("overview");

    revenue.focus();
    await user.keyboard("{End}");
    expect(onChange).toHaveBeenLastCalledWith("generation");
  });
});
