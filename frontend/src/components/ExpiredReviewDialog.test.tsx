import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExpiredReviewDialog } from "./ExpiredReviewDialog";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import { todayISO, addDaysISO } from "../utils/planDates";
import type { StockItem } from "../types";

function item(over: Partial<StockItem> = {}): StockItem {
  return {
    id: 1,
    name: "Yogurt",
    quantity_grams: 500,
    need_to_use: false,
    expiration_date: addDaysISO(todayISO(), -3),
    ...over,
  };
}

describe("ExpiredReviewDialog", () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it("lists every expired item and starts every row unanswered", () => {
    render(
      <ExpiredReviewDialog
        items={[item({ id: 1, name: "Yogurt" }), item({ id: 2, name: "Spinach" })]}
        onApply={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

    expect(screen.getByText("Yogurt")).toBeInTheDocument();
    expect(screen.getByText("Spinach")).toBeInTheDocument();
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).not.toBeChecked();
    }
  });

  it("applies only the rows that were answered", () => {
    const onApply = vi.fn();
    render(
      <ExpiredReviewDialog
        items={[
          item({ id: 1, name: "Yogurt" }),
          item({ id: 2, name: "Spinach" }),
          item({ id: 3, name: "Cheese" }),
        ]}
        onApply={onApply}
        onSkip={vi.fn()}
      />,
    );

    const rows = screen.getAllByRole("group");
    within(rows[0]).getByRole("radio", { name: /still fine/i }).click();
    within(rows[1]).getByRole("radio", { name: /threw it out/i }).click();
    // Row 2 (Cheese) deliberately left alone.
    screen.getByRole("button", { name: /^save$/i }).click();

    expect(onApply).toHaveBeenCalledTimes(1);
    const decisions = onApply.mock.calls[0][0];
    expect(decisions).toHaveLength(2);
    expect(decisions.map((d: { item: StockItem; choice: string }) => [d.item.name, d.choice])).toEqual([
      ["Yogurt", "still_fine"],
      ["Spinach", "thrown_out"],
    ]);
  });

  it("keeps each row's choice independent", async () => {
    // Regression: one shared radio `name` across rows would make the whole
    // list a single choice, so answering row 2 would silently unanswer row 1.
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(
      <ExpiredReviewDialog
        items={[item({ id: 1, name: "Yogurt" }), item({ id: 2, name: "Spinach" })]}
        onApply={onApply}
        onSkip={vi.fn()}
      />,
    );

    const rows = screen.getAllByRole("group");
    await user.click(within(rows[0]).getByRole("radio", { name: /still fine/i }));
    await user.click(within(rows[1]).getByRole("radio", { name: /still fine/i }));

    expect(within(rows[0]).getByRole("radio", { name: /still fine/i })).toBeChecked();
    expect(within(rows[1]).getByRole("radio", { name: /still fine/i })).toBeChecked();

    await user.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onApply.mock.calls[0][0]).toHaveLength(2);
  });

  it("applies an empty list when nothing was answered", async () => {
    // Confirming without answering is a normal outcome, not a blocked one.
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(
      <ExpiredReviewDialog items={[item()]} onApply={onApply} onSkip={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onApply).toHaveBeenCalledWith([]);
  });

  it("skips without applying anything, even after a choice was made", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    const onSkip = vi.fn();
    render(
      <ExpiredReviewDialog items={[item()]} onApply={onApply} onSkip={onSkip} />,
    );

    await user.click(screen.getByRole("radio", { name: /threw it out/i }));
    await user.click(screen.getByRole("button", { name: /^skip$/i }));

    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(onApply).not.toHaveBeenCalled();
  });

  it("tells the user what \"still fine\" will do to the date", () => {
    // Moving the stored date is a real edit to their fridge; doing it silently
    // would read as a bug.
    render(<ExpiredReviewDialog items={[item()]} onApply={vi.fn()} onSkip={vi.fn()} />);
    expect(screen.getByText(/moves its date on a week/i)).toBeInTheDocument();
  });

  it("never claims the food is safe", () => {
    // Liability: the app does not judge edibility and must not imply it has.
    // The user is telling us, not the other way round.
    const { container } = render(
      <ExpiredReviewDialog items={[item()]} onApply={vi.fn()} onSkip={vi.fn()} />,
    );
    expect(container.textContent).not.toMatch(/\bsafe\b|\bguarantee|safe to eat/i);
  });

  it("leaves no untranslated English when switched to Czech", () => {
    useLocaleStore.setState({ locale: "cs", explicit: true });
    render(
      <ExpiredReviewDialog
        items={[item({ name: "Jogurt" })]}
        onApply={vi.fn()}
        onSkip={vi.fn()}
      />,
    );
    expect(untranslatedEnglishIn(screen.getByRole("dialog"))).toEqual([]);
  });
});
