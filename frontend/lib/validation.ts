/**
 * Client-side validation for the Change Major scenario form.
 *
 * Kept as pure functions, deliberately separate from any React component,
 * so they can be unit-tested without rendering anything and reused
 * anywhere a credit value needs checking. None of this duplicates the
 * backend's authority — Pydantic in inputs.py is still the source of
 * truth and still runs on every request. This layer exists only to catch
 * the same problems earlier, with a specific field-level message, instead
 * of round-tripping to the server to find out "74 can't exceed 72."
 */

export interface CreditFieldResult {
  /** The value to actually feed the request. null when the raw text isn't
   * a usable whole number at all (empty, decimal, non-numeric). */
  value: number | null;
  /** Cleaned-up display string — strips leading zeros, keeps the field
   * showing what the user is actually typing otherwise. */
  display: string;
  error: string | null;
}

/**
 * Normalizes and validates a single credits field in isolation (whole
 * number, non-negative). Doesn't know about the OTHER field — the
 * cross-field "transferable can't exceed completed" rule lives in
 * validateCreditsPair below, since it genuinely needs both values.
 */
export function parseCreditsField(raw: string): CreditFieldResult {
  const trimmed = raw.trim();

  if (trimmed === "") {
    return { value: null, display: "", error: "Enter a number." };
  }

  // Reject anything that isn't a plain non-negative whole number BEFORE
  // parsing — Number("74abc") is NaN so that's already caught, but
  // Number(" ") is 0 and Number("1e2") is 100, both of which look like
  // numbers but aren't what a whole-number credits field should accept.
  if (!/^\d+$/.test(trimmed)) {
    // Still normalize what's shown so a stray leading zero on an
    // otherwise-invalid entry doesn't linger, e.g. "07.5" -> keep as
    // typed since it's invalid anyway; just report the specific problem.
    const isNegative = trimmed.startsWith("-");
    const isDecimal = /^\d+\.\d+$/.test(trimmed);
    return {
      value: null,
      display: trimmed,
      error: isNegative
        ? "Must be zero or more."
        : isDecimal
          ? "Whole numbers only."
          : "Enter a whole number.",
    };
  }

  const normalized = trimmed.replace(/^0+(?=\d)/, ""); // "074" -> "74", "0" stays "0"
  const value = Number(normalized);

  // Matches inputs.py's Field(..., le=300) on credits_completed exactly —
  // this bound has to track the backend's, or a value that passes here
  // could still come back as a raw validation error, which is the exact
  // failure mode this file exists to prevent.
  if (value > 300) {
    return {
      value: null,
      display: normalized,
      error: "Must be 300 or fewer.",
    };
  }

  return { value, display: normalized, error: null };
}

export interface CreditsPairResult {
  completed: CreditFieldResult;
  transferable: CreditFieldResult;
  /** True only when BOTH fields are individually valid AND the cross-field
   * rule holds. This is what actually gates the submit button. */
  isValid: boolean;
}

/**
 * Validates both credit fields together, including the one rule that
 * needs both values at once. Mirrors inputs.py's
 * transferable_cannot_exceed_completed validator exactly — same
 * condition, so the client rejects it before a request is ever sent, and
 * the same case the backend rejects can't silently diverge from what the
 * user sees here.
 */
export function validateCreditsPair(
  completedRaw: string,
  transferableRaw: string,
): CreditsPairResult {
  const completed = parseCreditsField(completedRaw);
  const transferable = parseCreditsField(transferableRaw);

  if (
    completed.value !== null &&
    transferable.value !== null &&
    transferable.value > completed.value
  ) {
    return {
      completed,
      transferable: {
        ...transferable,
        error: `Transferable credits cannot exceed completed credits. You can transfer up to ${completed.value} credits.`,
      },
      isValid: false,
    };
  }

  return {
    completed,
    transferable,
    isValid: completed.error === null && transferable.error === null,
  };
}