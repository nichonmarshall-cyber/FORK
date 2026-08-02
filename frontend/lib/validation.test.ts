import { describe, expect, it } from "vitest";
import { parseCreditsField, validateCreditsPair } from "./validation";

describe("validateCreditsPair", () => {
  it("blocks completed=72, transferable=74 client-side", () => {
    const result = validateCreditsPair("72", "74");
    expect(result.isValid).toBe(false);
    expect(result.transferable.error).toBe(
      "Transferable credits cannot exceed completed credits. You can transfer up to 72 credits.",
    );
  });

  it("accepts completed=72, transferable=72 (equal is allowed)", () => {
    const result = validateCreditsPair("72", "72");
    expect(result.isValid).toBe(true);
    expect(result.completed.error).toBeNull();
    expect(result.transferable.error).toBeNull();
  });

  it("accepts completed=0, transferable=0", () => {
    const result = validateCreditsPair("0", "0");
    expect(result.isValid).toBe(true);
    expect(result.completed.value).toBe(0);
    expect(result.transferable.value).toBe(0);
  });

  it("rejects negative values", () => {
    const result = validateCreditsPair("-5", "0");
    expect(result.isValid).toBe(false);
    expect(result.completed.error).toBe("Must be zero or more.");
  });

  it("rejects decimal values", () => {
    const result = validateCreditsPair("72.5", "60");
    expect(result.isValid).toBe(false);
    expect(result.completed.error).toBe("Whole numbers only.");
  });

  it("normalizes leading zeros: '074' displays as '74'", () => {
    const result = validateCreditsPair("074", "060");
    expect(result.completed.display).toBe("74");
    expect(result.completed.value).toBe(74);
    expect(result.transferable.display).toBe("60");
    expect(result.transferable.value).toBe(60);
    expect(result.isValid).toBe(true);
  });

  it("a lone zero stays '0', not stripped to empty", () => {
    const result = parseCreditsField("0");
    expect(result.display).toBe("0");
    expect(result.value).toBe(0);
    expect(result.error).toBeNull();
  });

  it("empty input is invalid but doesn't crash", () => {
    const result = parseCreditsField("");
    expect(result.value).toBeNull();
    expect(result.error).toBe("Enter a number.");
  });

  it("non-numeric garbage is rejected, not silently coerced to 0", () => {
    const result = parseCreditsField("abc");
    expect(result.value).toBeNull();
    expect(result.error).toBe("Enter a whole number.");
  });

  it("mirrors the backend's le=300 bound on credits_completed", () => {
    const atLimit = validateCreditsPair("300", "300");
    expect(atLimit.isValid).toBe(true);

    const overLimit = validateCreditsPair("301", "0");
    expect(overLimit.isValid).toBe(false);
    expect(overLimit.completed.error).toBe("Must be 300 or fewer.");
  });

  it("a valid completed value doesn't mask an invalid transferable value", () => {
    // Regression guard: the cross-field check must not run (and thus must
    // not falsely report "exceeds completed") when transferable itself
    // isn't a valid number yet.
    const result = validateCreditsPair("72", "abc");
    expect(result.isValid).toBe(false);
    expect(result.transferable.error).toBe("Enter a whole number.");
  });
});