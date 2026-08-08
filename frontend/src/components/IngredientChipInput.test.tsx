import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { IngredientChipInput } from "./IngredientChipInput";

function Harness({
  initial = [],
  suggestions,
  maxItems,
}: { initial?: string[]; suggestions: string[]; maxItems?: number }) {
  const [values, setValues] = useState<string[]>(initial);
  return (
    <>
      <IngredientChipInput
        values={values}
        onChange={setValues}
        suggestions={suggestions}
        placeholder="type here"
        maxItems={maxItems}
      />
      <div data-testid="state">{values.join("|")}</div>
    </>
  );
}

describe("IngredientChipInput", () => {
  it("commits a chip when Enter is pressed on a free-form entry (not in fridge)", async () => {
    const user = userEvent.setup();
    render(<Harness suggestions={["chicken", "rice"]} />);

    const input = screen.getByPlaceholderText("type here");
    await user.type(input, "mystery-herb");
    await user.keyboard("{Enter}");

    expect(screen.getByTestId("state").textContent).toBe("mystery-herb");
  });

  it("commits a chip when comma is pressed", async () => {
    const user = userEvent.setup();
    render(<Harness suggestions={[]} />);

    await user.type(screen.getByPlaceholderText("type here"), "basil,");
    expect(screen.getByTestId("state").textContent).toBe("basil");
  });

  it("splits a pasted comma-list into separate chips (no chip keeps a comma)", async () => {
    // A paste lands as one onChange with commas intact (unlike typing, where the comma
    // key commits per value). Committing must split it, so a chip can never contain a
    // comma — otherwise a downstream comma-join/split round-trip (MealPlanner's persisted
    // "avoid" string) would re-split the chip and silently multiply the list.
    const user = userEvent.setup();
    render(<Harness suggestions={[]} />);

    const input = screen.getByPlaceholderText("type here");
    await user.click(input);
    await user.paste("peanut, butter, jam");
    await user.keyboard("{Enter}");

    expect(screen.getByTestId("state").textContent).toBe("peanut|butter|jam");
  });

  it("shows fridge autocomplete suggestions as user types", async () => {
    const user = userEvent.setup();
    render(<Harness suggestions={["chicken breast", "chickpeas", "rice"]} />);

    await user.type(screen.getByPlaceholderText("type here"), "chick");

    expect(screen.getByRole("option", { name: "chicken breast" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "chickpeas" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "rice" })).not.toBeInTheDocument();
  });

  it("commits the top suggestion when Enter is pressed while suggestions are visible", async () => {
    const user = userEvent.setup();
    render(<Harness suggestions={["chicken breast", "chickpeas"]} />);

    await user.type(screen.getByPlaceholderText("type here"), "chick");
    await user.keyboard("{Enter}");

    expect(screen.getByTestId("state").textContent).toBe("chicken breast");
  });

  it("commits the top suggestion when Tab is pressed while suggestions are visible", async () => {
    const user = userEvent.setup();
    render(<Harness suggestions={["chicken breast", "chickpeas"]} />);

    await user.type(screen.getByPlaceholderText("type here"), "chick");
    await user.keyboard("{Tab}");

    expect(screen.getByTestId("state").textContent).toBe("chicken breast");
  });

  it("commits a suggestion when clicked", async () => {
    const user = userEvent.setup();
    render(<Harness suggestions={["chicken breast", "rice"]} />);

    await user.type(screen.getByPlaceholderText("type here"), "chic");
    const option = screen.getByRole("option", { name: "chicken breast" });
    fireEvent.mouseDown(option);

    expect(screen.getByTestId("state").textContent).toBe("chicken breast");
  });

  it("removes the last chip on Backspace when input is empty", async () => {
    const user = userEvent.setup();
    render(<Harness initial={["rice", "tofu"]} suggestions={[]} />);

    const input = screen.getByPlaceholderText("");
    input.focus();
    await user.keyboard("{Backspace}");

    expect(screen.getByTestId("state").textContent).toBe("rice");
  });

  it("removes a chip via the ✕ button", async () => {
    const user = userEvent.setup();
    render(<Harness initial={["rice", "tofu"]} suggestions={[]} />);

    await user.click(screen.getByLabelText("Remove rice"));
    expect(screen.getByTestId("state").textContent).toBe("tofu");
  });

  it("ignores duplicate chips (case-insensitive)", async () => {
    const user = userEvent.setup();
    render(<Harness initial={["Rice"]} suggestions={[]} />);

    const input = screen.getByPlaceholderText("");
    await user.type(input, "rice");
    await user.keyboard("{Enter}");

    expect(screen.getByTestId("state").textContent).toBe("Rice");
  });

  it("ignores empty chip submissions", async () => {
    const user = userEvent.setup();
    render(<Harness suggestions={[]} />);

    const input = screen.getByPlaceholderText("type here");
    input.focus();
    await user.keyboard("{Enter}");
    await user.type(input, "   ");
    await user.keyboard("{Enter}");

    expect(screen.getByTestId("state").textContent).toBe("");
  });

  it("filters out suggestions that are already chipped", async () => {
    const user = userEvent.setup();
    render(<Harness initial={["chicken breast"]} suggestions={["chicken breast", "chickpeas"]} />);

    const input = screen.getByPlaceholderText("");
    await user.type(input, "chick");

    expect(screen.queryByRole("option", { name: "chicken breast" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "chickpeas" })).toBeInTheDocument();
  });

  // The server truncates past its own max_length with no error and no log, so
  // anything the UI lets through above the cap is discarded silently.
  describe("maxItems cap", () => {
    it("shows the count so the ceiling is visible before it is hit", () => {
      render(<Harness initial={["a", "b"]} suggestions={[]} maxItems={5} />);
      expect(screen.getByText("2 of 5")).toBeInTheDocument();
    });

    it("renders no counter at all when uncapped", () => {
      render(<Harness initial={["a"]} suggestions={[]} />);
      expect(screen.queryByText(/of/)).not.toBeInTheDocument();
    });

    it("refuses a commit once full, and says why", async () => {
      const user = userEvent.setup();
      render(<Harness initial={["a", "b"]} suggestions={[]} maxItems={2} />);

      await user.type(screen.getByPlaceholderText(""), "c");
      await user.keyboard("{Enter}");

      expect(screen.getByTestId("state").textContent).toBe("a|b");
      expect(screen.getByText("Limit of 2 reached — remove one to add another.")).toBeInTheDocument();
    });

    it("accepts only what fits when a paste would overflow", async () => {
      const user = userEvent.setup();
      render(<Harness initial={["a"]} suggestions={[]} maxItems={3} />);

      await user.type(screen.getByPlaceholderText(""), "b, c, d, e");
      await user.keyboard("{Enter}");

      // Two free slots -> b and c land, d and e are refused rather than being
      // sent and dropped server-side.
      expect(screen.getByTestId("state").textContent).toBe("a|b|c");
    });

    it("takes chips again after one is removed", async () => {
      const user = userEvent.setup();
      render(<Harness initial={["a", "b"]} suggestions={[]} maxItems={2} />);

      await user.click(screen.getByLabelText("Remove b"));
      await user.type(screen.getByPlaceholderText(""), "c");
      await user.keyboard("{Enter}");

      expect(screen.getByTestId("state").textContent).toBe("a|c");
    });

    it("stops offering suggestions once full", async () => {
      const user = userEvent.setup();
      render(<Harness initial={["rice"]} suggestions={["chicken", "chickpeas"]} maxItems={1} />);

      await user.type(screen.getByPlaceholderText(""), "chick");

      expect(screen.queryByRole("option")).not.toBeInTheDocument();
    });
  });
});

// Satisfy vi mock boilerplate — none needed but keep import to avoid tree-shake quirks.
void vi;
