"use client";

/**
 * Detail panel for the selected node.
 *
 * Structure follows what a student actually needs in order: what this node
 * is asking, the number if we have one, what we already know, what's still
 * missing, and then the provenance. "Why am I seeing this?" isn't buried in
 * a tooltip — it's the point of the product.
 *
 * Source strings render exactly as the engine supplied them, PLACEHOLDER
 * included. A visible placeholder is honest; a hidden one isn't.
 */

import { useState } from "react";
import { BRANCH_COLOR, NodeDef, NodeState, STATE_LABEL } from "@/lib/nodes";
import { CalcResult } from "@/lib/types";

const STATE_TONE: Record<NodeState, string> = {
  completed: "#34d399",
  at_risk: "#fbbf24",
  needs_info: "#38bdf8",
  locked: "#8493ab",
  idle: "#64748b",
};

interface Props {
  node: NodeDef | null;
  result: CalcResult | null;
  onClose: () => void;
}

export default function NodePanel({ node, result, onClose }: Props) {
  const [showWhy, setShowWhy] = useState(true);

  if (!node) {
    return (
      <aside className="flex h-full flex-col justify-center rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-8 text-center">
        <p className="text-sm leading-relaxed text-slate-500">
          Select any node on the map to see what it means, where its number
          came from, and what it assumes.
        </p>
      </aside>
    );
  }

  const r = node.resolve(result);
  const color = BRANCH_COLOR[node.branch];
  const tone = STATE_TONE[r.state];

  return (
    <aside className="flex h-full flex-col overflow-hidden rounded-2xl border border-white/[0.07] bg-[#0a0e17]">
      <header className="flex items-start justify-between gap-3 border-b border-white/[0.07] px-5 py-4">
        <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-slate-500">
          Node details
        </span>
        <button
          onClick={onClose}
          aria-label="Close details"
          className="-mt-1 rounded p-1 text-slate-500 transition hover:bg-white/5 hover:text-slate-300"
        >
          ✕
        </button>
      </header>

      <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
        <div className="flex items-start gap-3.5">
          <span
            className="mt-0.5 h-9 w-9 shrink-0 rounded-full border-2"
            style={{
              borderColor: color,
              boxShadow: `0 0 14px ${color}55`,
              borderStyle: r.state === "needs_info" ? "dashed" : "solid",
            }}
          />
          <div>
            <h2 className="text-[17px] font-semibold leading-tight text-slate-100">
              {node.label}
            </h2>
            <p className="mt-0.5 text-[13px] font-medium" style={{ color: tone }}>
              {STATE_LABEL[r.state]}
            </p>
          </div>
        </div>

        <p className="text-[13.5px] leading-relaxed text-slate-400">
          {node.question}
        </p>

        {r.display && (
          <div
            className="rounded-xl border px-4 py-3.5"
            style={{ borderColor: `${color}40`, background: `${color}0d` }}
          >
            <p className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
              {r.lineItem?.label ?? "Value"}
            </p>
            <p
              className="mt-1 text-[28px] font-semibold leading-none tabular-nums"
              style={{ color }}
            >
              {r.display}
            </p>
          </div>
        )}

        {r.known && r.known.length > 0 && (
          <Section title="What we know">
            <ul className="space-y-2">
              {r.known.map((k) => (
                <li key={k} className="flex items-start gap-2.5">
                  <CheckMark />
                  <span>{k}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {r.stillNeed && r.stillNeed.length > 0 && (
          <Section title="What we still need">
            <ul className="space-y-2">
              {r.stillNeed.map((s) => (
                <li key={s} className="flex items-start gap-2.5">
                  <PendingMark />
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {r.reason && (
          <Section
            title={r.state === "locked" ? "Why this is empty" : "Why it matters"}
          >
            {r.reason}
          </Section>
        )}

        {r.lineItem && (
          <section>
            <button
              onClick={() => setShowWhy((v) => !v)}
              aria-expanded={showWhy}
              className="flex w-full items-center justify-between rounded-xl border border-white/[0.09] bg-white/[0.02] px-4 py-3 text-left text-[13.5px] font-medium text-slate-200 transition hover:bg-white/[0.05]"
            >
              Why am I seeing this?
              <span className="text-slate-500">{showWhy ? "−" : "+"}</span>
            </button>

            {showWhy && (
              <div className="mt-3 space-y-5 rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-4">
                <Field label="Where this number came from">
                  {r.lineItem.source}
                </Field>

                {r.derivedFrom && r.derivedFrom.length > 0 && (
                  <Field label="Calculated from">
                    <ul className="space-y-2">
                      {r.derivedFrom.map((li, i) => (
                        <li key={`${li.label}-${i}`}>
                          <div className="flex justify-between gap-3">
                            <span className="text-slate-400">{li.label}</span>
                            <span className="shrink-0 tabular-nums text-slate-200">
                              {li.value.toLocaleString("en-US")}
                            </span>
                          </div>
                          <p className="mt-0.5 text-[11.5px] leading-snug text-slate-600">
                            {li.source}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </Field>
                )}

                <Field label="Current as of">{r.lineItem.source_date}</Field>

                {result && (
                  <>
                    <Field label="What this assumes">
                      <Bullets items={result.why_am_i_seeing_this.assumptions} />
                    </Field>
                    <Field label="What this does not tell you">
                      <Bullets items={result.why_am_i_seeing_this.limitations} />
                    </Field>
                  </>
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </aside>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-white/[0.07] pt-5">
      <h3 className="text-[13px] font-semibold text-slate-200">{title}</h3>
      <div className="mt-2.5 text-[13px] leading-relaxed text-slate-400">
        {children}
      </div>
    </section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
        {label}
      </p>
      <div className="mt-1.5 text-[12.5px] leading-relaxed text-slate-300">
        {children}
      </div>
    </div>
  );
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1.5">
      {items.map((t) => (
        <li key={t} className="flex gap-2">
          <span className="text-slate-600">·</span>
          <span>{t}</span>
        </li>
      ))}
    </ul>
  );
}

function CheckMark() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" className="mt-1 shrink-0" aria-hidden>
      <path
        d="M2.5 7.5 L5.5 10.5 L11.5 3.5"
        fill="none"
        stroke="#34d399"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PendingMark() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" className="mt-1 shrink-0" aria-hidden>
      <circle
        cx="7"
        cy="7"
        r="5"
        fill="none"
        stroke="#38bdf8"
        strokeWidth="1.6"
        strokeDasharray="2.6 2.2"
      />
    </svg>
  );
}
