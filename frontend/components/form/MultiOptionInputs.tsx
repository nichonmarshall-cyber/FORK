"use client";

import CompareModeToggle from "./CompareModeToggle";
import { validateCreditsPair } from "@/lib/validation";

/**
 * The Compare Multiple input rows.
 *
 * One anchor (the current major) and one completed-credit total are
 * shared, because both are facts about the student. Everything else is
 * per option: the same 72 completed credits apply differently to
 * different programs, so each alternative carries its own transfer
 * figure and its own validation error.
 *
 * Rows are keyed by major rather than by array index. That's what keeps
 * a removal from shuffling values onto the wrong major — with index keys,
 * deleting row 2 makes React reuse row 2's DOM for what was row 3, and
 * the transfer number visibly lands on the wrong program.
 */

export interface DraftOption {
  major: string;
  /** Raw text, matching how the pairwise form holds credit inputs — lets
   * "typed something invalid" be a visible state rather than silently
   * coercing to 0. */
  transferableRaw: string;
}

export const MAX_OPTIONS = 4;
export const MIN_OPTIONS = 2;

interface Props {
  majors: { key: string; label: string }[];
  currentMajor: string;
  completedRaw: string;
  options: DraftOption[];
  onChange: (options: DraftOption[]) => void;
  /** True once submit has been attempted, so errors don't appear while
   * someone is still typing their first value. */
  showErrors: boolean;
  disabled?: boolean;
  /** Shared refs so the path navigator can move focus to a pending
   * option's input. Keyed by major, not index — see the note about row
   * keys above. */
  inputRefs?: React.MutableRefObject<Record<string, HTMLInputElement | null>>;
}

/** Validation for one row, independent of every other row. */
export function validateOption(
  option: DraftOption,
  completedRaw: string,
): string | null {
  if (!option.major) return "Choose a major.";
  // Reuses the pairwise rules so "cannot exceed completed" is defined in
  // one place and can't drift between the two forms.
  const result = validateCreditsPair(completedRaw, option.transferableRaw);
  return result.transferable.error;
}

export function validateAllOptions(
  options: DraftOption[],
  completedRaw: string,
): { errors: Record<string, string>; isValid: boolean } {
  const errors: Record<string, string> = {};
  for (const option of options) {
    const error = validateOption(option, completedRaw);
    if (error) errors[option.major || "unset"] = error;
  }
  return { errors, isValid: Object.keys(errors).length === 0 };
}

export default function MultiOptionInputs({
  majors,
  currentMajor,
  completedRaw,
  options,
  onChange,
  showErrors,
  disabled,
  inputRefs,
}: Props) {
  // A major already chosen in another row, or the anchor itself, can't be
  // picked again. Filtering the dropdown is what prevents duplicates —
  // rejecting them after the fact would let someone build an invalid
  // comparison and only find out on submit.
  const taken = new Set([currentMajor, ...options.map((o) => o.major)]);
  const available = majors.filter((m) => !taken.has(m.key));
  const canAdd = options.length < MAX_OPTIONS && available.length > 0;
  const canRemove = options.length > MIN_OPTIONS;

  const { errors } = validateAllOptions(options, completedRaw);
  const labelFor = (key: string) =>
    majors.find((m) => m.key === key)?.label ?? key;

  function updateRow(major: string, patch: Partial<DraftOption>) {
    onChange(options.map((o) => (o.major === major ? { ...o, ...patch } : o)));
  }

  function removeRow(major: string) {
    onChange(options.filter((o) => o.major !== major));
  }

  function addRow() {
    if (!canAdd) return;
    onChange([...options, { major: available[0].key, transferableRaw: "" }]);
  }

  return (
    <div className="space-y-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
        Compare against
      </p>

      {options.map((option) => {
        const error = showErrors ? errors[option.major] : undefined;
        const inputId = `transfer-${option.major}`;
        // Each row's dropdown offers what's free plus its own current
        // value, so a row can always still show what it's set to.
        const choices = majors.filter(
          (m) => m.key === option.major || !taken.has(m.key),
        );

        return (
          <div
            key={option.major}
            className="rounded-md border border-white/[0.07] bg-white/[0.02] p-2.5"
          >
            <div className="flex items-center gap-2">
              <select
                value={option.major}
                disabled={disabled}
                aria-label="Prospective major"
                onChange={(e) => updateRow(option.major, { major: e.target.value })}
                className="min-w-0 flex-1 rounded border border-white/10 bg-[#0a0e18] px-2 py-1.5 text-[13px] text-slate-100"
              >
                {choices.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                  </option>
                ))}
              </select>

              {canRemove && (
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => removeRow(option.major)}
                  aria-label={`Remove ${labelFor(option.major)} from the comparison`}
                  className="shrink-0 rounded p-1.5 text-slate-500 hover:bg-white/[0.06] hover:text-slate-300"
                >
                  <span aria-hidden="true">×</span>
                </button>
              )}
            </div>

            <div className="mt-2">
              <label
                htmlFor={inputId}
                className="block text-[11px] text-slate-400"
              >
                Credits that apply
              </label>
              <input
                id={inputId}
                ref={(el) => {
                  if (inputRefs) inputRefs.current[option.major] = el;
                }}
                inputMode="numeric"
                value={option.transferableRaw}
                disabled={disabled}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? `${inputId}-error` : undefined}
                onChange={(e) =>
                  updateRow(option.major, { transferableRaw: e.target.value })
                }
                className={
                  "mt-1 w-full rounded border bg-[#0a0e18] px-2 py-1.5 text-[13px] text-slate-100 " +
                  (error ? "border-red-500/60" : "border-white/10")
                }
              />
              {error && (
                <p
                  id={`${inputId}-error`}
                  role="alert"
                  className="mt-1 text-[11px] text-red-400"
                >
                  {error}
                </p>
              )}
            </div>
          </div>
        );
      })}

      {canAdd && (
        <button
          type="button"
          onClick={addRow}
          disabled={disabled}
          className="w-full rounded-md border border-dashed border-white/15 py-1.5 text-[12px] text-slate-400 hover:border-white/25 hover:text-slate-200"
        >
          + Add option
        </button>
      )}
    </div>
  );
}

export { CompareModeToggle };
