"use client";

/**
 * Left rail.
 *
 * Only "Decision Map" is built. The rest are listed because they're on the
 * roadmap and the shape of the product is easier to understand with them
 * visible — but they're rendered as disabled with a "soon" tag rather than
 * as links that go nowhere. A dead nav item is worse in a live demo than an
 * honest one.
 */

import { NODES } from "@/lib/nodes";
import { CalcResult } from "@/lib/types";

const NAV = [
  { label: "Decision Map", built: true },
  { label: "My Decisions", built: false },
  { label: "Reports", built: false },
  { label: "Saved Paths", built: false },
  { label: "Profile", built: false },
  { label: "Settings", built: false },
];

export default function Sidebar({ result }: { result: CalcResult | null }) {
  // Progress is counted from the map itself rather than hardcoded, so it
  // can't drift out of sync when nodes are added or removed.
  const total = NODES.length;
  const answered = result
    ? NODES.filter((n) => {
        const s = n.resolve(result).state;
        return s === "completed" || s === "at_risk";
      }).length
    : 0;
  const pct = Math.round((answered / total) * 100);

  return (
    <nav className="flex h-full flex-col gap-6 rounded-2xl border border-white/[0.07] bg-[#0a0e17] px-4 py-5">
      <div className="flex items-center gap-2.5 px-1">
        <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden>
          <path
            d="M12 22V13 M12 13 L5 5 M12 13 L19 5"
            fill="none"
            stroke="#22d3ee"
            strokeWidth="2.2"
            strokeLinecap="round"
          />
        </svg>
        <span className="text-[15px] font-semibold tracking-[0.22em] text-slate-100">
          FORK
        </span>
      </div>

      <ul className="space-y-0.5">
        {NAV.map((item) => (
          <li key={item.label}>
            <button
              disabled={!item.built}
              aria-current={item.built ? "page" : undefined}
              className={
                item.built
                  ? "w-full rounded-lg bg-cyan-400/10 px-3 py-2 text-left text-[13.5px] font-medium text-cyan-300"
                  : "flex w-full cursor-not-allowed items-center justify-between rounded-lg px-3 py-2 text-left text-[13.5px] text-slate-600"
              }
            >
              {item.label}
              {!item.built && (
                <span className="rounded border border-white/10 px-1.5 py-px text-[9.5px] uppercase tracking-wider text-slate-600">
                  soon
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>

      <div className="mt-auto space-y-5">
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5">
          <p className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
            Active path
          </p>
          <p className="mt-1.5 text-[13.5px] font-medium text-slate-200">
            Change Major
          </p>
          <p className="mt-2 text-[12px] text-slate-500">
            {answered} / {total} nodes answered
          </p>
          <div
            className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-violet-400 transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        <p className="px-1 text-[12.5px] italic leading-relaxed text-slate-600">
          &ldquo;Understand every consequence.
          <br />
          Make the right move.&rdquo;
        </p>
      </div>
    </nav>
  );
}
