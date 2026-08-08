import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { FeedbackModal } from "./FeedbackModal";
import { useLocaleStore, DEFAULT_LOCALE } from "../store/useLocaleStore";
import { untranslatedEnglishIn } from "../test/i18nAssertions";
import * as api from "../api";

vi.mock("../api", () => ({
  // AuthProvider calls authFetch on mount — stub it.
  authFetch: vi.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve(null) })),
  submitFeedback: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe("FeedbackModal", () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it("leaves no untranslated English when switched to Czech, form AND thanks", async () => {
    // The thank-you state REPLACES the form, so one render can only ever prove
    // one of them. This whole modal shipped untranslated behind an already-
    // translated "Poslat zpětnou vazbu" button — the button was migrated with
    // SettingsPopup and the modal it opens never was.
    vi.spyOn(api, "submitFeedback").mockResolvedValue({ id: 1 } as never);
    useLocaleStore.setState({ locale: "cs", explicit: true });

    const { container } = renderWithProviders(<FeedbackModal onClose={vi.fn()} />);
    expect(screen.getByText("Poslat zpětnou vazbu")).toBeInTheDocument();
    expect(untranslatedEnglishIn(container)).toEqual([]);

    const user = userEvent.setup();
    await user.type(
      screen.getByPlaceholderText(/Co se stalo/),
      "Tohle je dost dlouhá zpráva na odeslání.",
    );
    await user.click(screen.getByRole("button", { name: "Odeslat" }));
    await waitFor(() => expect(screen.getByText(/máme to/)).toBeInTheDocument());
    expect(untranslatedEnglishIn(container)).toEqual([]);
  });

  it("keeps Send disabled until the message is long enough", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FeedbackModal onClose={() => {}} />);

    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();

    await user.type(screen.getByPlaceholderText(/what happened/i), "short");
    expect(send).toBeDisabled(); // < 10 chars trimmed

    await user.type(screen.getByPlaceholderText(/what happened/i), " but now much longer");
    expect(send).toBeEnabled();
  });

  it("submits the report and shows the thank-you state", async () => {
    vi.mocked(api.submitFeedback).mockResolvedValue({ id: 7, status: "new" });
    const user = userEvent.setup();
    renderWithProviders(<FeedbackModal page="settings" onClose={() => {}} />);

    await user.selectOptions(screen.getByRole("combobox"), "feature");
    await user.type(
      screen.getByPlaceholderText(/what happened/i),
      "Please add a weekly shopping list export.",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(api.submitFeedback).toHaveBeenCalledWith({
        kind: "feature",
        message: "Please add a weekly shopping list export.",
        page: "settings",
        screenshot_base64: null,
        screenshot_content_type: null,
      }),
    );
    expect(await screen.findByText(/thanks — we got it/i)).toBeInTheDocument();
  });

  it("surfaces a server error and stays on the form", async () => {
    vi.mocked(api.submitFeedback).mockRejectedValue(
      new Error("You've already sent this — thanks, we have it."),
    );
    const user = userEvent.setup();
    renderWithProviders(<FeedbackModal onClose={() => {}} />);

    await user.type(
      screen.getByPlaceholderText(/what happened/i),
      "The regenerate button is broken.",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already sent/i);
    // Still on the form (not the thank-you) — retryable.
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  describe("screenshot attachment", () => {
    async function fillValidMessage(user: ReturnType<typeof userEvent.setup>) {
      await user.type(
        screen.getByPlaceholderText(/what happened/i),
        "The regenerate button is broken.",
      );
    }

    it("attaches a screenshot via the file input and includes it on submit", async () => {
      vi.mocked(api.submitFeedback).mockResolvedValue({ id: 1, status: "new" });
      const user = userEvent.setup();
      renderWithProviders(<FeedbackModal onClose={() => {}} />);
      await fillValidMessage(user);

      const file = new File(["fake-png-bytes"], "bug.png", { type: "image/png" });
      await user.upload(screen.getByLabelText(/attach screenshot/i), file);

      // Preview + Remove replace the Attach button once a file is set.
      expect(await screen.findByAltText(/screenshot preview/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /remove/i })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /attach screenshot/i })).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Send" }));

      await waitFor(() => {
        const payload = vi.mocked(api.submitFeedback).mock.calls[0][0];
        expect(payload.screenshot_content_type).toBe("image/png");
        expect(payload.screenshot_base64).toEqual(expect.any(String));
        expect(payload.screenshot_base64!.length).toBeGreaterThan(0);
      });
    });

    it("removes an attached screenshot and submits without one", async () => {
      vi.mocked(api.submitFeedback).mockResolvedValue({ id: 1, status: "new" });
      const user = userEvent.setup();
      renderWithProviders(<FeedbackModal onClose={() => {}} />);
      await fillValidMessage(user);

      const file = new File(["fake-png-bytes"], "bug.png", { type: "image/png" });
      await user.upload(screen.getByLabelText(/attach screenshot/i), file);
      expect(await screen.findByAltText(/screenshot preview/i)).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /remove/i }));
      expect(screen.queryByAltText(/screenshot preview/i)).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /attach screenshot/i })).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Send" }));
      await waitFor(() => {
        const payload = vi.mocked(api.submitFeedback).mock.calls[0][0];
        expect(payload.screenshot_base64).toBeNull();
        expect(payload.screenshot_content_type).toBeNull();
      });
    });

    it("rejects an unsupported file type client-side", async () => {
      // userEvent.upload() filters by the input's `accept`, which would mask
      // this case — use fireEvent to simulate a file that got through anyway
      // (e.g. the OS picker's "All Files" option, or a drag-and-drop, neither
      // of which `accept` actually blocks), exercising the JS-level guard.
      const user = userEvent.setup();
      renderWithProviders(<FeedbackModal onClose={() => {}} />);
      await fillValidMessage(user);

      const file = new File(["<svg/>"], "bug.svg", { type: "image/svg+xml" });
      const input = screen.getByLabelText(/attach screenshot/i);
      Object.defineProperty(input, "files", { value: [file] });
      fireEvent.change(input);

      expect(await screen.findByRole("alert")).toHaveTextContent(/png or jpeg/i);
      expect(screen.queryByAltText(/screenshot preview/i)).not.toBeInTheDocument();
    });

    it("rejects an oversized file client-side", async () => {
      const user = userEvent.setup();
      renderWithProviders(<FeedbackModal onClose={() => {}} />);
      await fillValidMessage(user);

      const oversized = new File([new Uint8Array(3 * 1024 * 1024 + 1)], "big.png", {
        type: "image/png",
      });
      await user.upload(screen.getByLabelText(/attach screenshot/i), oversized);

      expect(await screen.findByRole("alert")).toHaveTextContent(/too large/i);
      expect(screen.queryByAltText(/screenshot preview/i)).not.toBeInTheDocument();
    });

    it("attaches a pasted image", async () => {
      vi.mocked(api.submitFeedback).mockResolvedValue({ id: 1, status: "new" });
      const user = userEvent.setup();
      renderWithProviders(<FeedbackModal onClose={() => {}} />);
      await fillValidMessage(user);

      const file = new File(["fake-jpeg-bytes"], "pasted.jpg", { type: "image/jpeg" });
      const textarea = screen.getByPlaceholderText(/what happened/i);
      fireEvent.paste(textarea, {
        clipboardData: {
          items: [{ type: "image/jpeg", getAsFile: () => file }],
        },
      });

      expect(await screen.findByAltText(/screenshot preview/i)).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Send" }));
      await waitFor(() => {
        const payload = vi.mocked(api.submitFeedback).mock.calls[0][0];
        expect(payload.screenshot_content_type).toBe("image/jpeg");
      });
    });

    it("keeps pasted text when the clipboard also carries an image flavor", async () => {
      // Regression: onPaste used to preventDefault() on the mere presence of
      // an image item, dropping the text half of a copy that carried both
      // (e.g. a rich webpage selection). Text must win — the image is still
      // reachable via the explicit Attach button.
      renderWithProviders(<FeedbackModal onClose={() => {}} />);

      const file = new File(["fake-png-bytes"], "bug.png", { type: "image/png" });
      const textarea = screen.getByPlaceholderText(/what happened/i);
      fireEvent.paste(textarea, {
        clipboardData: {
          items: [
            { kind: "string", type: "text/plain", getAsFile: () => null },
            { kind: "file", type: "image/png", getAsFile: () => file },
          ],
        },
      });

      // Not prevented -> no image attached (the caller decides whether the
      // browser's default text insertion actually lands; this handler's job
      // is only to not steal the event when text is present).
      expect(screen.queryByAltText(/screenshot preview/i)).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /attach screenshot/i })).toBeInTheDocument();
    });

    it("rejects a 0-byte file client-side without discarding the typed message", async () => {
      const user = userEvent.setup();
      renderWithProviders(<FeedbackModal onClose={() => {}} />);
      await fillValidMessage(user);

      const empty = new File([], "empty.png", { type: "image/png" });
      await user.upload(screen.getByLabelText(/attach screenshot/i), empty);

      expect(await screen.findByRole("alert")).toHaveTextContent(/empty/i);
      expect(screen.queryByAltText(/screenshot preview/i)).not.toBeInTheDocument();
      // The message survives — rejection happened before submit, not via a
      // whole-request 422.
      expect(screen.getByPlaceholderText(/what happened/i)).toHaveValue(
        "The regenerate button is broken.",
      );
      expect(api.submitFeedback).not.toHaveBeenCalled();
    });

    it("clears the file input after a reject so re-selecting the same file retries", async () => {
      const user = userEvent.setup();
      renderWithProviders(<FeedbackModal onClose={() => {}} />);
      await fillValidMessage(user);

      const oversized = new File([new Uint8Array(3 * 1024 * 1024 + 1)], "big.png", {
        type: "image/png",
      });
      const input = screen.getByLabelText(/attach screenshot/i) as HTMLInputElement;
      await user.upload(input, oversized);
      await screen.findByRole("alert");

      expect(input.value).toBe("");
    });

    it("shows an error when the file can't be read", async () => {
      const user = userEvent.setup();
      renderWithProviders(<FeedbackModal onClose={() => {}} />);
      await fillValidMessage(user);

      // jsdom's FileReader.readAsDataURL succeeds unconditionally, so force
      // the failure path directly to prove the handler is wired up at all —
      // this component shipped with reader.onload set and no reader.onerror,
      // which left a failed read completely silent (no banner, no state
      // change, nothing telling the user the attach didn't work).
      const originalReadAsDataURL = FileReader.prototype.readAsDataURL;
      FileReader.prototype.readAsDataURL = function (this: FileReader) {
        this.onerror?.(new ProgressEvent("error") as ProgressEvent<FileReader>);
      };

      try {
        const file = new File(["fake-png-bytes"], "bug.png", { type: "image/png" });
        await user.upload(screen.getByLabelText(/attach screenshot/i), file);

        expect(await screen.findByRole("alert")).toHaveTextContent(/could not read/i);
        expect(screen.queryByAltText(/screenshot preview/i)).not.toBeInTheDocument();
      } finally {
        // A global prototype patch that survives a failed assertion would
        // otherwise leak into every test that runs after this one.
        FileReader.prototype.readAsDataURL = originalReadAsDataURL;
      }
    });
  });
});
