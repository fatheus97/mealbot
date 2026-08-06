import { landingCopy } from "./copy";
// The landing page's "Request access" form.
//
// Replaces the old mailto: link so requests land in a queue the admin can act
// on (dashboard → Invites) instead of an inbox. Same vanilla-DOM approach as
// the auth dialog — this is the SEO page, and it stays React-free.

export interface AccessFormElements {
  form: HTMLFormElement;
  email: HTMLInputElement;
  message: HTMLTextAreaElement;
  submit: HTMLButtonElement;
  /** role="alert" — failures, announced assertively. Lives BELOW the submit
   *  button so showing it can't shift the button mid-click. */
  error: HTMLElement;
  /** role="status" — the success confirmation, announced politely. */
  status: HTMLElement;
}

// Read per call, not once at module load: `landingCopy()` needs
// `document.documentElement.lang`, which is not there when this module is
// first evaluated.

/** Client-side guard so an empty submit doesn't cost a round-trip. Email
 *  *format* is left to the browser's native type=email validation (the form is
 *  no longer `novalidate`) and to the server — a homegrown regex would reject
 *  valid addresses. */
export function validateAccessRequest(email: string): string | null {
  return email.trim() ? null : landingCopy().accessNeedEmail;
}

/**
 * Submit the form. Resolves with the message to display, rejects with an
 * Error whose message is displayable.
 *
 * The success copy is whatever the server returns — deliberately identical
 * for a new request, a duplicate, and an address that already has an account,
 * so the form can't be used to probe who has one.
 */
export async function submitAccessRequest(email: string, message: string): Promise<string> {
  let resp: Response;
  try {
    resp = await fetch("/api/access-requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, message }),
    });
  } catch {
    throw new Error(landingCopy().accessGenericFailure);
  }

  if (resp.status === 429) throw new Error(landingCopy().accessRateLimited);
  // 422 is Pydantic rejecting what they typed — almost always a mistyped
  // address, which is the single most likely failure on this form. Saying so
  // discloses nothing (it's about their own input, not about our data), and
  // "Something went wrong" would leave them nothing to correct.
  if (resp.status === 422) throw new Error(landingCopy().accessBadEmail);
  if (!resp.ok) throw new Error(landingCopy().accessGenericFailure);

  const body = (await resp.json().catch(() => null)) as { message?: string } | null;
  return body?.message ?? landingCopy().accessThanks;
}

export function createAccessForm(
  els: AccessFormElements,
  deps: { submit?: (email: string, message: string) => Promise<string> } = {},
) {
  const send = deps.submit ?? submitAccessRequest;
  let busy = false;

  function setError(text: string): void {
    els.error.textContent = text;
    els.error.hidden = !text;
    // Tie the message to the field for screen readers, and mark the field
    // invalid so it isn't only conveyed by colour.
    els.email.setAttribute("aria-invalid", text ? "true" : "false");
  }

  async function onSubmit(event: Event): Promise<void> {
    event.preventDefault();
    if (busy) return;

    const email = els.email.value;
    const invalid = validateAccessRequest(email);
    if (invalid) {
      setError(invalid);
      els.email.focus();
      return;
    }

    busy = true;
    els.submit.disabled = true;
    els.submit.textContent = landingCopy().accessBusy;
    setError("");
    try {
      const message = await send(email, els.message.value);
      // Replace the form with the confirmation rather than leaving a filled-in
      // form the visitor might submit again (which would silently no-op
      // server-side, looking broken).
      els.form.hidden = true;
      els.status.textContent = message;
      els.status.hidden = false;
      // Focus was on the submit button, which just disappeared with the form —
      // without this a keyboard/screen-reader user is dumped back at <body>
      // with no idea the request succeeded.
      els.status.focus();
    } catch (err) {
      setError(err instanceof Error ? err.message : landingCopy().accessGenericFailure);
      els.submit.disabled = false;
      els.submit.textContent = landingCopy().accessSubmit;
      busy = false;
      els.email.focus();
    }
  }

  els.form.addEventListener("submit", (e) => void onSubmit(e));
  return { onSubmit };
}
