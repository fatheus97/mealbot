import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  createAccessForm,
  submitAccessRequest,
  validateAccessRequest,
  type AccessFormElements,
} from "./accessRequest";

// See authApi.test.ts: src/test/setup.ts installs localStorage via
// vi.stubGlobal, so vi.unstubAllGlobals() here would delete it. Re-stub fetch
// per test instead — vitest isolates globals per test file.

function mount(): AccessFormElements {
  document.body.innerHTML = `
    <form id="access-form">
      <input id="access-email" />
      <textarea id="access-message"></textarea>
      <button type="submit" id="access-submit">Send request</button>
      <div id="access-error" role="alert" hidden></div>
    </form>
    <div id="access-status" role="status" tabindex="-1" hidden></div>`;
  const $ = (id: string) => document.getElementById(id)!;
  return {
    form: $("access-form") as HTMLFormElement,
    email: $("access-email") as HTMLInputElement,
    message: $("access-message") as HTMLTextAreaElement,
    submit: $("access-submit") as HTMLButtonElement,
    error: $("access-error"),
    status: $("access-status"),
  };
}

function submitForm(els: AccessFormElements) {
  els.form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
}

describe("validateAccessRequest", () => {
  it("requires an email", () => {
    expect(validateAccessRequest("")).toMatch(/email/i);
    expect(validateAccessRequest("   ")).toMatch(/email/i);
  });

  it("accepts anything non-empty — format is the server's call", () => {
    // A homegrown email regex rejects valid addresses; type=email + the
    // server's EmailStr are the real validators.
    expect(validateAccessRequest("a@b.com")).toBeNull();
  });
});

describe("submitAccessRequest", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

  it("posts the email and message and returns the LOCAL acknowledgement", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ message: "Thanks — we've got your request." }),
    } as unknown as Response);

    const msg = await submitAccessRequest("a@b.com", "let me in");
    expect(msg).toMatch(/thanks/i);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/access-requests");
    expect(JSON.parse(init!.body as string)).toEqual({
      email: "a@b.com",
      message: "let me in",
    });
  });

  it("ignores the server's English ack on a Czech page", async () => {
    // `_NEUTRAL_ACK` in backend/app/api/access_request.py is an English-only
    // constant, and preferring it meant a Czech visitor filled in a Czech
    // form and got an English thank-you. Nothing is lost by dropping it: the
    // endpoint returns one fixed sentence for EVERY outcome on purpose, so it
    // carries no information the local copy lacks.
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ message: "Thanks — we've got your request." }),
    } as unknown as Response);

    document.documentElement.setAttribute("lang", "cs");
    try {
      await expect(submitAccessRequest("a@b.com", "")).resolves.toBe("Díky — žádost máme.");
    } finally {
      document.documentElement.removeAttribute("lang");
    }
  });

  it("surfaces a dedicated message when rate-limited", async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 429 } as unknown as Response);
    await expect(submitAccessRequest("a@b.com", "")).rejects.toThrow(/try again in a minute/i);
  });

  it("tells the visitor their EMAIL is wrong on a 422, not 'something went wrong'", async () => {
    // A typo'd address is the single most likely failure on this form; the
    // generic message would leave them nothing to correct.
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 422 } as unknown as Response);
    await expect(submitAccessRequest("typo@@example", "")).rejects.toThrow(
      /valid email address/i,
    );
  });

  it("falls back to generic copy on a server error", async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 500 } as unknown as Response);
    await expect(submitAccessRequest("a@b.com", "")).rejects.toThrow(/something went wrong/i);
  });

  it("falls back to generic copy when the network is down", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("offline"));
    await expect(submitAccessRequest("a@b.com", "")).rejects.toThrow(/something went wrong/i);
  });

  it("still resolves when the 201 body isn't parseable", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.reject(new Error("no body")),
    } as unknown as Response);
    await expect(submitAccessRequest("a@b.com", "")).resolves.toMatch(/thanks/i);
  });
});

describe("access form", () => {
  let els: AccessFormElements;

  beforeEach(() => {
    els = mount();
  });

  it("blocks an empty submit without calling the API", () => {
    const submit = vi.fn<(e: string, m: string) => Promise<string>>();
    createAccessForm(els, { submit });
    submitForm(els);

    expect(submit).not.toHaveBeenCalled();
    expect(els.error.hidden).toBe(false);
    expect(els.error.textContent).toMatch(/email/i);
    expect(els.email.getAttribute("aria-invalid")).toBe("true");
  });

  it("hides the form and shows the confirmation on success", async () => {
    const submit = vi.fn().mockResolvedValue("Thanks — we've got your request.");
    createAccessForm(els, { submit });
    els.email.value = "a@b.com";
    els.message.value = "hello";
    submitForm(els);

    await vi.waitFor(() => expect(els.form.hidden).toBe(true));
    expect(submit).toHaveBeenCalledWith("a@b.com", "hello");
    expect(els.status.hidden).toBe(false);
    expect(els.status.textContent).toMatch(/thanks/i);
    // The submit button just vanished with the form — focus must land on the
    // confirmation, not fall back to <body> with no feedback.
    expect(document.activeElement).toBe(els.status);
  });

  it("keeps the form usable and re-enables the button on failure", async () => {
    const submit = vi.fn().mockRejectedValue(new Error("Too many requests just now."));
    createAccessForm(els, { submit });
    els.email.value = "a@b.com";
    submitForm(els);

    await vi.waitFor(() => expect(els.error.hidden).toBe(false));
    expect(els.form.hidden).toBe(false);
    expect(els.submit.disabled).toBe(false);
    expect(els.submit.textContent).toBe("Send request");
    // The success node must stay hidden — an error is not a confirmation.
    expect(els.status.hidden).toBe(true);
  });

  it("ignores a second submit while the first is in flight", async () => {
    let resolve!: (v: string) => void;
    const submit = vi.fn().mockReturnValue(new Promise<string>((r) => (resolve = r)));
    createAccessForm(els, { submit });
    els.email.value = "a@b.com";

    submitForm(els);
    submitForm(els);
    submitForm(els);
    expect(submit).toHaveBeenCalledTimes(1);

    resolve("ok");
    await vi.waitFor(() => expect(els.form.hidden).toBe(true));
  });

  it("shows a pending label while sending", () => {
    createAccessForm(els, { submit: () => new Promise(() => {}) });
    els.email.value = "a@b.com";
    submitForm(els);
    expect(els.submit.textContent).toBe("Sending…");
    expect(els.submit.disabled).toBe(true);
  });
});
