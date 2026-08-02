// Turn a non-OK Response into the sentence a user should read.
//
// Lives in utils/, not api.ts, for a mechanical reason: most component and hook
// tests stub the whole `../api` module with a factory listing only the network
// functions they need (`vi.mock('../api', () => ({ authFetch: vi.fn() }))`).
// A pure Response parser exported from there would vanish under every one of
// those stubs — which is exactly what happened when the two duplicate copies
// were first merged into api.ts. This module is never mocked, so error handling
// behaves the same in tests as in the browser.
//
// FastAPI's `detail` is not always a string, and the two non-string shapes need
// opposite treatment:
//   - An OBJECT detail is one of ours. It carries the sentence in `user_detail`
//     and machine-readable siblings (`code`, `cap_eur`, `reset_at`) that must
//     never reach the UI raw. The usage-cap 429 is the only one today; reading
//     `user_detail` generically means the next one works with no new call site.
//   - A LIST detail is a Pydantic *validation* 422 — internal field errors, no
//     sentence for a human — so it falls through to the fallback.
//
// The Array.isArray clause below is DEFENSIVE, not behaviour-defining: a parsed
// JSON array has no `user_detail`, so removing it changes no current output and
// no test can pin it. It is here so that a future, more generous read of the
// object branch (say, "return the first string value") cannot start rendering
// Pydantic field errors at the user. If that branch is ever made generic, this
// clause is what stops the 422 path regressing — keep it.
export async function extractErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const detail = (await res.json())?.detail;
    if (typeof detail === "string") return detail;
    if (detail && !Array.isArray(detail) && typeof detail === "object") {
      const userDetail = (detail as { user_detail?: unknown }).user_detail;
      if (typeof userDetail === "string" && userDetail) return userDetail;
    }
  } catch {
    // non-JSON body — use the fallback
  }
  return `${fallback} (${res.status})`;
}
