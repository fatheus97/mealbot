import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FridgeItemModal } from "./FridgeItemModal";

const defaultValues = { name: "", quantity_grams: 100, expiration_date: null, need_to_use: false };

describe("FridgeItemModal", () => {
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
        initialValues={{ name: "Eggs", quantity_grams: 200, expiration_date: "2026-04-01", need_to_use: true }}
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
});
