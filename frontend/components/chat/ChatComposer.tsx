"use client";

import { useEffect, useRef } from "react";

const MAX_HEIGHT_PX = 120;

/**
 * The message input, pinned at the bottom of the chat panel.
 *
 * A textarea rather than an input because the spec calls for multiline
 * with Shift+Enter — which a single-line input physically can't do. The
 * auto-grow is a manual height reset + scrollHeight read on every change;
 * CSS alone can't size a textarea to its content.
 */
export default function ChatComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  busy,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  /** No calculation yet — the whole composer is unusable. */
  disabled: boolean;
  /** A request is in flight. Input stays editable (so a student can keep
   * typing their next question), only Send is blocked — the spec is
   * explicit that loading must not disable the workspace. */
  busy: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, [value]);

  const canSend = !disabled && !busy && value.trim().length > 0;

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter submits, Shift+Enter inserts a newline. Checking shiftKey
    // before preventing default is what makes the second case work at
    // all — without it the textarea would never receive a line break.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) onSubmit();
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSubmit();
      }}
      className="flex items-end gap-2 border-t border-white/[0.07] px-3 py-2.5"
    >
      <textarea
        ref={ref}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        aria-label="Ask Fork about this decision"
        placeholder={
          disabled
            ? "Calculate a comparison first to ask about it"
            : "Ask Fork about this decision..."
        }
        className="min-w-0 flex-1 resize-none bg-transparent px-1 py-1.5 text-[13px] leading-relaxed text-slate-200 outline-none placeholder:text-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={!canSend}
        aria-label="Send question"
        className="mb-0.5 shrink-0 rounded-lg bg-cyan-500/90 px-3 py-1.5 text-[12px] font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-cyan-500/30 disabled:text-slate-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60"
      >
        {busy ? "…" : "Send"}
      </button>
    </form>
  );
}