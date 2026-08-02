import { describe, it, expect } from "vitest";
import { extractErrorDetail } from "./httpError";

function res(status: number, body: unknown, { json = true } = {}): Response {
  return {
    status,
    json: () => (json ? Promise.resolve(body) : Promise.reject(new SyntaxError("not JSON"))),
  } as unknown as Response;
}

describe("extractErrorDetail", () => {
  it("returns a string detail as-is", async () => {
    const out = await extractErrorDetail(res(409, { detail: "Not enough chicken." }), "fb");
    expect(out).toBe("Not enough chicken.");
  });

  it("reads user_detail out of a structured detail", async () => {
    const out = await extractErrorDetail(
      res(429, { detail: { user_detail: "You have used your €2.00.", code: "usage_cap_reached" } }),
      "fb",
    );
    expect(out).toBe("You have used your €2.00.");
  });

  it("falls back for a Pydantic list detail", async () => {
    // Pins the BEHAVIOUR (field errors never reach the user), not the
    // Array.isArray guard — an array has no `user_detail` either way, so the
    // guard is defensive and no test can distinguish it. See httpError.ts.
    const out = await extractErrorDetail(res(422, { detail: [{ msg: "field required" }] }), "fb");
    expect(out).toBe("fb (422)");
    expect(out).not.toMatch(/field required/);
  });

  it("falls back on a non-JSON body", async () => {
    // nginx/Caddy error pages and proxy timeouts are HTML, not JSON.
    const out = await extractErrorDetail(res(502, null, { json: false }), "fb");
    expect(out).toBe("fb (502)");
  });

  it("falls back when detail is absent", async () => {
    const out = await extractErrorDetail(res(500, {}), "fb");
    expect(out).toBe("fb (500)");
  });

  it("falls back on an empty user_detail rather than showing a blank error", async () => {
    const out = await extractErrorDetail(res(429, { detail: { user_detail: "" } }), "fb");
    expect(out).toBe("fb (429)");
  });
});
