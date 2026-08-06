/**
 * Thrown when POST /users/register succeeded (201) but the subsequent
 * auto-login step failed (network hiccup, login rate-limit, 5xx). The
 * caller must surface a registration-succeeded message so the user
 * doesn't try to register again and hit a 409 "email already exists".
 *
 * Lives in its own module (not AuthContext.tsx) so the context file
 * stays a components-only file and keeps React Fast Refresh working.
 */
export class AutoLoginAfterRegisterError extends Error {
  constructor(cause: unknown) {
    super("Account created, but auto-login failed");
    this.name = "AutoLoginAfterRegisterError";
    if (cause instanceof Error) this.cause = cause;
  }
}

/**
 * A failed POST /auth/login, carrying the status so the caller can tell WHICH
 * failure it was.
 *
 * The status is the machine-readable half of the response and the only part a
 * UI should branch on. `/auth/login` answers 401 for a credential failure and
 * 403 for a disabled account — and that split exists precisely so the SPA can
 * distinguish them (see the comment above the 403 in `backend/app/api/auth.py`).
 *
 * Note what this deliberately does NOT carry: the server's `detail` sentence.
 * It arrives already translated, which is tempting, but AuthBar stores a
 * translation KEY rather than text so that switching language re-renders a
 * standing error — text would strand the alert in the old language, which is a
 * bug that has already been fixed here once. A status maps to a key; a sentence
 * does not.
 */
export class LoginFailedError extends Error {
  // Declared, not a `readonly status` constructor parameter: `erasableSyntaxOnly`
  // is on, and parameter properties emit real runtime code.
  readonly status: number;

  constructor(status: number) {
    super(`Login failed: ${status}`);
    this.name = "LoginFailedError";
    this.status = status;
  }
}
