import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FridgeItemModal } from "./FridgeItemModal";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import { untranslatedEnglishIn } from "../test/i18nAssertions";

const defaultValues = { name: "", quantity_grams: 100, expiration_date: null, need_to_use: false, date_kind: null };

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

  it("asks only once there is a date, and saves the kind picked from the pack", async () => {
    const onOk = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <FridgeItemModal mode="add" initialValues={defaultValues} onOk={onOk} onCancel={vi.fn()} />,
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
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
