"use client";

import { useEffect, useRef, useState } from "react";
import { ComparisonOptionOutcome } from "@/lib/types";

/**
 * The "1 of 4" control in the workspace header.
 *
 * This changes which alternative's detailed pairwise map is on screen.
 * It does NOT change which majors are being compared — those stay active
 * in the conversation regardless of what's displayed. The component
 * makes no network call at all, which is the structural reason it can't
 * affect active_options: there's nothing for it to tell the backend.
 *
 * The denominator counts prospective alternatives only. The anchor is
 * what they're all measured against, not one of the numbered options.
 */

interface Props {
  options: ComparisonOptionOutcome[];
  selectedMajorKey: string;
  onSelect: (majorKey: string) => void;
  /** Called when a pending path is chosen, so the form can move focus to
   * the input that's missing. */
  onFocusPending: (majorKey: string) => void;
}

export default function PathNavigator({
  options,
  selectedMajorKey,
  onSelect,
  onFocusPending,
}: Props) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const position = options.findIndex((o) => o.major_key === selectedMajorKey);
  const displayPosition = position >= 0 ? position + 1 : 1;
  const total = options.length;

  useEffect(() => {
    if (open) setActiveIndex(position >= 0 ? position : 0);
  }, [open, position]);

  useEffect(() => {
    if (open) itemRefs.current[activeIndex]?.focus();
  }, [open, activeIndex]);

  // Close on outside click and on Escape. Both are what a popover is
  // expected to do, and skipping them strands keyboard users inside it.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  function choose(option: ComparisonOptionOutcome) {
    setOpen(false);
    if (option.status === "calculated") {
      onSelect(option.major_key);
    } else {
      // No result exists for this path, so there's nothing to display.
      // Sending the student to the input that's missing is more useful
      // than swapping to a blank map.
      onFocusPending(option.major_key);
    }
  }

  function onListKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % total);
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + total) % total);
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`View comparison paths, currently viewing ${displayPosition} of ${total}`}
        className="flex items-center gap-1 rounded border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[12px] text-slate-300 hover:bg-white/[0.07]"
      >
        {displayPosition} of {total}
        <span aria-hidden="true" className="text-[9px]">
          ▾
        </span>
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Comparison paths"
          onKeyDown={onListKeyDown}
          className="absolute left-0 z-20 mt-1 w-64 rounded-md border border-white/10 bg-[#0d1220] p-1 shadow-xl"
        >
          <p className="px-2 py-1 text-[10px] uppercase tracking-wide text-slate-500">
            Comparison paths
          </p>
          {options.map((option, i) => {
            const isSelected = option.major_key === selectedMajorKey;
            const pending = option.status !== "calculated";
            return (
              <button
                key={option.major_key}
                ref={(el) => {
                  itemRefs.current[i] = el;
                }}
                type="button"
                role="option"
                aria-selected={isSelected}
                tabIndex={i === activeIndex ? 0 : -1}
                onClick={() => choose(option)}
                className={
                  "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[12px] " +
                  (isSelected
                    ? "bg-white/[0.08] text-slate-100"
                    : "text-slate-300 hover:bg-white/[0.05]")
                }
              >
                <span className="w-3 shrink-0 text-slate-500">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate">{option.major}</span>
                {isSelected && (
                  <span className="shrink-0 text-[10px] text-slate-400">
                    Viewing
                  </span>
                )}
                {pending && !isSelected && (
                  <span className="shrink-0 text-[10px] text-amber-400">
                    Needs info
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
