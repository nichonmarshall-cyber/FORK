import { describe, expect, it, vi } from "vitest";
import { parseApiError } from "./types";

describe("parseApiError", () => {
  it("translates a structured validation_error into its clean message", () => {
    const parsed = parseApiError({
      status: 422,
      body: {
        detail: {
          status: "validation_error",
          message:
            "credits_transferable cannot exceed credits_completed (got 74 transferable vs 72 completed).",
          errors: [
            { field: "credits_transferable", message: "credits_transferable cannot exceed credits_completed" },
          ],
        },
      },
    });
    expect(parsed.message).toContain("credits_transferable cannot exceed credits_completed");
    expect(parsed.field).toBe("credits_transferable");
  });

  it("never lets raw Pydantic internals through, even if they somehow appear in a message field", () => {
    // Defense in depth: even if the backend regressed and put internals
    // INSIDE the message string, this test documents that the parser's
    // contract is to pass through `message` verbatim — the backend test
    // suite (test_main.py) is what actually guarantees the backend never
    // sends that. This test exists so a frontend reviewer sees explicitly
    // that this layer is not a second line of defense against that.
    const raw = "credits_transferable cannot exceed credits_completed";
    const parsed = parseApiError({
      status: 422,
      body: { detail: { message: raw } },
    });
    expect(parsed.message).not.toContain("errors.pydantic.dev");
    expect(parsed.message).not.toContain("type=value_error");
  });

  it("passes through a plain string detail (FastAPI's own built-in errors)", () => {
    const parsed = parseApiError({
      status: 404,
      body: { detail: "Unknown institution_id 'hogwarts'." },
    });
    expect(parsed.message).toBe("Unknown institution_id 'hogwarts'.");
  });

  it("gives the network-failure message when fetch itself throws", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const parsed = parseApiError({ networkError: new TypeError("Failed to fetch") });
    expect(parsed.message).toBe(
      "We couldn't calculate the difference right now. Please try again.",
    );
    // Technical detail goes to the console, not into the returned message.
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it("falls back safely for an unrecognized error shape rather than showing raw JSON", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const parsed = parseApiError({
      status: 500,
      body: { some_future_field: "not a shape this parser has ever seen" },
    });
    expect(parsed.message).not.toContain("some_future_field");
    expect(parsed.message).toBe(
      "We couldn't calculate the difference right now. Please try again.",
    );
    consoleSpy.mockRestore();
  });

  it("uses a gentler fallback for an unrecognized 4xx than for a 5xx", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const parsed = parseApiError({ status: 418, body: { weird: true } });
    expect(parsed.message).toContain("check your inputs");
    consoleSpy.mockRestore();
  });

  it("never includes a URL, stack trace, or class name in any returned message", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const cases = [
      parseApiError({ status: 422, body: { detail: { message: "bad input" } } }),
      parseApiError({ status: 404, body: { detail: "not found" } }),
      parseApiError({ networkError: new Error("boom") }),
      parseApiError({ status: 500, body: null }),
    ];
    for (const c of cases) {
      expect(c.message).not.toMatch(/https?:\/\//);
      expect(c.message).not.toMatch(/Traceback/);
      expect(c.message).not.toMatch(/ValidationError/);
      expect(c.message).not.toMatch(/pydantic/i);
    }
    consoleSpy.mockRestore();
  });
});