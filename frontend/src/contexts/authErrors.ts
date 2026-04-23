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
