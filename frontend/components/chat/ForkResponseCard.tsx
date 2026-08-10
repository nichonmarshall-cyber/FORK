"use client";

import { useState } from "react";
import { NODES_BY_ID } from "@/lib/nodes";
import { ExplainResponse } from "@/lib/types";

/**
 * One Fork answer, rendered as a left-aligned response card.
 *
 * Visual hierarchy is deliberate and follows the spec's ordering: the
 * direct answer dominates, key points sit at medium weight, next step is
 * a compact highlight, still-useful-for is supportive, limitations are
 * collapsed by default, and related nodes are small pills at the bottom.
 * No section renders at all when it has no content — an empty "Still
 * useful for" heading is worse than no heading.
 *
 * There is no Markdown parsing anywhere in here on purpose. The
 * structured schema is what produces emphasis (separate title and
 * explanation fields + CSS weight), so the model never needs to emit
 * "**bold**" and this component never needs to interpret it. That's what
 * makes literal asterisks structurally impossible rather than merely
 * filtered.
 */
export default function ForkResponseCard({
  answer,
  onSelectNode,
}: {
  answer: ExplainResponse;
  onSelectNode: (id: string) => void;
}) {
  return (
    <div className="flex gap-2.5">
      <ForkAvatar />
      <div className="min-w-0 flex-1 space-y-2.5 rounded-2xl rounded-tl-sm border border-white/[0.07] bg-white/[0.02] px-3.5 py-3">
        <p className="text-[13px] font-medium leading-relaxed text-slate-100">
          {answer.direct_answer}
        </p>

        {answer.key_points.length > 0 && (
          <ul className="space-y-1.5">
            {answer.key_points.map((kp) => (
              <li key={kp.title} className="text-[12.5px] leading-relaxed">
                <span className="font-medium text-slate-300">{kp.title}: </span>
                <span className="text-slate-400">{kp.explanation}</span>
              </li>
            ))}
          </ul>
        )}

        {answer.next_step && (
          <div className="rounded-lg border-l-2 border-cyan-400/50 bg-cyan-400/[0.04] py-1.5 pl-2.5 pr-2">
            <p className="text-[12.5px] font-medium text-slate-100">
              {answer.next_step.action}
            </p>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-slate-400">
              {answer.next_step.reason}
            </p>
          </div>
        )}

        {answer.still_useful_for.length > 0 && (
          <div>
            <p className="text-[10.5px] uppercase tracking-[0.12em] text-slate-500">
              Still useful for
            </p>
            <ul className="mt-1 space-y-0.5">
              {answer.still_useful_for.map((item) => (
                <li key={item} className="text-[11.5px] leading-relaxed text-slate-400">
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}

        {answer.limitations.length > 0 && (
          <LimitationsDisclosure limitations={answer.limitations} />
        )}

        {answer.used_fallback && (
          <p className="text-[11px] text-slate-600">
            Simplified summary — built directly from the calculation.
          </p>
        )}

        {answer.related_node_ids.length > 0 && (
          <RelatedNodeLinks
            nodeIds={answer.related_node_ids}
            onSelectNode={onSelectNode}
          />
        )}
      </div>
    </div>
  );
}

function LimitationsDisclosure({
  limitations,
}: {
  limitations: ExplainResponse["limitations"];
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-white/[0.06] pt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between rounded text-left focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400/60"
      >
        <span className="text-[10.5px] uppercase tracking-[0.12em] text-slate-500">
          Limitations and assumptions · {limitations.length}
        </span>
        <span aria-hidden className="text-[13px] text-slate-500">
          {open ? "−" : "+"}
        </span>
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {limitations.map((lim) => (
            <li key={lim.title} className="text-[11.5px] leading-relaxed">
              <span className="font-medium text-slate-400">{lim.title}: </span>
              <span className="text-slate-500">{lim.explanation}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RelatedNodeLinks({
  nodeIds,
  onSelectNode,
}: {
  nodeIds: string[];
  onSelectNode: (id: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5 pt-0.5">
      {nodeIds.map((id) => {
        // Defensive despite the backend already filtering against real
        // ids — rendering a chip for a node that doesn't exist would
        // produce a dead click, so skip rather than trust.
        const node = NODES_BY_ID.get(id);
        if (!node) return null;
        return (
          <button
            key={id}
            type="button"
            onClick={() => onSelectNode(id)}
            className="rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[11px] text-slate-400 transition hover:border-cyan-400/40 hover:text-cyan-300 focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400/60"
          >
            {node.label}
          </button>
        );
      })}
    </div>
  );
}

export function ForkAvatar() {
  return (
    <span
      aria-hidden
      className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-cyan-400/25 bg-cyan-400/10 text-[10px] font-semibold text-cyan-300"
    >
      F
    </span>
  );
}