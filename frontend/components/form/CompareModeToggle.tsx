"use client";

/**
 * Switches the left form between comparing one alternative and comparing
 * several. Lives next to the "Considering" section because that's where
 * the student is defining the comparison — putting it in Ask Fork would
 * mean setting up a comparison in one place and defining it in another.
 *
 * Implemented as a radiogroup rather than two buttons so arrow keys move
 * between the options the way a keyboard user expects, and only the
 * active mode sits in the tab order.
 */

export type CompareMode = "one" | "multiple";

interface Props {
  mode: CompareMode;
  onChange: (mode: CompareMode) => void;
  /** Set while a calculation is in flight, so a mode switch can't race a
   * request that's about to write results. */
  disabled?: boolean;
}

const MODES: { value: CompareMode; label: string }[] = [
  { value: "one", label: "Compare one" },
  { value: "multiple", label: "Compare multiple" },
];

export default function CompareModeToggle({ mode, onChange, disabled }: Props) {
  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    onChange(mode === "one" ? "multiple" : "one");
  }

  return (
    <div
      role="radiogroup"
      aria-label="Comparison mode"
      onKeyDown={handleKeyDown}
      className="inline-flex rounded-md border border-white/10 bg-white/[0.03] p-0.5"
    >
      {MODES.map((option) => {
        const active = option.value === mode;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={
              "rounded px-2.5 py-1 text-[12px] font-medium transition-colors disabled:opacity-50 " +
              (active
                ? "bg-white/[0.09] text-slate-100"
                : "text-slate-400 hover:text-slate-200")
            }
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
