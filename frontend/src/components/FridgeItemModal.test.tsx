import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FridgeItemModal } from "./FridgeItemModal";
import { lookupKeepTime } from "../api";
import { addDaysISO, todayISO } from "../utils/planDates";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import { untranslatedEnglishIn } from "../test/i18nAssertions";

vi.mock("../api", () => ({ lookupKeepTime: vi.fn() }));
const mockedLookup = vi.mocked(lookupKeepTime);

const defaultValues = { name: "", quantity_grams: 100, expiration_date: null, need_to_use: false, date_kind: null };

// Every test starts with a table that knows nothing.
beforeEach(() => {
  mockedLookup.mockReset();
  mockedLookup.mockResolvedValue(null);
});

describe("FridgeItemModal", () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it("leaves no untranslated English when switched to Czech, in both modes", () => {
    // BOTH modes: the title is a ternary, so one render only ever proves one
    // branch — the shape that shipped English twice in earlier slices.
    useLocaleStore.setState({ locale: "cs", explicit: true });
    for (const mode of ["add", "edit"] as const) {
      const { container, unmount } = render(
        <FridgeItemModal mode={mode} initialValues={defaultValues} onOk={vi.fn()} onCancel={vi.fn()} />,
      );
      expect(untranslatedEnglishIn(container)).toEqual([]);
      unmount();
    }
  });

  it('renders "Add Ingredient" title in add mode', () => {
    render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByText("Add Ingredient")).toBeInTheDocument();
  });

  it('renders "Edit Ingredient" title in edit mode', () => {
    render(
      <FridgeItemModal mode="edit" initialValues={defaultValues} onOk={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByText("Edit Ingredient")).toBeInTheDocument();
  });

  it("pre-fills values in edit mode", () => {
    render(
      <FridgeItemModal
        mode="edit"
        initialValues={{ name: "Eggs", quantity_grams: 200, expiration_date: "2026-04-01", need_to_use: true, date_kind: null }}
        onOk={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByDisplayValue("Eggs")).toBeInTheDocument();
    expect(screen.getByDisplayValue("200")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2026-04-01")).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeChecked();
  });

  it("calls onOk with form values", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={onOk} onCancel={vi.fn()} />,
    );

    await user.type(screen.getByPlaceholderText(/chicken breast/i), "Milk");
    await user.click(screen.getByRole("button", { name: /ok/i }));

    expect(onOk).toHaveBeenCalledWith({
      name: "Milk",
      quantity_grams: 100,
      expiration_date: null,
      need_to_use: false,
      date_kind: null,
    });
  });

  it("calls onCancel on Cancel click", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={vi.fn()} onCancel={onCancel} />,
    );

    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("shows validation error when name is empty", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={onOk} onCancel={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: /ok/i }));

    expect(screen.getByText("Name is required")).toBeInTheDocument();
    expect(onOk).not.toHaveBeenCalled();
  });

  it("backspacing the quantity field leaves it empty (no auto-zero)", async () => {
    const user = userEvent.setup();
    render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={vi.fn()} onCancel={vi.fn()} />,
    );

    const qty = screen.getByDisplayValue("100") as HTMLInputElement;
    await user.click(qty);
    await user.keyboard("{Backspace}{Backspace}{Backspace}");

    expect(qty.value).toBe("");
  });

  it("blocks submit and shows error when quantity is empty", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={onOk} onCancel={vi.fn()} />,
    );

    await user.type(screen.getByPlaceholderText(/chicken breast/i), "Milk");
    await user.clear(screen.getByDisplayValue("100"));
    await user.click(screen.getByRole("button", { name: /ok/i }));

    expect(screen.getByText(/quantity greater than 0/i)).toBeInTheDocument();
    expect(onOk).not.toHaveBeenCalled();
  });

  it("blocks submit and shows error when quantity is zero", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={onOk} onCancel={vi.fn()} />,
    );

    const qty = screen.getByDisplayValue("100") as HTMLInputElement;
    await user.type(screen.getByPlaceholderText(/chicken breast/i), "Milk");
    await user.clear(qty);
    await user.type(qty, "0");
    await user.click(screen.getByRole("button", { name: /ok/i }));

    expect(screen.getByText(/quantity greater than 0/i)).toBeInTheDocument();
    expect(onOk).not.toHaveBeenCalled();
  });

  it("accepts decimal quantities and forwards them as numbers", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={onOk} onCancel={vi.fn()} />,
    );

    const qty = screen.getByDisplayValue("100") as HTMLInputElement;
    await user.type(screen.getByPlaceholderText(/chicken breast/i), "Yeast");
    await user.clear(qty);
    await user.type(qty, "12.5");
    await user.click(screen.getByRole("button", { name: /ok/i }));

    expect(onOk).toHaveBeenCalledWith({
      name: "Yeast",
      quantity_grams: 12.5,
      expiration_date: null,
      need_to_use: false,
      date_kind: null,
    });
  });

  it("hides the need-to-use checkbox when needToUseEnabled is false", () => {
    render(
      <FridgeItemModal
        mode="edit"
        initialValues={{ name: "Eggs", quantity_grams: 200, expiration_date: null, need_to_use: true, date_kind: null }}
        onOk={vi.fn()}
        onCancel={vi.fn()}
        needToUseEnabled={false}
      />,
    );
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("submits the stored need_to_use unchanged when the checkbox is hidden", async () => {
    // The field is invisible, not cleared — a disabled preference masks the
    // signal server-side; it never mutates what's actually stored, so
    // re-enabling the preference restores it.
    const onOk = vi.fn();
    const user = userEvent.setup();
    render(
      <FridgeItemModal
        mode="edit"
        initialValues={{ name: "Eggs", quantity_grams: 200, expiration_date: null, need_to_use: true, date_kind: null }}
        onOk={onOk}
        onCancel={vi.fn()}
        needToUseEnabled={false}
      />,
    );

    await user.click(screen.getByRole("button", { name: /ok/i }));

    expect(onOk).toHaveBeenCalledWith({
      name: "Eggs",
      quantity_grams: 200,
      expiration_date: null,
      need_to_use: true,
      date_kind: null,
    });
  });

  it("rejects non-numeric input at the keystroke level", async () => {
    const user = userEvent.setup();
    render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={vi.fn()} onCancel={vi.fn()} />,
    );

    const qty = screen.getByDisplayValue("100") as HTMLInputElement;
    await user.click(qty);
    await user.keyboard("abc");

    expect(qty.value).toBe("100");
  });
});

describe("FridgeItemModal date kind", () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  const dateInput = (container: HTMLElement) =>
    container.querySelector('input[type="date"]') as HTMLInputElement;
  const picker = () => screen.getByRole("combobox", { name: "Date from the pack?" });
  const estimated = {
    name: "Carrot", quantity_grams: 300, expiration_date: "2026-12-01",
    need_to_use: false, date_kind: "estimated_ai" as const,
  };

  it("asks on an edit only once there is a date", () => {
    render(<FridgeItemModal mode="edit" initialValues={{ ...defaultValues, name: "Rice" }} onOk={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("asks on an add right away, and saves the kind picked from the pack", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={onOk} onCancel={vi.fn()} />,
    );
    // The answer decides whether the table may suggest a date, so it comes first.
    expect(picker()).toHaveValue("");
    await user.type(screen.getByPlaceholderText(/chicken breast/i), "Pasta");
    fireEvent.change(dateInput(container), { target: { value: "2027-03-01" } });
    expect(picker()).toHaveValue("");
    await user.selectOptions(picker(), "best_before");
    await user.click(screen.getByRole("button", { name: /ok/i }));
    expect(onOk).toHaveBeenCalledWith(
      expect.objectContaining({ expiration_date: "2027-03-01", date_kind: "best_before" }),
    );
  });

  it("keeps an estimate while its date is untouched", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    render(<FridgeItemModal mode="edit" initialValues={estimated} onOk={onOk} onCancel={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /ok/i }));
    expect(onOk).toHaveBeenCalledWith(expect.objectContaining({ date_kind: "estimated_ai" }));
  });

  it("makes a retyped date unknown unless the pack names its kind", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <FridgeItemModal mode="edit" initialValues={estimated} onOk={onOk} onCancel={vi.fn()} />,
    );
    fireEvent.change(dateInput(container), { target: { value: "2026-12-05" } });
    await user.click(screen.getByRole("button", { name: /ok/i }));
    expect(onOk).toHaveBeenCalledWith(
      expect.objectContaining({ expiration_date: "2026-12-05", date_kind: null }),
    );
  });

  it("shows a pack kind and drops it when the user says No", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    render(
      <FridgeItemModal
        mode="edit"
        initialValues={{ ...estimated, date_kind: "use_by" }}
        onOk={onOk}
        onCancel={vi.fn()}
      />,
    );
    expect(picker()).toHaveValue("use_by");
    await user.selectOptions(picker(), "");
    await user.click(screen.getByRole("button", { name: /ok/i }));
    expect(onOk).toHaveBeenCalledWith(expect.objectContaining({ date_kind: null }));
  });

  it("saves no kind without a date", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <FridgeItemModal
        mode="edit"
        initialValues={{ ...estimated, date_kind: "best_before" }}
        onOk={onOk}
        onCancel={vi.fn()}
      />,
    );
    fireEvent.change(dateInput(container), { target: { value: "" } });
    await user.click(screen.getByRole("button", { name: /ok/i }));
    expect(onOk).toHaveBeenCalledWith(
      expect.objectContaining({ expiration_date: null, date_kind: null }),
    );
  });

  it("leaves no untranslated English in the picker in Czech", () => {
    useLocaleStore.setState({ locale: "cs", explicit: true });
    const { container } = render(
      <FridgeItemModal mode="edit" initialValues={estimated} onOk={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(container.querySelector("select")).not.toBeNull();
    expect(untranslatedEnglishIn(container)).toEqual([]);
  });
});

describe("FridgeItemModal table suggestion", () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  const chicken = { low: 4, high: 9, unit: "Days" as const, low_days: 4 };
  const dateInput = (container: HTMLElement) =>
    container.querySelector('input[type="date"]') as HTMLInputElement;
  const picker = () => screen.getByRole("combobox", { name: "Date from the pack?" });
  const ok = () => screen.getByRole("button", { name: /ok/i });

  /** An add with `name` typed and the table's answer shown. */
  async function addWithSuggestion(name = "Chicken breast") {
    mockedLookup.mockResolvedValue(chicken);
    const onOk = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={onOk} onCancel={vi.fn()} />,
    );
    await user.type(screen.getByPlaceholderText(/chicken breast/i), name);
    await waitFor(() => expect(dateInput(container)).toHaveValue(addDaysISO(todayISO(), 4)));
    return { onOk, user, container };
  }

  it("suggests today plus the short end, names its source and saves it as a table estimate", async () => {
    const { onOk, user } = await addWithSuggestion();
    // Looked up once, after the typing stopped, with the whole name.
    expect(mockedLookup).toHaveBeenCalledTimes(1);
    expect(mockedLookup).toHaveBeenCalledWith("Chicken breast", expect.any(AbortSignal));
    expect(screen.getByText("Usually keeps 4 to 9 days in a fridge, based on USDA FoodKeeper (US).")).toBeInTheDocument();
    await user.click(ok());
    expect(onOk).toHaveBeenCalledWith(
      expect.objectContaining({ expiration_date: addDaysISO(todayISO(), 4), date_kind: "estimated_table" }),
    );
  });

  it.each(["use_by", "best_before"])("drops the suggestion when the pack says %s (design check 2)", async (kind) => {
    const { onOk, user, container } = await addWithSuggestion();
    await user.selectOptions(picker(), kind);
    expect(dateInput(container)).toHaveValue("");
    expect(screen.queryByText(/USDA FoodKeeper/)).not.toBeInTheDocument();
    await user.click(ok());
    // A table date never stands under a pack kind: no date, so no kind.
    expect(onOk).toHaveBeenCalledWith(expect.objectContaining({ expiration_date: null, date_kind: null }));
  });

  it("takes the pack's date once the user types it under a pack kind", async () => {
    const { onOk, user, container } = await addWithSuggestion();
    await user.selectOptions(picker(), "use_by");
    fireEvent.change(dateInput(container), { target: { value: "2027-01-02" } });
    await user.click(ok());
    expect(onOk).toHaveBeenCalledWith(expect.objectContaining({ expiration_date: "2027-01-02", date_kind: "use_by" }));
  });

  it("ends the suggestion for good once the user touches the date", async () => {
    const { onOk, user, container } = await addWithSuggestion();
    fireEvent.change(dateInput(container), { target: { value: "" } });
    // Cleared on purpose: no new suggestion, even after a lookup would have answered.
    await user.type(screen.getByPlaceholderText(/chicken breast/i), "s");
    await new Promise((r) => setTimeout(r, 600));
    expect(dateInput(container)).toHaveValue("");
    await user.click(ok());
    expect(onOk).toHaveBeenCalledWith(expect.objectContaining({ expiration_date: null, date_kind: null }));
  });

  it("makes a date typed over the suggestion unknown", async () => {
    const { onOk, user, container } = await addWithSuggestion();
    fireEvent.change(dateInput(container), { target: { value: "2027-01-02" } });
    expect(screen.queryByText(/USDA FoodKeeper/)).not.toBeInTheDocument();
    await user.click(ok());
    expect(onOk).toHaveBeenCalledWith(expect.objectContaining({ expiration_date: "2027-01-02", date_kind: null }));
  });

  it("never saves an answer for an earlier name", async () => {
    const { onOk, user, container } = await addWithSuggestion("Chicken");
    // Typing on: the shown answer was for "Chicken", so it goes at once.
    await user.type(screen.getByPlaceholderText(/chicken breast/i), " nuggets");
    expect(dateInput(container)).toHaveValue("");
    mockedLookup.mockResolvedValue(null);
    await user.click(ok());
    expect(onOk).toHaveBeenCalledWith(expect.objectContaining({ name: "Chicken nuggets", expiration_date: null, date_kind: null }));
  });

  it("suggests nothing for a name the table lacks, or when the lookup fails", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={vi.fn()} onCancel={vi.fn()} />,
    );
    await user.type(screen.getByPlaceholderText(/chicken breast/i), "Mystery");
    await waitFor(() => expect(mockedLookup).toHaveBeenCalled());
    mockedLookup.mockRejectedValue(new Error("down"));
    await user.type(screen.getByPlaceholderText(/chicken breast/i), " box");
    await waitFor(() => expect(mockedLookup).toHaveBeenCalledTimes(2));
    expect(dateInput(container)).toHaveValue("");
  });

  it("never looks up on an edit", async () => {
    render(
      <FridgeItemModal mode="edit" initialValues={{ ...defaultValues, name: "Chicken breast" }} onOk={vi.fn()} onCancel={vi.fn()} />,
    );
    await new Promise((r) => setTimeout(r, 600));
    expect(mockedLookup).not.toHaveBeenCalled();
  });

  it.each([
    ["en", { low: 2, high: 2, unit: "Weeks" as const, low_days: 14 }, "Usually keeps 2 weeks in a fridge, based on USDA FoodKeeper (US)."],
    ["en", { low: 2, high: 3, unit: "Weeks" as const, low_days: 14 }, "Usually keeps 2 to 3 weeks in a fridge, based on USDA FoodKeeper (US)."],
    ["cs", { low: 1, high: 2, unit: "Days" as const, low_days: 1 }, "V lednici obvykle vydrží 1 až 2 dny, podle USDA FoodKeeper (USA)."],
    ["cs", { low: 7, high: 10, unit: "Days" as const, low_days: 7 }, "V lednici obvykle vydrží 7 až 10 dní, podle USDA FoodKeeper (USA)."],
    ["cs", { low: 1, high: 1, unit: "Weeks" as const, low_days: 7 }, "V lednici obvykle vydrží 1 týden, podle USDA FoodKeeper (USA)."],
    ["cs", { low: 4, high: 6, unit: "Weeks" as const, low_days: 28 }, "V lednici obvykle vydrží 4 až 6 týdnů, podle USDA FoodKeeper (USA)."],
  ])("words the source line in %s for %o", async (locale, keeps, line) => {
    useLocaleStore.setState({ locale: locale as "en" | "cs", explicit: true });
    mockedLookup.mockResolvedValue(keeps);
    const user = userEvent.setup();
    const { container } = render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={vi.fn()} onCancel={vi.fn()} />,
    );
    await user.type(screen.getByRole("textbox", { name: locale === "cs" ? /název/i : /name/i }), "x");
    await waitFor(() => expect(screen.getByText(line)).toBeInTheDocument());
    expect(dateInput(container)).toHaveValue(addDaysISO(todayISO(), keeps.low_days));
    if (locale === "cs") expect(untranslatedEnglishIn(container)).toEqual([]);
  });
});
